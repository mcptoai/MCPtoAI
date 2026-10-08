"""Uzun süren komut görevleri (jobs).

Görevler sohbet turundan ve modelden bağımsızdır:
- Durum diskte tutulur (config_dir()/jobs/<görev>/state.json); model değişse de yeni
  model görevleri görür ve devam edebilir.
- Komut kendi süreç grubunda çalışır, çıktısı doğrudan dosyaya yazılır. Agent yeniden
  başlasa ya da relay bağlantısı kopsa bile görev sürer.
- Çıkış kodunu, komutu saran küçük bir kabuk dosyaya yazar; agent süreci beklemese de
  sonuç kaybolmaz.
- "Çalışıyor mu" kontrolü süreç numarasının yanında komut satırında görev kimliğinin
  bulunmasına da bakar (süreç numarası yeniden kullanılabilir).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

from .paths import config_dir

JOB_ID_RE = re.compile(r"^job-[a-f0-9]{12}$")
MAX_RUNNING = 4
RETENTION_SECONDS = 7 * 24 * 3600
TAIL_BYTES = 64 * 1024
# "Çalışıyor" sonucu bu süre yeniden kullanılır (Windows'ta her kontrol bir PowerShell süreci
# başlatır). Bitiş anında, çıkış kodu dosyasından anlaşılır; önbellek bunu geciktirmez.
ALIVE_CACHE_SECONDS = 30

# Çıktı modele ve sunucuya gider; bilinen sır biçimleri maskelenir.
_SECRET_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
]
_PROGRESS_PATTERNS = [
    ("epoch", re.compile(r"[Ee]poch[\s:]*(\d+)\s*/\s*(\d+)")),
    ("step", re.compile(r"[Ss]tep[\s:]*(\d+)\s*/\s*(\d+)")),
    ("percent", re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%")),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[GİZLENDİ]", text)
    return text


def parse_progress(text: str) -> dict:
    """Son satırlardan ilerleme bilgisi çıkarır (epoch x/y, step x/y, yüzde)."""
    found: dict = {}
    for line in reversed(text.splitlines()[-200:]):
        for key, pattern in _PROGRESS_PATTERNS:
            if key in found:
                continue
            matches = pattern.findall(line)
            if not matches:
                continue
            last = matches[-1]
            if key == "percent":
                value = float(last)
                if 0 <= value <= 100:
                    found[key] = value
            else:
                current, total = int(last[0]), int(last[1])
                if 0 < total and current <= total:
                    found[key] = {"current": current, "total": total}
        if len(found) == len(_PROGRESS_PATTERNS):
            break
    return found


def _fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h} sa {m} dk" if h else (f"{m} dk {s} sn" if m else f"{s} sn")


class JobError(RuntimeError):
    pass


class JobManager:
    def __init__(self, root: Path | None = None, env_factory: Callable[[], dict] | None = None):
        self.root = Path(root) if root else config_dir() / "jobs"
        self.env_factory = env_factory or (lambda: dict(os.environ))
        self._procs: dict[str, subprocess.Popen] = {}
        self._alive_cache: dict[str, float] = {}

    # --- yardımcılar -------------------------------------------------------
    def _dir(self, job_id: str) -> Path:
        if not JOB_ID_RE.match(str(job_id or "")):
            raise JobError(f"Geçersiz görev kimliği: {job_id!r}")
        return self.root / job_id

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.root, 0o700)

    def _read_state(self, job_id: str) -> dict:
        path = self._dir(job_id) / "state.json"
        # Başka bir süreç dosyayı o an değiştiriyorsa (Windows ta kısa kilit) birkaç kez dene.
        for attempt in range(5):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise JobError(f"Görev bulunamadı: {job_id}") from None
            except (PermissionError, json.JSONDecodeError):
                if attempt == 4:
                    raise
                time.sleep(0.05)

    def _write_state(self, job_id: str, state: dict) -> None:
        d = self._dir(job_id)
        tmp = d / "state.json.tmp"
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, d / "state.json")

    def _exit_code(self, job_id: str) -> int | None:
        try:
            raw = (self._dir(job_id) / "exit_code").read_text(encoding="ascii", errors="ignore").strip()
            return int(raw) if raw.lstrip("-").isdigit() else None
        except OSError:
            # Dosya yok ya da Windows ta move sırasında kısa bir an kilitli: henüz hazır değil.
            return None

    def _alive(self, job_id: str, pid: int) -> bool:
        """Süreç yaşıyor ve gerçekten bu göreve ait mi (komut satırında görev kimliği)."""
        proc = self._procs.get(job_id)
        if proc is not None and proc.poll() is not None:
            return False  # kendi çocuğumuzsa poll() zombiyi de temizler
        if time.time() - self._alive_cache.get(job_id, 0) < ALIVE_CACHE_SECONDS:
            return True
        alive = self._alive_uncached(job_id, pid)
        if alive:
            self._alive_cache[job_id] = time.time()
        else:
            self._alive_cache.pop(job_id, None)
        return alive

    def _alive_uncached(self, job_id: str, pid: int) -> bool:
        """Süreç yaşıyor ve gerçekten bu göreve ait mi.

        Linux'ta /proc'tan okunur. `ps` kullanılmaz: çıktısı bir terminale gitmediğinde
        (systemd servisi) 80 sütunda kesilir ve komut satırındaki görev kimliği kaybolur;
        her çalışan görev "kesildi" görünürdü.
        """
        try:
            with open(f"/proc/{int(pid)}/stat", "rb") as f:
                stat = f.read()
            # Durum harfi, komut adının kapanış parantezinden sonra gelir (ad boşluk içerebilir).
            state = stat[stat.rfind(b")") + 2:stat.rfind(b")") + 3]
            if state == b"Z":
                return False
            with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
                cmdline = f.read()
        except (OSError, ValueError):
            return False
        return job_id.encode() in cmdline

    def _tail(self, job_id: str, lines: int) -> str:
        path = self._dir(job_id) / "output.log"
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - TAIL_BYTES))
                data = f.read()
        except FileNotFoundError:
            return ""
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        # İlerleme çubukları satırı \r ile yeniden yazar; yalnızca son halini tut.
        text = "\n".join(seg.split("\r")[-1] for seg in text.split("\n"))
        return redact("\n".join(text.splitlines()[-max(1, min(int(lines), 400)):]))

    def _refresh(self, job_id: str, state: dict) -> dict:
        """Diskteki durumu süreçle karşılaştırıp günceller."""
        if state.get("status") != "running":
            return state
        code = self._exit_code(job_id)
        if code is None and not self._alive(job_id, state["pid"]):
            # Görev iki kontrol arasında bitmiş olabilir (önce dosya yok, sonra süreç kapanmış):
            # "kesildi" demeden önce çıkış kodunu bir kez daha oku.
            code = self._exit_code(job_id)
            if code is None:
                # Sarmalayıcı çıkış kodunu yazamadan durdu: makine yeniden başladı ya da süreç öldürüldü.
                state.update(status="interrupted", finished_at=time.time())
                self._procs.pop(job_id, None)
                self._write_state(job_id, state)
                return state
        if code is not None:
            # Bitiş zamanı, sorgu anı değil çıkış kodunun yazıldığı an.
            try:
                finished = os.path.getmtime(self._dir(job_id) / "exit_code")
            except OSError:
                finished = time.time()
            state.update(status="finished", exit_code=code, finished_at=finished)
            self._procs.pop(job_id, None)
            self._write_state(job_id, state)
        return state

    # --- genel arayüz ------------------------------------------------------
    def start(self, command: str, *, cwd: Path | None = None, name: str = "", session_id: str = "") -> dict:
        command = str(command or "").strip()
        if not command:
            raise JobError("Komut boş olamaz.")
        running = [j for j in self.list() if j["status"] == "running"]
        if len(running) >= MAX_RUNNING:
            raise JobError(f"Aynı anda en fazla {MAX_RUNNING} görev çalışabilir; önce birini bitirin ya da durdurun.")
        self._ensure_root()
        job_id = "job-" + secrets.token_hex(6)
        d = self._dir(job_id)
        d.mkdir(mode=0o700)
        exit_file = d / "exit_code"
        if os.name == "nt":
            # Komut argüman olarak geçirilmez (PowerShell 5.1 iç içe tırnakları bozar); toplu iş
            # dosyasına yazılır ve cmd onu elle yazılmış gibi yorumlar. Toplu iş dosyalarında
            # % kaçırılmalıdır; dosya cmd'nin okuduğu konsol kod sayfasıyla (OEM) yazılır.
            script = "\r\n".join([
                "@echo off",
                "call :run",
                '>"%~dp0exit_code.tmp" echo %ERRORLEVEL%',
                'move /y "%~dp0exit_code.tmp" "%~dp0exit_code" >nul',
                "exit /b",
                ":run",
                command.replace("%", "%%"),
                "exit /b %ERRORLEVEL%",
                "",
            ])
            try:
                (d / "run.cmd").write_bytes(script.encode("oem"))
            except UnicodeEncodeError:
                shutil.rmtree(d, ignore_errors=True)
                raise JobError("Komut, Windows konsol kod sayfasında gösterilemeyen karakterler içeriyor.") from None
            args = ["cmd.exe", "/d", "/c", str(d / "run.cmd")]
            extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        else:
            # Komut ve dosya yolu kabuğa argüman olarak verilir; tırnaklama sorunu olmaz.
            args = ["/bin/sh", "-c", 'eval "$1"; code=$?; printf "%s" "$code" > "$2.tmp" && mv "$2.tmp" "$2"',
                    f"mcptoai-{job_id}", command, str(exit_file)]
            extra = {"start_new_session": True}
        with open(d / "output.log", "ab") as out:
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                    cwd=str(cwd) if cwd else None, env=self.env_factory(), close_fds=True, **extra)
        self._procs[job_id] = proc
        state = {"id": job_id, "name": str(name or "")[:120], "command": command[:4000],
                 "cwd": str(cwd) if cwd else "", "pid": proc.pid, "status": "running",
                 "started_at": time.time(), "session_id": str(session_id or "")[:128], "acknowledged": False}
        self._write_state(job_id, state)
        return self._public(state, tail="")

    def status(self, job_id: str, lines: int = 40) -> dict:
        state = self._refresh(job_id, self._read_state(job_id))
        tail = self._tail(job_id, lines)
        if state["status"] != "running" and not state.get("acknowledged"):
            # Sonuç bir modele (ve dolayısıyla kullanıcıya) iletildi.
            state["acknowledged"] = True
            self._write_state(job_id, state)
        return self._public(state, tail=tail)

    def view(self, job_id: str, lines: int = 20) -> dict:
        """Durumu okur ama görevi "kullanıcıya bildirildi" olarak işaretlemez (web izleyicisi
        için). Böylece "Devam edeyim mi?" kuralı modelin sonucu görmesine bağlı kalır."""
        state = self._refresh(job_id, self._read_state(job_id))
        return self._public(state, tail=self._tail(job_id, lines))

    def stop(self, job_id: str) -> dict:
        state = self._refresh(job_id, self._read_state(job_id))
        if state["status"] != "running":
            return self._public(state, tail=self._tail(job_id, 20))
        pid = int(state["pid"])
        # Durdurulan görevin canlı önbellek kaydı kalmamalı (her platformda).
        self._alive_cache.pop(job_id, None)
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
            end = time.time() + 5
            while time.time() < end and self._alive_uncached(job_id, pid):
                time.sleep(0.2)
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        proc = self._procs.pop(job_id, None)
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        state.update(status="stopped", finished_at=time.time(), acknowledged=True)
        self._write_state(job_id, state)
        return self._public(state, tail=self._tail(job_id, 20))

    def list(self) -> list[dict]:
        if not self.root.exists():
            return []
        now = time.time()
        result = []
        for d in sorted(self.root.iterdir()):
            if not JOB_ID_RE.match(d.name) or not (d / "state.json").exists():
                continue
            try:
                state = self._refresh(d.name, self._read_state(d.name))
            except (JobError, ValueError, OSError):
                continue
            finished = state.get("finished_at")
            if state["status"] != "running" and finished and now - finished > RETENTION_SECONDS:
                shutil.rmtree(d, ignore_errors=True)  # bir haftadan eski biten görevler temizlenir
                continue
            result.append(self._public(state, tail=None))
        return sorted(result, key=lambda j: j["started_at"])

    def prompt_summary(self) -> str:
        """Her turda sistem talimatına eklenir; model değişse de görevler bilinir."""
        jobs = [j for j in self.list() if j["status"] == "running" or not j["acknowledged"]]
        if not jobs:
            return ""
        lines = ["Cihazda modelden bağımsız uzun süreli görevler var (ayrıntı için job_status):"]
        for j in jobs:
            label = f'{j["id"]}' + (f' "{j["name"]}"' if j["name"] else "")
            if j["status"] == "running":
                prog = j.get("progress") or {}
                extra = ""
                if "epoch" in prog:
                    extra = f', epoch {prog["epoch"]["current"]}/{prog["epoch"]["total"]}'
                elif "percent" in prog:
                    extra = f', %{prog["percent"]:g}'
                lines.append(f"- {label}: çalışıyor ({_fmt_duration(j['elapsed_seconds'])}{extra})")
            else:
                code = j.get("exit_code")
                lines.append(f"- {label}: {j['status']}" + (f" (çıkış kodu {code})" if code is not None else "")
                             + ", sonucu kullanıcıya henüz bildirilmedi")
        lines.append("Kural: Biten bir görevin sonucunu job_status ile al, kullanıcıya özetle ve bir sonraki "
                     "adıma geçmeden önce 'Devam edeyim mi?' diye sor. Kullanıcı onaylamadan yeni görev ya da "
                     "komut başlatma.")
        return "\n".join(lines)

    def _public(self, state: dict, *, tail: str | None) -> dict:
        end = state.get("finished_at") or time.time()
        view = {k: state.get(k) for k in ("id", "name", "command", "cwd", "status", "exit_code",
                                         "started_at", "finished_at", "acknowledged")}
        view["command"] = redact(view["command"] or "")
        view["elapsed_seconds"] = round(end - state["started_at"], 1)
        if tail is None:
            tail = self._tail(state["id"], 200) if state["status"] == "running" else ""
            view["progress"] = parse_progress(tail) if tail else {}
        else:
            view["progress"] = parse_progress(tail) if tail else {}
            view["output_tail"] = tail
        return view


_default: JobManager | None = None


def default_manager(env_factory: Callable[[], dict] | None = None) -> JobManager:
    """Süreç genelinde tek görev yöneticisi (aynı kök klasör)."""
    global _default
    if _default is None:
        _default = JobManager(env_factory=env_factory)
    elif env_factory is not None:
        _default.env_factory = env_factory
    return _default
