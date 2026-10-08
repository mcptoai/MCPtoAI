"""MCPtoAI Linux CLI.

Yalnızca terminalden kullanılır: `mcptoai <komut>`. Arka plan bağlantısı bir systemd
kullanıcı servisidir (`mcptoai service install`). Sırlar terminalden gizli girilir ya da
stdin'den okunur ve doğrudan kasaya yazılır; komut satırı argümanı ya da ortam değişkeni
olarak alınmaz (ps ve /proc/<pid>/environ üzerinden görülmesinler).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import time
from dataclasses import replace

from . import __version__


# --- yardımcılar --------------------------------------------------------------

def _cfg(**over):
    from .config import Settings
    settings = Settings()
    over = {k: v for k, v in over.items() if v}
    return replace(settings, **over) if over else settings


def _paired() -> bool:
    from .auth import _auth_bundle
    try:
        bundle = _auth_bundle()
    except Exception:
        return False
    return bool(bundle.get("refresh_token") and bundle.get("owner_sub"))


def _table(rows) -> None:
    width = max((len(k) for k, _ in rows), default=0)
    for k, v in rows:
        print(f"  {k.ljust(width)}  {v}")


def _fmt_dur(sec) -> str:
    s = int(max(0, sec or 0))
    h, m = divmod(s, 3600)
    m, s = divmod(m, 60)
    return f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")


def _confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False  # terminal yoksa onay verilmiş sayılmaz
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes", "e", "evet"}


def _restart_service_if_running() -> None:
    from . import service
    if service.is_active():
        service.systemctl("restart", service.UNIT_NAME)
        print("Background service restarted to apply the change.")


def _chat_providers() -> dict:
    from .config import Settings
    from .provider_registry import registry
    custom = Settings().user_settings.get("custom_providers") or {}
    return {k: v for k, v in registry(custom).items() if v.get("chat", True) is not False}



# --- self update ---------------------------------------------------------------

def _latest_pypi_version() -> str:
    """Return the latest published mcptoai version from PyPI."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/mcptoai/json",
            headers={"User-Agent": f"MCPtoAI/{__version__} update-check"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.load(response)
        latest = str((payload.get("info") or {}).get("version") or "").strip()
    except Exception as exc:
        raise RuntimeError(f"Could not check PyPI for updates: {exc}") from exc
    if not latest:
        raise RuntimeError("PyPI did not return a latest version for mcptoai")
    return latest


def _update_available(current: str, latest: str) -> bool:
    from packaging.version import InvalidVersion, Version
    try:
        return Version(latest) > Version(current)
    except InvalidVersion as exc:
        raise RuntimeError(f"Invalid package version returned by PyPI: {latest}") from exc


def _detect_update_command(latest: str) -> tuple[list[str], str]:
    """Choose the safest updater for the way the current CLI was installed."""
    import shutil
    from pathlib import Path
    exe = str(Path(sys.executable).resolve())
    normalized = exe.replace("\\", "/")
    if "/pipx/venvs/" in normalized:
        pipx = shutil.which("pipx")
        if not pipx:
            candidate = Path.home()/".local"/"bin"/"pipx"
            if candidate.exists(): pipx = str(candidate)
        if not pipx:
            raise RuntimeError("This looks like a pipx installation, but the pipx command was not found")
        return [pipx, "runpip", "mcptoai", "install", "--upgrade", "--no-cache-dir", "--index-url", "https://pypi.org/simple", f"mcptoai=={latest}"], "pipx"
    # venv/pip install: use the exact interpreter that is running this CLI.
    return [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", "--index-url", "https://pypi.org/simple", f"mcptoai=={latest}"], "pip"


def cmd_update(a) -> None:
    import subprocess
    from . import service
    if os.getenv("MCPTOAI_CONTAINER"):
        raise SystemExit("MCPtoAI is running in Docker. Pull the latest image and recreate/restart the container instead of self-updating the package.")

    current = __version__
    latest = _latest_pypi_version()
    available = _update_available(current, latest)
    print(f"Current version: {current}")
    print(f"Latest version:  {latest}")

    if a.check:
        print("Update available." if available else "MCPtoAI is up to date.")
        return
    if not available:
        print("MCPtoAI is already up to date.")
        return

    command, method = _detect_update_command(latest)
    was_active = service.is_active()
    print(f"Updating with {method}...")
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f"Update failed (exit code {result.returncode}). The background service was not restarted.")

    # Read the installed version using a fresh interpreter/process; this avoids
    # reporting the old __version__ still loaded in the current process.
    verify = subprocess.run(
        [sys.executable, "-c", "import importlib.metadata as m; print(m.version('mcptoai'))"],
        capture_output=True, text=True
    )
    installed = verify.stdout.strip() if verify.returncode == 0 else ""
    if installed != latest:
        raise SystemExit(
            f"Update did not reach {latest} (still {installed or 'unknown'}). "
            "PyPI may still be propagating the new release; wait a moment and run `mcptoai update` again. "
            "The background service was not restarted."
        )
    print(f"Updated: {current} -> {installed}")
    if was_active:
        r = service.systemctl("restart", service.UNIT_NAME)
        if r.returncode == 0:
            print("Background service restarted.")
        else:
            print("Warning: update succeeded but the background service could not be restarted.", file=sys.stderr)
            if r.stderr.strip(): print(r.stderr.strip(), file=sys.stderr)
            print("Run: mcptoai service restart", file=sys.stderr)
    print("Done.")

# --- hesap ---------------------------------------------------------------------

def cmd_login(_a) -> None:
    from .auth import device_login
    sub = asyncio.run(device_login(_cfg()))
    print(f"Device paired: {sub}")
    print()
    print("Connect now:")
    print("  mcptoai connect")
    print()
    print("Keep this machine connected in the background:")
    print("  mcptoai service install")
    print()
    print("Recommended next steps:")
    print("  mcptoai keys set <provider>")
    print("  mcptoai service install")
    print("  mcptoai doctor")


def cmd_logout(_a) -> None:
    from .auth import disconnect_device
    asyncio.run(disconnect_device(_cfg()))
    print("Disconnected.")


def cmd_status(_a) -> None:
    from . import service
    from .auth import device_removed_state
    from .config import local_permission, Settings
    if device_removed_state():
        print("This device was removed from your account. Pair it again.")
        raise SystemExit(2)
    from .jobs import default_manager
    from .secret_store import backend_name, vault_status
    cfg = _cfg()
    try:
        running = sum(1 for j in default_manager().list() if j["status"] == "running")
    except Exception:
        running = "?"
    _table([
        ("Version", __version__),
        ("Paired", "yes" if _paired() else "no  (mcptoai login)"),
        ("Provider / model", f"{cfg.provider} / {cfg.model}"),
        ("Chat history", "this device only" if cfg.user_settings.get("history_provider") == "local" else "MCPtoAI Cloud"),
        ("Vault", f"{backend_name()} ({vault_status()})"),
        ("Terminal commands", "on" if cfg.enable_shell else "off  (mcptoai shell on)"),
        ("Background service", "managed by Docker" if os.getenv("MCPTOAI_CONTAINER") else service.status_line()),
        ("Running jobs", str(running)),
    ])


def cmd_doctor(_a) -> None:
    from . import service
    from .auth import device_removed_state
    from .config import local_permission
    from .secret_store import api_key_name, backend_name, get_secret, vault_status
    cfg = _cfg()
    checks = []

    def check(name, ok, detail):
        checks.append((ok, name, detail))
    check("Server", bool(cfg.server_url), cfg.server_url)
    check("Auth0 configuration", bool(cfg.auth0_domain and cfg.auth0_device_client_id), "configured" if cfg.auth0_domain else "missing")
    vs = vault_status()
    check("Vault", vs in {"ok", "absent"}, f"{backend_name()} ({vs})")
    removed=device_removed_state()
    check("Device paired", not removed and _paired(), "This device was removed from your account. Pair it again." if removed else ("yes" if _paired() else "run: mcptoai login"))
    try:
        has_key = bool(get_secret(api_key_name(cfg.provider)))
    except Exception:
        has_key = False
    info = _chat_providers().get(cfg.provider) or {}
    check(f"API key ({cfg.provider})", has_key or not info.get("key", True), "set" if has_key else f"run: mcptoai keys set {cfg.provider}")
    if os.getenv("MCPTOAI_CONTAINER"):
        print("  Running in a container: the background connection is managed by Docker.")
    else:
        check("Background service", service.is_active(), service.status_line())
        check("Start at boot (linger)", service.linger_enabled(), "on" if service.linger_enabled() else "sudo loginctl enable-linger $USER")
    print(f"  Terminal commands: {'on' if cfg.enable_shell else 'off'}")
    for ok, name, detail in checks:
        print(f"  [{'OK' if ok else '!!'}] {name}: {detail}")
    if not all(ok for ok, _, _ in checks):
        raise SystemExit(1)


# --- çalışma alanı -------------------------------------------------------------

def cmd_workspace(a) -> None:
    from pathlib import Path
    from .config import _user_settings, save_user_settings
    current = _user_settings()
    if a.action == "show":
        chosen = str(current.get("workspace_root") or "").strip()
        if chosen:
            print(f"Workspace: {chosen}")
        else:
            home = Path.home()
            print("Workspace: default")
            for name in ("Desktop", "Documents", "Downloads"):
                print(f"  {home / name}")
        return
    if a.action == "reset":
        current.pop("workspace_root", None)
        save_user_settings(current)
        print("Workspace reset to the default Desktop/Documents/Downloads folders.")
        _restart_service_if_running()
        return
    target = Path(a.path).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"Workspace does not exist: {target}")
    if not target.is_dir():
        raise SystemExit(f"Workspace is not a directory: {target}")
    current["workspace_root"] = str(target)
    save_user_settings(current)
    print(f"Workspace: {target}")
    _restart_service_if_running()


# --- API anahtarları -----------------------------------------------------------

def cmd_keys(a) -> None:
    from .secret_store import api_key_name, backend_name, delete_secret, get_secret, set_secret
    providers = _chat_providers()
    if a.action == "list":
        for pid, info in providers.items():
            if not info.get("key", True):
                continue
            try:
                state = "set" if get_secret(api_key_name(pid)) else "-"
            except Exception as exc:
                state = f"error: {exc}"
            print(f"  {pid.ljust(12)} {info['name'].ljust(26)} {state}")
        return
    if a.provider not in providers:
        raise SystemExit(f"Unknown provider: {a.provider}. See: mcptoai keys list")
    if a.action == "remove":
        delete_secret(api_key_name(a.provider))
        print("Removed.")
        return
    # Anahtar gizli sorulur (terminal) ya da stdin'den okunur (boru); argüman olarak alınmaz.
    if sys.stdin.isatty():
        key = getpass.getpass(f"{providers[a.provider]['name']} API key: ")
    else:
        key = sys.stdin.readline()
    key = key.strip()
    if not key:
        raise SystemExit("Empty key, nothing saved.")
    set_secret(api_key_name(a.provider), key)
    print(f"Saved to vault ({backend_name()}).")


# --- modeller ------------------------------------------------------------------

def cmd_models(a) -> None:
    from .providers import make_provider
    cfg = _cfg(provider=a.provider)
    models = asyncio.run(make_provider(cfg).list_models())
    for m in models:
        mid = m.get("id") if isinstance(m, dict) else str(m)
        print(("* " if mid == cfg.model else "  ") + str(mid))


def cmd_use(a) -> None:
    from .config import _user_settings, save_user_settings
    if a.provider not in _chat_providers():
        raise SystemExit(f"Unknown provider: {a.provider}")
    current = _user_settings()
    model = a.model or (current.get("model") if current.get("provider") == a.provider else "")
    if not model:
        raise SystemExit(f"Choose a model: mcptoai models {a.provider}   then   mcptoai use {a.provider} <model>")
    save_user_settings({**current, "provider": a.provider, "model": model})
    print(f"Default: {a.provider} / {model}")
    _restart_service_if_running()


# --- MCP sunucuları ------------------------------------------------------------

def cmd_mcp(a) -> None:
    from .mcp_config import add_server, custom_servers, remove_server
    if a.action == "list":
        servers = custom_servers()
        if not servers:
            print("No MCP servers. Add one: mcptoai mcp add-http <name> <url>")
        for s in servers:
            target = s.get("url") or " ".join([s.get("command", ""), *s.get("args", [])])
            print(f"  {s['id']}  {s.get('name', '')}  [{s.get('transport', 'stdio')}]  {target}")
        return
    if a.action == "remove":
        print("Removed." if remove_server(a.server_id) else "Not found.")
        _restart_service_if_running()
        return
    if a.action == "add-http":
        item = add_server(a.name, transport="streamable-http", url=a.url)
    else:  # add-stdio: yalnızca bu cihazdan eklenebilir (web'den eklenemez), kod çalıştırır
        print("Warning: a local (stdio) MCP server runs code on this machine with your permissions.")
        if not _confirm(f"Add '{a.name}' running: {' '.join(a.command)}?"):
            raise SystemExit("Cancelled.")
        item = add_server(a.name, command=a.command[0], args=a.command[1:], transport="stdio")
    print(f"Added: {item['id']}. Connecting (sign in if a link is shown)…")
    from .discover_cli import run
    code = run(item["id"])
    _restart_service_if_running()
    if code:
        raise SystemExit(code)


# --- yerel izin: terminal komutları --------------------------------------------

def cmd_shell(a) -> None:
    from .config import local_permission, save_local_permission
    if a.action in {"on", "off"}:
        if a.action == "on" and not a.yes and not _confirm("Allow the AI to run terminal commands and long-running jobs on this machine? Every command still asks for approval."):
            raise SystemExit("Cancelled.")
        save_local_permission("shell", a.action == "on")
        _restart_service_if_running()
    print(f"Terminal commands: {'on' if _cfg().enable_shell else 'off'}")


# --- uzun süreli görevler ------------------------------------------------------

def cmd_jobs(a) -> None:
    from .jobs import default_manager
    mgr = default_manager()
    if a.action == "list":
        jobs = mgr.list()
        if not jobs:
            print("No jobs.")
        for j in jobs:
            p = j.get("progress") or {}
            prog = f"epoch {p['epoch']['current']}/{p['epoch']['total']}" if "epoch" in p else (f"{p['percent']:g}%" if "percent" in p else "")
            code = f" exit={j['exit_code']}" if j.get("exit_code") is not None else ""
            print(f"  {j['id']}  {j['status'].ljust(11)} {_fmt_dur(j['elapsed_seconds']).ljust(8)} {prog.ljust(12)} {j.get('name') or j['command'][:50]}{code}")
        return
    if a.action == "stop":
        if not a.yes and not _confirm(f"Stop {a.job_id}?"):
            raise SystemExit("Cancelled.")
        print(f"Status: {mgr.stop(a.job_id)['status']}")
        return
    # show / logs: görüntüleme görevi "bildirildi" olarak işaretlemez (model sonucu yine sorar)
    view = mgr.view(a.job_id, lines=a.lines)
    if a.action == "show":
        _table([("Job", view["id"]), ("Name", view.get("name") or "-"), ("Status", view["status"]),
                ("Exit code", str(view.get("exit_code"))), ("Elapsed", _fmt_dur(view["elapsed_seconds"])),
                ("Command", view["command"])])
        print()
    follow = a.action == "logs" and getattr(a, "follow", False)
    if view.get("output_tail"):
        print(view["output_tail"])
    elif not follow:
        print("(no output)")
    if follow:
        last = view.get("output_tail") or ""
        while view["status"] == "running":
            time.sleep(2)
            view = mgr.view(a.job_id, lines=a.lines)
            tail = view.get("output_tail") or ""
            if tail != last:
                # Yalnızca yeni satırlar; ayraç satır sonu tekrar basılmaz (boş satır oluşmasın).
                new = tail[len(last):].lstrip("\n") if tail.startswith(last) else tail.splitlines()[-1]
                if new:
                    print(new.rstrip("\n"), flush=True)
                last = tail
        print(f"[{view['status']}{' exit=' + str(view['exit_code']) if view.get('exit_code') is not None else ''}]")


# --- conversation history ------------------------------------------------------

def cmd_history(a) -> None:
    from .config import _user_settings, save_user_settings
    current = _user_settings()
    mode = str(current.get("history_provider") or "mcptoai")
    if a.action == "status":
        print("Conversation history: " + ("this device only" if mode == "local" else "MCPtoAI Cloud"))
        return
    new_mode = "local" if a.action == "local" else "mcptoai"
    if mode == new_mode:
        print("Conversation history: " + ("this device only" if new_mode == "local" else "MCPtoAI Cloud"))
        return
    current["history_provider"] = new_mode
    save_user_settings(current)
    print("Conversation history: " + ("this device only" if new_mode == "local" else "MCPtoAI Cloud"))
    _restart_service_if_running()



# --- terminal sohbeti ----------------------------------------------------------

async def _chat_loop(provider: str, model: str) -> None:
    from .agent import AgentSession
    from .mcp_config import load_rules
    from .policy import Decision, ToolPolicy
    from .providers import make_provider
    from .relay_client import RelayClient
    from .tools import build_server

    cfg = _cfg(provider=provider, model=model)
    remote = RelayClient(cfg)
    try:
        await remote._discover_mcp_tools(allow_oauth_prompt=False)
    except Exception as exc:
        print(f"(MCP tools unavailable: {exc})")
    history: list[dict] = []
    history_mode = "local" if cfg.user_settings.get("history_provider") == "local" else "mcptoai"
    history_chat_id: str | None = None
    history_warning_shown = False

    async def history_action(action: str, **payload):
        nonlocal history_warning_shown
        req={"action":action, **payload}
        try:
            if history_mode == "local":
                from .local_history import LocalHistoryStore
                return await asyncio.to_thread(LocalHistoryStore().handle, req)
            if not _paired():
                return {"ok":False,"error":"device_not_paired"}
            from .relay_client import handle_cloud_chat_request
            return await handle_cloud_chat_request(cfg, req)
        except Exception as exc:
            if not history_warning_shown:
                print(f"(History could not be saved: {exc})")
                history_warning_shown = True
            return {"ok":False,"error":str(exc)}

    async def ensure_history_chat() -> str | None:
        nonlocal history_chat_id
        if history_chat_id:
            return history_chat_id
        result=await history_action("cloud_chat_create",title="New chat",provider=cfg.provider,model=cfg.model)
        if result.get("ok") and isinstance(result.get("data"),dict):
            history_chat_id=str(result["data"].get("id") or "") or None
        return history_chat_id

    def make_session(c):
        rules = {name: Decision((remote._remote_tool_map[name][0].get("tools") or {}).get(remote._remote_tool_map[name][1], "confirm"))
                 for name in remote._remote_tool_map}
        return AgentSession(c, make_provider(c), build_server(c), policy=ToolPolicy(rules={**load_rules(), **rules}),
                            remote_tools=list(remote._remote_tool_specs.values()), remote_caller=remote._call_remote_tool,
                            server_aliases=remote._server_aliases())

    try:
        session = make_session(cfg)
    except RuntimeError as exc:
        raise SystemExit(f"Error: {str(exc).rstrip('.')}. Set it with: mcptoai keys set {cfg.provider}")

    async def approver(tool, args) -> bool:
        # Onay yalnızca terminalden verilir; boru/betik ile çalışırken her istek reddedilir.
        print(f"\n  ⚠ {tool} {json.dumps(args, ensure_ascii=False)[:300]}")
        if not sys.stdin.isatty():
            print("  denied (no terminal)")
            return False
        answer = await asyncio.to_thread(input, "  Allow once? [y/N] ")
        return answer.strip().lower() in {"y", "yes", "e", "evet"}

    async def emit(e) -> None:
        t = e.get("type")
        if t == "text":
            print(e.get("text", ""), flush=True)
        elif t == "tool_request":
            print(f"  → {e.get('name')}", flush=True)
        elif t == "tool_result":
            print(f"  ← {e.get('name')}{' (error)' if e.get('is_error') else ''}", flush=True)
        elif t == "error":
            print(f"  ! {e.get('message')}", flush=True)

    print(f"MCPtoAI chat · {cfg.provider} / {cfg.model} · /help for commands")
    while True:
        try:
            text = (await asyncio.to_thread(input, "\nyou › ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not text:
            continue
        if text.startswith("/"):
            cmd, _, arg = text[1:].partition(" ")
            arg = arg.strip()
            if cmd in {"exit", "quit"}:
                return
            if cmd == "help":
                print("/models  /model [id]  /provider [id] [model]  /new  /jobs  /exit")
            elif cmd == "models":
                try:
                    listed = await make_provider(cfg).list_models()
                    if not listed:
                        print(f"No models returned by {cfg.provider}.")
                    else:
                        print(f"Models for {cfg.provider}:")
                        for i, item in enumerate(listed, 1):
                            mid = item.get("id") if isinstance(item, dict) else str(item)
                            mark = "*" if mid == cfg.model else " "
                            print(f"  {mark} {i:>2}. {mid}")
                        print("Use /model <id> or just /model for interactive selection.")
                except Exception as exc:
                    print(f"  ! {exc}")
            elif cmd == "new":
                history.clear()
                history_chat_id = None
                session = make_session(cfg)
                print("New conversation.")
            elif cmd == "jobs":
                cmd_jobs(argparse.Namespace(action="list"))
            elif cmd in {"model", "provider"}:
                try:
                    providers = _chat_providers()
                    if cmd == "provider":
                        prov, _, mod = arg.partition(" ")
                        prov, mod = prov.strip(), mod.strip()
                        if not prov:
                            choices = list(providers.items())
                            print("Select a provider:")
                            for i, (pid, info) in enumerate(choices, 1):
                                mark = "*" if pid == cfg.provider else " "
                                print(f"  {mark} {i:>2}. {pid} — {info.get('name', pid)}")
                            answer = (await asyncio.to_thread(input, "provider › ")).strip()
                            if not answer:
                                continue
                            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                                prov = choices[int(answer)-1][0]
                            else:
                                prov = answer
                        if prov not in providers:
                            print(f"Unknown provider: {prov}")
                            continue
                    else:
                        prov, mod = cfg.provider, arg

                    if not mod:
                        probe_cfg = _cfg(provider=prov, model=(cfg.model if prov == cfg.provider else None))
                        listed = await make_provider(probe_cfg).list_models()
                        models = [m.get("id") if isinstance(m, dict) else str(m) for m in listed]
                        models = [m for m in models if m]
                        if not models:
                            print(f"No models returned by {prov}.")
                            continue
                        print(f"Select a model for {prov}:")
                        for i, mid in enumerate(models, 1):
                            mark = "*" if prov == cfg.provider and mid == cfg.model else " "
                            print(f"  {mark} {i:>2}. {mid}")
                        answer = (await asyncio.to_thread(input, "model › ")).strip()
                        if not answer:
                            continue
                        if answer.isdigit() and 1 <= int(answer) <= len(models):
                            mod = models[int(answer)-1]
                        else:
                            mod = answer

                    new_cfg = _cfg(provider=prov, model=mod)
                    session = make_session(new_cfg)  # conversation history is passed as context on the next turn
                    cfg = new_cfg
                    print(f"Switched to {cfg.provider} / {cfg.model}")
                    print("Conversation context preserved.")
                    if history_chat_id:
                        await history_action("cloud_chat_update",session_id=history_chat_id,provider=cfg.provider,model=cfg.model)
                except Exception as exc:
                    print(f"  ! {exc}")
            else:
                print("Unknown command. /help")
            continue
        chat_id = await ensure_history_chat()
        if chat_id:
            await history_action("cloud_chat_add_message",session_id=chat_id,role="user",content=text,model=cfg.model)
        try:
            reply = await session.run(text, approver, emit, context=list(history[-40:]))
        except KeyboardInterrupt:
            print("\n(stopped)")
            continue
        except Exception as exc:
            print(f"  ! {exc}")
            continue
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply or ""}]
        if chat_id:
            await history_action("cloud_chat_add_message",session_id=chat_id,role="assistant",content=reply or "",model=cfg.model)


def cmd_chat(a) -> None:
    cfg = _cfg(provider=a.provider, model=a.model)
    try:
        asyncio.run(_chat_loop(cfg.provider, cfg.model))
    except KeyboardInterrupt:
        print()


# --- servis --------------------------------------------------------------------

def cmd_service(a) -> None:
    from . import service
    if os.getenv("MCPTOAI_CONTAINER"):
        raise SystemExit("Running in a container: use Docker to run it in the background (docker run -d --restart unless-stopped …).")
    if a.action == "install":
        if not _paired():
            raise SystemExit("Pair this machine first: mcptoai login")
        for note in service.install():
            print("Note:", note)
        print(f"Service: {service.status_line()}")
    elif a.action == "uninstall":
        service.uninstall()
        print("Service removed.")
    elif a.action in {"start", "stop", "restart"}:
        r = service.systemctl(a.action, service.UNIT_NAME)
        print(r.stderr.strip() or f"Service: {service.status_line()}")
    elif a.action == "status":
        print(f"Service: {service.status_line()}")
    elif a.action == "logs":
        import subprocess
        subprocess.run(["journalctl", "--user", "-u", service.UNIT_NAME, "-n", str(a.lines), "--no-pager", *(["-f"] if a.follow else [])],
                       env=service._env())


def cmd_reset(a) -> None:
    """Bu cihazdaki tüm MCPtoAI verisini siler: servis, eşleşme, kasa ve ayarlar."""
    import shutil
    from . import service
    from .paths import config_dir
    from .secret_store import destroy_vault
    if not a.yes and not _confirm("Remove the service, unpair this machine and delete all local MCPtoAI data (keys, settings)?"):
        raise SystemExit("Cancelled.")
    try:
        service.uninstall()
    except Exception:
        pass
    try:  # cihazı hesaptan düşürmeyi dene; ağ/kasa hatası temizliği engellemez
        from .auth import disconnect_device
        asyncio.run(disconnect_device(_cfg()))
    except Exception:
        pass
    # Kasa içeriğine bakmadan silinir (bozuk kasa dahil). Başarısızsa identity.pub silinmez:
    # kimlik koruması devam etmeli.
    destroy_vault()
    shutil.rmtree(config_dir(), ignore_errors=True)
    print("Local MCPtoAI data removed.")


def cmd_run(_a) -> None:
    """Relay bağlantısını ön planda çalıştırır (systemd servisi bunu çağırır)."""
    import logging
    from .relay_client import run_relay_client
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run_relay_client(_cfg()))
    except KeyboardInterrupt:
        pass


# --- komut ağacı ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawDescriptionHelpFormatter
    p = argparse.ArgumentParser(
        prog="mcptoai",
        formatter_class=fmt,
        description="MCPtoAI Linux agent — securely connect this machine to AI from the web, your phone, or this terminal.",
        epilog="""Quick start:
  mcptoai login
  mcptoai keys set anthropic
  mcptoai models anthropic
  mcptoai use anthropic <model-id>
  mcptoai service install
  mcptoai doctor

Common tasks:
  mcptoai status                 Show the current configuration
  mcptoai update --check         Check PyPI for a newer CLI version
  mcptoai workspace show         Show filesystem access scope
  mcptoai mcp list               List connected MCP servers
  mcptoai shell status           Show terminal-command permission
  mcptoai jobs list              Show long-running jobs
  mcptoai chat                   Chat directly over SSH/terminal
  mcptoai connect                Connect in the foreground

Run `mcptoai <command> --help` for command-specific examples and safety notes.
Documentation: https://mcptoai.com/""",
    )
    p.add_argument("--version", action="version", version=f"mcptoai {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    def leaf(name, help_text, description, epilog=None):
        return sub.add_parser(name, help=help_text, description=description, epilog=epilog, formatter_class=fmt)

    leaf("login", "Pair this machine with your MCPtoAI account",
         "Pair this Linux machine with your MCPtoAI account using the browser/device login flow.",
         """Example:
  mcptoai login

After pairing:
  mcptoai keys set <provider>
  mcptoai service install""").set_defaults(fn=cmd_login)

    leaf("logout", "Disconnect this machine",
         "Disconnect this machine from the MCPtoAI account. Local provider keys and settings are not deleted.",
         """Example:
  mcptoai logout

To remove all local MCPtoAI data as well, use `mcptoai reset`.""").set_defaults(fn=cmd_logout)

    leaf("status", "Show pairing, model, vault and service state",
         "Show the current MCPtoAI version, pairing state, provider/model, vault, shell permission, service and jobs.",
         "Example:\n  mcptoai status").set_defaults(fn=cmd_status)

    leaf("doctor", "Check the installation",
         "Run installation and configuration checks. Exits with status 1 when an important check fails.",
         """Example:
  mcptoai doctor

Useful after installation, changing provider keys, or troubleshooting the background service.""").set_defaults(fn=cmd_doctor)

    w = leaf("workspace", "Show or choose the filesystem workspace exposed to AI tools",
             "Control which filesystem area MCPtoAI file tools may access.",
             """Examples:
  mcptoai workspace show
  mcptoai workspace set ~/projects/my-app
  mcptoai workspace reset

Without a custom workspace, MCPtoAI uses the default Desktop, Documents and Downloads folders.""")
    ws = w.add_subparsers(dest="action", metavar="<action>")
    ws.add_parser("show", help="Show the current workspace", description="Show the current filesystem workspace.", formatter_class=fmt)
    wset = ws.add_parser("set", help="Choose one directory as the workspace", description="Restrict file tools to one existing directory.", formatter_class=fmt)
    wset.add_argument("path", help="Existing directory to expose to MCPtoAI file tools")
    ws.add_parser("reset", help="Return to Desktop/Documents/Downloads defaults", description="Return to the default filesystem workspace.", formatter_class=fmt)
    w.set_defaults(fn=cmd_workspace, action="show")

    k = leaf("keys", "Manage AI provider API keys (stored in the vault)",
             "Add, list or remove AI provider API keys. Keys are entered through a hidden prompt and stored in the local vault.",
             """Examples:
  mcptoai keys list
  mcptoai keys set openai
  mcptoai keys set anthropic
  mcptoai keys remove openai

Security:
  API keys are not accepted as command-line arguments. This avoids exposing them through shell history or process listings.""")
    ks = k.add_subparsers(dest="action", required=True, metavar="<action>")
    ks.add_parser("list", help="Show which provider keys are configured", formatter_class=fmt)
    for name, text in (("set", "Securely save a provider API key"), ("remove", "Remove a provider API key")):
        x=ks.add_parser(name, help=text, formatter_class=fmt)
        x.add_argument("provider", help="Provider id, for example openai or anthropic")
    k.set_defaults(fn=cmd_keys)

    m = leaf("models", "List models of a provider",
             "List models available from an AI provider. If provider is omitted, the current provider is used.",
             """Examples:
  mcptoai models
  mcptoai models openai
  mcptoai models anthropic""")
    m.add_argument("provider", nargs="?", help="Provider id; defaults to the currently selected provider")
    m.set_defaults(fn=cmd_models)

    u = leaf("use", "Set the default provider and model",
             "Choose the provider and model used by web, relay and terminal chat sessions on this machine.",
             """Examples:
  mcptoai models anthropic
  mcptoai use anthropic <model-id>

Changing the default restarts the background service if it is currently running.""")
    u.add_argument("provider", help="Provider id")
    u.add_argument("model", nargs="?", help="Model id; required unless a model is already selected for this provider")
    u.set_defaults(fn=cmd_use)

    mc = leaf("mcp", "Manage MCP servers",
              "Connect local stdio MCP servers or remote HTTPS Streamable HTTP MCP servers.",
              """Examples:
  mcptoai mcp list
  mcptoai mcp add-http Cloudflare https://mcp.cloudflare.com/mcp
  mcptoai mcp add-stdio my-tools /path/to/server --arg value
  mcptoai mcp remove mcp-0123456789ab

Security:
  Remote MCP URLs must use HTTPS and may require OAuth in your browser.
  Local stdio MCP servers execute code on this machine with your user permissions, so adding one requires local confirmation.""")
    ms = mc.add_subparsers(dest="action", required=True, metavar="<action>")
    ms.add_parser("list", help="List configured MCP servers", formatter_class=fmt)
    h = ms.add_parser("add-http", help="Add a remote HTTPS Streamable HTTP MCP server", formatter_class=fmt,
                      description="Add a remote HTTPS Streamable HTTP MCP server and run tool discovery/OAuth setup.")
    h.add_argument("name", help="Friendly name, used for @mentions and tool routing")
    h.add_argument("url", help="HTTPS MCP endpoint URL")
    st = ms.add_parser("add-stdio", help="Add a local MCP server (runs code on this machine)", formatter_class=fmt,
                       description="Add a local stdio MCP server. The command runs with your Linux user permissions.")
    st.add_argument("name", help="Friendly server name")
    st.add_argument("command", nargs=argparse.REMAINDER, help="Executable followed by its arguments")
    rm = ms.add_parser("remove", help="Remove an MCP server", formatter_class=fmt)
    rm.add_argument("server_id", help="Server id shown by `mcptoai mcp list`")
    mc.set_defaults(fn=cmd_mcp)

    sh = leaf("shell", "Allow or block terminal commands and jobs (local permission)",
              "Control whether AI sessions may request terminal commands and long-running jobs on this machine.",
              """Examples:
  mcptoai shell status
  mcptoai shell on
  mcptoai shell off

Security:
  Terminal access is off by default and can only be enabled locally.
  Remote clients cannot turn it on. Sensitive command execution still requires explicit approval.""")
    sh.add_argument("action", choices=["on", "off", "status"], nargs="?", default="status", help="Permission action (default: status)")
    sh.add_argument("-y", "--yes", action="store_true", help="Skip the local enable/disable confirmation prompt")
    sh.set_defaults(fn=cmd_shell)

    hst = leaf("history", "Choose where conversation history is stored",
               "Choose whether conversation history is stored only on this Linux device or in MCPtoAI Cloud.",
               """Examples:
  mcptoai history status
  mcptoai history local
  mcptoai history cloud""")
    hst.add_argument("action", choices=["local", "cloud", "status"], nargs="?", default="status", help="History storage mode (default: status)")
    hst.set_defaults(fn=cmd_history)

    j = leaf("jobs", "Long-running background jobs",
             "Inspect and stop long-running jobs started through MCPtoAI.",
             """Examples:
  mcptoai jobs list
  mcptoai jobs show job-1234abcd
  mcptoai jobs logs job-1234abcd
  mcptoai jobs logs job-1234abcd --follow
  mcptoai jobs stop job-1234abcd

Jobs continue independently of a single chat/model session and their state can be surfaced to later sessions.""")
    js = j.add_subparsers(dest="action", metavar="<action>")
    js.add_parser("list", help="List jobs", formatter_class=fmt)
    for name, text in (("show", "Show job status and recent output"), ("logs", "Show job output")):
        x = js.add_parser(name, help=text, formatter_class=fmt)
        x.add_argument("job_id", help="Job id")
        x.add_argument("-n", "--lines", type=int, default=40, help="Number of output lines (default: 40)")

        if name == "logs":
            x.add_argument("-f", "--follow", action="store_true", help="Follow output until the job stops")
    stop = js.add_parser("stop", help="Stop a running job", formatter_class=fmt)
    stop.add_argument("job_id", help="Job id")
    stop.add_argument("-y", "--yes", action="store_true", help="Skip the local confirmation prompt")
    j.set_defaults(fn=cmd_jobs, action="list")

    c = leaf("chat", "Chat in this terminal",
             "Start an interactive MCPtoAI chat in this terminal. Useful over SSH without opening the web app.",
             """Examples:
  mcptoai chat
  mcptoai chat --provider openai --model <model-id>

In-chat commands:
  /help
  /model <model-id>
  /provider <provider> <model-id>
  /new
  /jobs
  /exit

Tool requests that require confirmation are approved interactively in the terminal.""")
    c.add_argument("--provider", help="Override the configured provider for this terminal chat")
    c.add_argument("--model", help="Override the configured model for this terminal chat")
    c.set_defaults(fn=cmd_chat)

    sv = leaf("service", "Background connection (systemd user service)",
              "Install and manage MCPtoAI as a systemd user service so this machine remains reachable when the terminal closes.",
              """Examples:
  mcptoai service install
  mcptoai service status
  mcptoai service restart
  mcptoai service logs
  mcptoai service logs --follow
  mcptoai service uninstall

`service install` requires the machine to be paired first. In Docker, container restart policy replaces this systemd service.""")
    sv.add_argument("action", choices=["install", "uninstall", "start", "stop", "restart", "status", "logs"], help="Service action")
    sv.add_argument("-n", "--lines", type=int, default=50, help="Number of journal lines for `logs` (default: 50)")
    sv.add_argument("-f", "--follow", action="store_true", help="Follow service logs")
    sv.set_defaults(fn=cmd_service)

    up = leaf("update", "Check for or install MCPtoAI CLI updates",
              "Check PyPI for a newer MCPtoAI CLI release or update this installation in place.",
              """Examples:
  mcptoai update --check
  mcptoai update

Behavior:
  pipx installations use `pipx upgrade mcptoai`.
  pip/venv installations use the current Python interpreter with `pip install --upgrade mcptoai`.
  If the MCPtoAI background service is running, it is restarted after a successful update.
  Docker installations should be updated by pulling a newer image instead.""")
    up.add_argument("--check", action="store_true", help="Only check whether a newer version is available; make no changes")
    up.set_defaults(fn=cmd_update)

    rs = leaf("reset", "Remove the service, unpair and delete all local data",
              "Remove the MCPtoAI service, unpair this machine and delete the local MCPtoAI vault/settings.",
              """Example:
  mcptoai reset

Warning:
  This deletes locally stored provider credentials, MCP configuration and MCPtoAI settings on this machine.
  It does not delete your MCPtoAI account or cloud-side account data.""")
    rs.add_argument("-y", "--yes", action="store_true", help="Skip the destructive-action confirmation prompt")
    rs.set_defaults(fn=cmd_reset)

    leaf("connect", "Connect this machine to MCPtoAI in the foreground",
         "Connect this machine to the MCPtoAI relay in the foreground. Normally `mcptoai service install` keeps this connection running for you.",
         """Example:
  mcptoai connect

Useful for a quick connection test, debugging, or container entrypoints. Press Ctrl-C to disconnect.""").set_defaults(fn=cmd_run)
    return p

def main(argv: list[str] | None = None) -> None:
    import os
    args = build_parser().parse_args(argv)
    if args.cmd == "jobs" and getattr(args, "action", None) is None:
        args.action = "list"
    try:
        args.fn(args)
    except KeyboardInterrupt:
        print()
        raise SystemExit(130)
    except SystemExit:
        raise
    except Exception as exc:
        # Kullanıcıya Python yığını değil kısa bir mesaj; MCPTOAI_DEBUG=1 ile tam yığın.
        if os.getenv("MCPTOAI_DEBUG"):
            raise
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
