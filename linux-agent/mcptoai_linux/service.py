"""systemd kullanıcı servisi: relay bağlantısını arka planda çalıştırır (asla root değil)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "mcptoai.service"


def unit_path() -> Path:
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user" / UNIT_NAME


def _env() -> dict:
    # SSH ya da cron gibi oturumsuz ortamlarda systemctl --user için gereken değişkenler.
    env = dict(os.environ)
    run_dir = f"/run/user/{os.getuid()}"
    env.setdefault("XDG_RUNTIME_DIR", run_dir)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={run_dir}/bus")
    return env


def systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], env=_env(), capture_output=True, text=True, check=check)


def executable() -> str:
    """Servisin çalıştıracağı mcptoai yolu (pipx: ~/.local/bin/mcptoai)."""
    found = shutil.which("mcptoai")
    return str(Path(found).resolve()) if found else str(Path(sys.argv[0]).resolve())


def unit_text(exe: str) -> str:
    return f"""[Unit]
Description=MCPtoAI Linux agent (relay connection)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exe} connect
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=yes

[Install]
WantedBy=default.target
"""


def linger_enabled() -> bool:
    out = subprocess.run(["loginctl", "show-user", str(os.getuid()), "-p", "Linger"], capture_output=True, text=True)
    return out.stdout.strip() == "Linger=yes"


def install() -> list[str]:
    if os.geteuid() == 0:
        raise SystemExit("Refusing to install the service as root. Run as the user who owns the device.")
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text(executable()), encoding="utf-8")
    notes = []
    for args in (("daemon-reload",), ("enable", "--now", UNIT_NAME)):
        r = systemctl(*args)
        if r.returncode != 0:
            raise SystemExit(f"systemctl --user {' '.join(args)} failed: {r.stderr.strip()}")
    if not linger_enabled():
        notes.append("Linger is off: the service stops when you log out. Enable start-at-boot with: sudo loginctl enable-linger " + os.getenv("USER", ""))
    return notes


def uninstall() -> None:
    systemctl("disable", "--now", UNIT_NAME)
    unit_path().unlink(missing_ok=True)
    systemctl("daemon-reload")


def status_line() -> str:
    if not unit_path().exists():
        return "not installed  (mcptoai service install)"
    state = systemctl("is-active", UNIT_NAME).stdout.strip() or "unknown"
    enabled = systemctl("is-enabled", UNIT_NAME).stdout.strip() or "unknown"
    return f"{state} ({enabled})"


def is_active() -> bool:
    return unit_path().exists() and systemctl("is-active", UNIT_NAME).stdout.strip() == "active"
