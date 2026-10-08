"""Cihaz araçları için süreç içi FastMCP sunucusu.

Kaynak: uhm-mac-app/server.py. Farklar:
- Auth0 yok: sunucu dışarı açılmaz, agent döngüsü ona bellek içinden bağlanır.
- Sınırsız shell varsayılan olarak kapalı (MCPTOAI_ENABLE_SHELL=true ile açılır).
- safe_tool artık async araçları da doğru sarıyor (UHM'deki sürüm coroutine
  içindeki hataları yakalayamıyordu).
"""

from __future__ import annotations

import inspect
import asyncio
import base64
import locale
import signal
import io
import json
import logging
import os
import re
import subprocess
import socket
import platform
import shutil
import webbrowser
import ipaddress
import httpx
import httpcore
from httpcore._backends.sync import SyncBackend
from html.parser import HTMLParser
from urllib.parse import urlparse
from functools import wraps
from pathlib import Path

from fastmcp import FastMCP

from ..config import Settings
from ..secret_store import get_secret, api_key_name

logger = logging.getLogger("mcptoai.tools")

# Komut içinde bağımsız kelime olarak geçen yetki yükseltme komutunu yakalar.
# Kararlı bir saldırgana karşı sandbox değildir, sadece korkuluktur.
_PRIV = "su" + "do"
_PRIV_PATTERN = re.compile(r"(?:^|[\s;&|`(])" + _PRIV + r"(?:[\s]|$)", re.IGNORECASE)


def build_server(cfg: Settings) -> FastMCP:
    """Ayarlara göre araçları kaydedilmiş bir FastMCP örneği döndürür."""
    mcp = FastMCP("mcptoai-device")

    def _truncate(text: str) -> str:
        limit = cfg.max_output_chars
        if len(text) <= limit:
            return text
        half = limit // 2
        return f"{text[:half]}\n\n... [{len(text) - limit} karakter kırpıldı] ...\n\n{text[-half:]}"

    def _safe_path(path: str, *, must_exist: bool = False) -> Path:
        candidate = Path(path).expanduser().resolve(strict=False)
        if not any(candidate == r or candidate.is_relative_to(r) for r in cfg.allowed_roots):
            roots = ", ".join(map(str, cfg.allowed_roots))
            raise PermissionError(f"Yol izin verilen klasörlerin dışında ({roots}): {candidate}")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(candidate)
        return candidate

    def _command_env() -> dict[str, str]:
        """Komutlar için ortam. Agent soruları yanıtlayamaz: git ve ssh kimlik bilgisi
        ya da parola sormak için beklemek yerine anında hata vermelidir."""
        env = {**os.environ, "PATH": os.getenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")}
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        if not env.get("GIT_SSH_COMMAND"):
            env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
        return env

    def _run(args, *, timeout: int | None = None, cwd: Path | None = None, shell: bool = False) -> str:
        timeout = max(1, min(int(timeout or cfg.default_cmd_timeout), cfg.max_cmd_timeout))
        try:
            # stdin kapalı: alt süreç agent'ın girdisini (Desktop'ın onay/iptal kanalı) devralmasın.
            result = subprocess.run(
                args, shell=shell, cwd=cwd, capture_output=True, text=True,
                timeout=timeout, errors="replace", stdin=subprocess.DEVNULL, env=_command_env(),
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
            err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
            return _truncate(f"[ERROR] {timeout} sn sonra zaman aşımı\n{out}{err}".strip())
        output = (result.stdout + result.stderr).strip() or "(çıktı yok)"
        prefix = f"[exit={result.returncode}]\n" if result.returncode else ""
        return _truncate(prefix + output)

    async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
        """Komutu ve başlattığı tüm alt süreçleri durdurur: önce nazikçe, 2 sn sonra zorla."""
        if os.name == "nt":
            if proc.returncode is None:
                try:
                    k = await asyncio.create_subprocess_exec(
                        "taskkill", "/PID", str(proc.pid), "/T", "/F",
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    await asyncio.wait_for(k.wait(), 10)
                except (OSError, asyncio.TimeoutError):
                    pass
        else:
            # Kabuk çıkmış olsa da grubunda kalan alt süreçler olabilir; gruba her zaman sinyal gönder.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            try:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except asyncio.TimeoutError:
                logger.warning("Komut süreci durdurulamadı: pid=%s", proc.pid)
        if os.name != "nt":
            # Grupta kalmış son süreçler (kabuk SIGTERM'den önce çıkmışsa) için son temizlik.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass

    async def _arun(command: str, *, timeout: int | None = None, cwd: Path | None = None) -> str:
        """Kabuk komutunu olay döngüsünü tıkamadan çalıştırır.

        Komut kendi süreç grubunda başlar; görev iptal edilirse (Durdur) ya da süre
        dolarsa komut ve alt süreçleri öldürülür. stdout ve stderr birleşik okunur.
        """
        timeout = max(1, min(int(timeout or cfg.default_cmd_timeout), cfg.max_cmd_timeout))
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      cwd=cwd, env=_command_env())
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_shell(command, **kwargs)
        buf = bytearray()
        limit = max(cfg.max_output_chars * 4, 65536)  # bellek sınırı; fazlası okunup atılır

        async def drain() -> None:
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    return
                if len(buf) < limit:
                    buf.extend(chunk[: limit - len(buf)])

        # Çıktı, subprocess(text=True) ile aynı kodlamayla çözülür (Windows'ta yerel kod sayfası).
        encoding = locale.getpreferredencoding(False)
        try:
            await asyncio.wait_for(asyncio.gather(drain(), proc.wait()), timeout)
        except asyncio.TimeoutError:
            await _kill_tree(proc)
            out = buf.decode(encoding, errors="replace").strip()
            return _truncate(f"[ERROR] {timeout} sn sonra zaman aşımı; komut ve alt süreçleri durduruldu\n{out}".strip())
        except asyncio.CancelledError:
            # Durdur: iptal devam ederken bile süreç ağacının öldürülmesi tamamlanmalı.
            await asyncio.shield(_kill_tree(proc))
            raise
        output = buf.decode(encoding, errors="replace").strip() or "(çıktı yok)"
        prefix = f"[exit={proc.returncode}]\n" if proc.returncode else ""
        return _truncate(prefix + output)

    def _reject_privileged(command: str) -> None:
        if _PRIV_PATTERN.search(command):
            raise PermissionError("Yetki yükseltme uzak bağlantı üzerinden engellidir.")

    def safe_tool(fn):
        """Araç hatalarını modele kısa metin olarak döndürür; tam traceback sadece loglanır."""
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def awrapper(*a, **kw):
                try:
                    return await fn(*a, **kw)
                except Exception as exc:
                    logger.exception("Araç hatası: %s", fn.__name__)
                    return f"[ERROR] {fn.__name__}: {type(exc).__name__}: {exc}"
            return awrapper

        # Senkron araçlar ayrı bir iş parçacığında çalışır. Olay döngüsünde çalışsalardı
        # araç bitene kadar agent kilitlenir; Durdur, onaylar ve relay işlenemezdi.
        @wraps(fn)
        async def twrapper(*a, **kw):
            try:
                return await asyncio.to_thread(fn, *a, **kw)
            except Exception as exc:
                logger.exception("Araç hatası: %s", fn.__name__)
                return f"[ERROR] {fn.__name__}: {type(exc).__name__}: {exc}"
        return twrapper


    def _resolve_public_http_url(url: str) -> tuple[str, int, tuple[str, ...]]:
        """Validate URL and return the exact public IPs approved for this request.

        The returned addresses must be used for the TCP connection itself.  Merely
        validating DNS here and resolving the hostname again in the HTTP client
        would leave a DNS-rebinding/TOCTOU window.
        """
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only public http(s) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Credentials in URLs are not allowed")
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            raise PermissionError("Local addresses are blocked")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        approved: list[str] = []
        for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                raise PermissionError(f"Private/local address is blocked: {ip}")
            value = str(ip)
            if value not in approved:
                approved.append(value)
        if not approved:
            raise PermissionError("Host did not resolve to a public address")
        return host, port, tuple(approved)

    class _PinnedDNSBackend(SyncBackend):
        """Resolve one validated origin to its pre-approved IPs only."""
        def __init__(self, host: str, port: int, approved_ips: tuple[str, ...]):
            self.host, self.port, self.approved_ips = host, port, approved_ips

        def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            if host.rstrip('.').lower() != self.host or port != self.port:
                raise httpcore.ConnectError("Unexpected connection origin")
            last = None
            for ip in self.approved_ips:
                try:
                    # TLS still receives the original hostname from httpcore, so
                    # certificate verification/SNI are not weakened by IP pinning.
                    return super().connect_tcp(ip, port, timeout, local_address, socket_options)
                except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                    last = exc
            raise last or httpcore.ConnectError("No approved address available")

    def _pinned_transport(host: str, port: int, approved_ips: tuple[str, ...]) -> httpx.HTTPTransport:
        transport = httpx.HTTPTransport(retries=0)
        # HTTPX does not expose a public DNS-pinning hook. Its sync transport wraps
        # an httpcore pool; replacing only the pool's network backend preserves all
        # HTTP/TLS behaviour while ensuring TCP uses the addresses validated above.
        transport._pool._network_backend = _PinnedDNSBackend(host, port, approved_ips)
        return transport

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__(); self.parts=[]; self.skip=0
        def handle_starttag(self, tag, attrs):
            if tag in {"script","style","noscript","svg"}: self.skip += 1
        def handle_endtag(self, tag):
            if tag in {"script","style","noscript","svg"} and self.skip: self.skip -= 1
        def handle_data(self, data):
            if not self.skip and data.strip(): self.parts.append(data.strip())

    # --- dosya araçları ---------------------------------------------------
    @mcp.tool(description="List a directory inside the allowed roots.")
    @safe_tool
    def list_dir(path: str) -> str:
        """List a directory inside the allowed roots."""
        target = _safe_path(path, must_exist=True)
        rows = []
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            kind = "d" if entry.is_dir() else "f"
            size = entry.stat().st_size if entry.is_file() else 0
            rows.append(f"{kind} {size:>12} {entry.name}")
        return _truncate("\n".join(rows) or "(boş)")

    @mcp.tool(description="Read a UTF-8 text file inside the allowed roots.")
    @safe_tool
    def read_file(path: str) -> str:
        """Read a UTF-8 text file inside the allowed roots."""
        target = _safe_path(path, must_exist=True)
        if target.stat().st_size > cfg.max_read_bytes:
            return f"[ERROR] Dosya çok büyük (> {cfg.max_read_bytes} bayt)"
        return _truncate(target.read_text(errors="replace"))

    @mcp.tool(description="Write a UTF-8 file inside the allowed roots; refuses overwrite by default.")
    @safe_tool
    def write_file(path: str, content: str, overwrite: bool = False) -> str:
        """Write a UTF-8 file inside the allowed roots; refuses overwrite by default."""
        target = _safe_path(path)
        if target.exists() and not overwrite:
            return f"[ERROR] Dosya zaten var: {target} (overwrite=true gerekli)"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Yazıldı: {target} ({len(content)} karakter)"

    @mcp.tool(description="Recursively find files matching a glob pattern under a root, largest first.")
    @safe_tool
    def find_files(root: str, pattern: str = "*", limit: int = 200) -> str:
        """Recursively find files matching a glob pattern under a root, largest first."""
        base = _safe_path(root, must_exist=True)
        hits = [p for p in base.rglob(pattern) if p.is_file()]
        hits.sort(key=lambda p: p.stat().st_size, reverse=True)
        lines = [f"{p.stat().st_size:>12} {p}" for p in hits[: max(1, min(limit, 1000))]]
        return _truncate("\n".join(lines) or "(eşleşme yok)")

    # --- sistem araçları --------------------------------------------------
    @mcp.tool(description="Show disk usage for the configured roots using portable Python APIs.")
    @safe_tool
    def disk_usage() -> str:
        """Show disk usage for the configured roots using portable Python APIs."""
        roots = []
        for root in cfg.allowed_roots:
            anchor = Path(root).anchor or str(root)
            if anchor not in roots: roots.append(anchor)
        rows = ["Path                 Total        Used        Free   Used%"]
        for root in roots:
            try:
                total, used, free = shutil.disk_usage(root)
                gb = lambda n: f"{n / (1024**3):.1f} GB"
                rows.append(f"{root:<20} {gb(total):>10} {gb(used):>10} {gb(free):>10} {used/total*100:6.1f}%")
            except OSError as exc: rows.append(f"{root}: [ERROR] {exc}")
        return _truncate("\n".join(rows))

    @mcp.tool(description="List the top processes by memory usage on macOS, Windows, or Linux.")
    @safe_tool
    def running_processes() -> str:
        """List the top processes by memory usage on macOS, Windows, or Linux."""
        system = platform.system()
        if system == "Windows":
            script = "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20 Id,ProcessName,@{N='MemoryMB';E={[math]::Round($_.WorkingSet64/1MB,1)}} | Format-Table -AutoSize"
            return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
        return _run(["ps", "-axo", "pid=,rss=,comm=", "-r"])

    @mcp.tool(description="Launch an application as the current desktop user.")
    @safe_tool
    def open_app(name: str) -> str:
        """Launch an application as the current desktop user."""
        if not name or any(c in name for c in "\r\n\0"):
            return "[ERROR] Invalid application name"
        system = platform.system()
        if system == "Darwin": return _run(["open", "-a", name])
        if system == "Windows":
            try:
                os.startfile(name)  # type: ignore[attr-defined]
                return f"Opened: {name}"
            except OSError:
                return _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Start-Process -FilePath $args[0]", name])
        return _run(["xdg-open", name])


    @mcp.tool(description="Capture the current desktop and return a bounded JPEG payload for the MCPtoAI UI. Requires user approval.")
    @safe_tool
    def capture_screen() -> str:
        """Capture the current desktop and return a bounded JPEG payload for the MCPtoAI UI. Requires user approval."""
        from PIL import ImageGrab

        image = ImageGrab.grab(all_screens=True) if platform.system() == "Windows" else ImageGrab.grab()
        image = image.convert("RGB")
        width, height = image.size
        max_w, max_h = 1600, 1000
        scale = min(1.0, max_w / max(width, 1), max_h / max(height, 1))
        if scale < 1.0:
            image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))

        # WebSocket application messages are capped at 512 KiB. Keep the JPEG
        # substantially below that so base64 + JSON framing remains bounded.
        target_bytes = 300 * 1024
        encoded = b""
        for quality in (72, 64, 56, 48, 40, 34):
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=quality, optimize=True)
            encoded = buf.getvalue()
            if len(encoded) <= target_bytes:
                break
        while len(encoded) > target_bytes and image.width > 800:
            image = image.resize((int(image.width * 0.82), int(image.height * 0.82)))
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=36, optimize=True)
            encoded = buf.getvalue()
        if len(encoded) > target_bytes:
            raise RuntimeError("Screenshot could not be reduced below the safe transfer limit")

        payload = {
            "kind": "screen_capture",
            "mime": "image/jpeg",
            "width": image.width,
            "height": image.height,
            "bytes": len(encoded),
            "data_url": "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii"),
        }
        return json.dumps(payload, separators=(",", ":"))

    @mcp.tool(description="Generate an image with the Replicate image model configured on this device. Requires user approval because the provider may charge for generation.")
    @safe_tool
    def generate_image(prompt: str, aspect_ratio: str = "1:1") -> str:
        """Generate an image with the Replicate image model configured on this device. Requires user approval because the provider may charge for generation."""
        prompt = str(prompt or "").strip()
        if not prompt or len(prompt) > 4000:
            raise ValueError("Prompt must be between 1 and 4000 characters")
        allowed_ratios = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
        if aspect_ratio not in allowed_ratios:
            raise ValueError("Unsupported aspect ratio")
        token = get_secret(api_key_name("replicate"))
        if not token:
            raise RuntimeError("Replicate API token is not configured")
        model = str(cfg.user_settings.get("replicate_image_model") or "black-forest-labs/flux-1.1-pro").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", model):
            raise ValueError("Invalid Replicate model slug")
        url = f"https://api.replicate.com/v1/models/{model}/predictions"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "wait=60"}
        with httpx.Client(timeout=70.0, follow_redirects=False) as client:
            response = client.post(url, headers=headers, json={"input": {"prompt": prompt, "aspect_ratio": aspect_ratio}})
            if response.status_code >= 400:
                try: detail = response.json().get("detail") or response.json().get("error") or response.text
                except Exception: detail = response.text
                raise RuntimeError(f"Replicate request failed ({response.status_code}): {str(detail)[:300]}")
            data = response.json()
            status = data.get("status")
            if status not in {"succeeded", "failed", "canceled"} and data.get("urls", {}).get("get"):
                poll = data["urls"]["get"]
                if not poll.startswith("https://api.replicate.com/"):
                    raise RuntimeError("Unexpected Replicate polling URL")
                for _ in range(30):
                    import time as _time; _time.sleep(2)
                    rr = client.get(poll, headers={"Authorization": f"Bearer {token}"})
                    rr.raise_for_status(); data = rr.json(); status = data.get("status")
                    if status in {"succeeded", "failed", "canceled"}: break
            if data.get("status") != "succeeded":
                raise RuntimeError(f"Replicate prediction {data.get('status') or 'did not complete'}: {str(data.get('error') or '')[:300]}")
            output = data.get("output")
            urls = output if isinstance(output, list) else [output]
            urls = [str(x) for x in urls if isinstance(x, str) and x.startswith("https://")]
            if not urls:
                raise RuntimeError("Replicate returned no image URL")
            return "Generated image URL: " + urls[0]

    @mcp.tool(description="Open an http(s) URL in the default browser.")
    @safe_tool
    def open_url(url: str) -> str:
        """Open an http(s) URL in the default browser."""
        if not url.startswith(("http://", "https://")):
            return "[ERROR] Only http:// or https:// URLs are allowed"
        return "Opened." if webbrowser.open(url, new=2) else "[ERROR] Could not open the default browser"

    @mcp.tool(description="Fetch and read a public web page without opening a browser. Use this to research a URL and inspect its actual page content.")
    @safe_tool
    def web_fetch(url: str) -> str:
        """Fetch and read a public web page without opening a browser. Use this to research a URL and inspect its actual page content."""
        current=url
        for _ in range(5):
            host, port, approved_ips = _resolve_public_http_url(current)
            transport = _pinned_transport(host, port, approved_ips)
            with httpx.Client(transport=transport, follow_redirects=False, timeout=12.0, headers={"User-Agent":"MCPtoAI/0.1 (+https://mcptoai.com)"}) as client:
                r=client.get(current)
            if r.status_code in {301,302,303,307,308} and r.headers.get("location"):
                current=str(httpx.URL(current).join(r.headers["location"])); continue
            r.raise_for_status()
            ctype=r.headers.get("content-type","").lower()
            if not any(x in ctype for x in ("text/","application/json","application/xml","application/xhtml+xml")):
                return f"[ERROR] Unsupported content type: {ctype or 'unknown'}"
            raw=r.content[:1000000]
            text=raw.decode(r.encoding or "utf-8",errors="replace")
            if "html" in ctype:
                parser=_TextExtractor(); parser.feed(text); text="\n".join(parser.parts)
            return _truncate(f"URL: {current}\nStatus: {r.status_code}\nContent-Type: {ctype}\n\n{text}")
        return "[ERROR] Too many redirects"

    # --- yüksek risk: shell (varsayılan kapalı) ----------------------------
    if cfg.enable_shell:
        @mcp.tool(description="Run a shell command as the current user. HIGH RISK. Privilege escalation is blocked.")
        @safe_tool
        async def run_command(command: str, timeout: int = 300) -> str:
            """Run a shell command as the current user. HIGH RISK. Privilege escalation is blocked."""
            _reject_privileged(command)
            return await _arun(command, timeout=timeout)

        @mcp.tool(description="Run a shell command with cwd inside the allowed roots. Privilege escalation is blocked.")
        @safe_tool
        async def run_in_project(command: str, project_path: str, timeout: int = 300) -> str:
            """Run a shell command with cwd inside the allowed roots. Privilege escalation is blocked."""
            _reject_privileged(command)
            cwd = _safe_path(project_path, must_exist=True)
            return await _arun(command, timeout=timeout, cwd=cwd)

        # --- uzun süreli görevler: sohbet turundan ve modelden bağımsız -------
        from ..jobs import default_manager
        jobs = default_manager(env_factory=_command_env)

        @mcp.tool(description="Start a long-running shell command (training, fine-tuning, large builds, downloads) as a background job and return immediately with a job id. Use this instead of run_command for anything that may take more than a few minutes. The job keeps running even if the chat ends, the model changes or the connection drops. Check it later with job_status. Privilege escalation is blocked.")
        @safe_tool
        def job_start(command: str, name: str = "", project_path: str = "") -> str:
            """Start a long-running shell command (training, fine-tuning, large builds, downloads) as a
            background job and return immediately with a job id. Use this instead of run_command for
            anything that may take more than a few minutes. The job keeps running even if the chat
            ends, the model changes or the connection drops. Check it later with job_status.
            Privilege escalation is blocked."""
            _reject_privileged(command)
            cwd = _safe_path(project_path, must_exist=True) if project_path else None
            return json.dumps(jobs.start(command, cwd=cwd, name=name), ensure_ascii=False)

        @mcp.tool(description="Get a background job's status, exit code, progress and the last output lines. When a job has finished, summarise the result for the user and ask whether to continue with the next step before starting anything new.")
        @safe_tool
        def job_status(job_id: str, lines: int = 40) -> str:
            """Get a background job's status, exit code, progress and the last output lines. When a job
            has finished, summarise the result for the user and ask whether to continue with the next
            step before starting anything new."""
            return json.dumps(jobs.status(job_id, lines=lines), ensure_ascii=False)

        @mcp.tool(description="List background jobs on this device (running and recently finished).")
        @safe_tool
        def job_list() -> str:
            """List background jobs on this device (running and recently finished)."""
            return json.dumps(jobs.list(), ensure_ascii=False)

        @mcp.tool(description="Stop a running background job and all of its child processes.")
        @safe_tool
        def job_stop(job_id: str) -> str:
            """Stop a running background job and all of its child processes."""
            return json.dumps(jobs.stop(job_id), ensure_ascii=False)

    return mcp
