"""Yerel "Terminal komutları" izni: varsayılan kapalı, yalnızca cihazdan açılır."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "mcptoai_agent"


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "MCPTOAI_ENABLE_SHELL"}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), APPDATA=str(tmp_path / "AppData"))
    return env


def _run(tmp_path, *args):
    out = subprocess.run([sys.executable, "-W", "ignore", "-m", "mcptoai_agent", *args], cwd=ROOT,
                         env=_env(tmp_path), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def _shell_tools(tmp_path):
    code = ("import asyncio;from fastmcp import Client;from mcptoai_agent.config import Settings;"
            "from mcptoai_agent.tools import build_server\n"
            "async def m():\n async with Client(build_server(Settings())) as c:\n"
            "  print(sorted(t.name for t in await c.list_tools() if t.name.startswith(('run_','job_'))))\n"
            "asyncio.run(m())")
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=ROOT, env=_env(tmp_path),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    return out.stdout.strip().splitlines()[-1]


def test_varsayilan_kapali_ve_araclar_yok(tmp_path):
    assert _run(tmp_path, "shell-access", "status")["enabled"] is False
    assert _shell_tools(tmp_path) == "[]"


def test_yerel_komutla_acilir_kapanir_ve_araclar_gelir(tmp_path):
    assert _run(tmp_path, "shell-access", "on")["enabled"] is True
    tools = _shell_tools(tmp_path)
    for name in ("run_command", "run_in_project", "job_start", "job_status", "job_list", "job_stop"):
        assert name in tools
    assert _run(tmp_path, "shell-access", "off")["enabled"] is False
    assert _shell_tools(tmp_path) == "[]"


@pytest.mark.skipif(os.name == "nt", reason="POSIX dosya izni")
def test_izin_dosyasi_yalnizca_sahibi_okuyabilir(tmp_path):
    _run(tmp_path, "shell-access", "on")
    f = next(tmp_path.rglob("local-permissions.json"))
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_bozuk_izin_dosyasi_kapali_sayilir(tmp_path):
    _run(tmp_path, "shell-access", "on")
    f = next(tmp_path.rglob("local-permissions.json"))
    f.write_text('{"shell": "true"}')  # yalnızca gerçek true açar
    assert _run(tmp_path, "shell-access", "status")["enabled"] is False
    f.write_text("bozuk{")
    assert _run(tmp_path, "shell-access", "status")["enabled"] is False


def test_izin_dosyasina_yalnizca_yerel_kod_yazabilir():
    """Relay/web yolundaki hiçbir modül yerel izin dosyasına erişmemeli."""
    allowed = {"config.py", "__main__.py"}
    offenders = []
    for path in PKG.rglob("*.py"):
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if any(k in text for k in ("save_local_permission", "LOCAL_PERMISSIONS_FILE", "local-permissions")):
            offenders.append(str(path.relative_to(PKG)))
    assert offenders == [], f"yerel izin dosyasına erişen modüller: {offenders}"
    main = (PKG / "__main__.py").read_text(encoding="utf-8")
    # __main__ içinde save_local_permission yalnızca shell-access komutunda kullanılır.
    assert main.count("save_local_permission(") == 1
