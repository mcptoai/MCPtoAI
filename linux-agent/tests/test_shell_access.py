"""Linux shell capability: default-on, with a local-only kill switch."""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "mcptoai_linux"


def _env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in {"MCPTOAI_ENABLE_SHELL", "XDG_CONFIG_HOME"}}
    env.update(HOME=str(tmp_path))
    return env


def _cli(tmp_path, *args, stdin=None):
    return subprocess.run([sys.executable, "-W", "ignore", "-m", "mcptoai_linux", *args], cwd=ROOT, env=_env(tmp_path),
                          capture_output=True, text=True, timeout=60, input=stdin)


def _shell_tools(tmp_path):
    code = ("import asyncio;from fastmcp import Client;from mcptoai_linux.config import Settings;"
            "from mcptoai_linux.tools import build_server\n"
            "async def m():\n async with Client(build_server(Settings())) as c:\n"
            "  print(sorted(t.name for t in await c.list_tools() if t.name.startswith(('run_','job_','service_','docker_'))))\n"
            "asyncio.run(m())")
    out = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=ROOT, env=_env(tmp_path), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    return out.stdout.strip().splitlines()[-1]


def test_varsayilan_acik_ve_araclar_mevcut(tmp_path):
    assert "on" in _cli(tmp_path, "shell").stdout
    tools = _shell_tools(tmp_path)
    for name in ("run_command", "run_in_project", "service_control", "docker_control",
                 "job_start", "job_status", "job_list", "job_stop"):
        assert name in tools


def test_terminal_yokken_kill_switch_yeniden_acilamaz(tmp_path):
    assert "off" in _cli(tmp_path, "shell", "off").stdout
    assert _shell_tools(tmp_path) == "['docker_status', 'service_status']"
    r = _cli(tmp_path, "shell", "on", stdin="y\n")  # pipe is not an interactive terminal
    assert r.returncode != 0 and "Cancelled" in (r.stderr + r.stdout)
    assert _shell_tools(tmp_path) == "['docker_status', 'service_status']"


def test_yerel_komutla_acilir_kapanir_ve_araclar_gelir(tmp_path):
    assert "on" in _cli(tmp_path, "shell", "on", "--yes").stdout
    tools = _shell_tools(tmp_path)
    for name in ("run_command", "run_in_project", "service_control", "docker_control", "job_start", "job_status", "job_list", "job_stop"):
        assert name in tools
    assert "off" in _cli(tmp_path, "shell", "off").stdout
    assert _shell_tools(tmp_path) == "['docker_status', 'service_status']"


def test_izin_dosyasi_yalnizca_sahibi_okuyabilir(tmp_path):
    _cli(tmp_path, "shell", "on", "--yes")
    f = next(tmp_path.rglob("local-permissions.json"))
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_izin_dosyasina_yalnizca_yerel_kod_yazabilir():
    """Relay/web yolundaki hiçbir modül yerel izin dosyasına erişmemeli."""
    allowed = {"config.py", "cli.py"}
    offenders = [str(p.relative_to(PKG)) for p in PKG.rglob("*.py") if p.name not in allowed
                 and any(k in p.read_text(encoding="utf-8") for k in ("save_local_permission", "LOCAL_PERMISSIONS_FILE", "local-permissions"))]
    assert offenders == [], f"yerel izin dosyasına erişen modüller: {offenders}"
    assert (PKG / "cli.py").read_text(encoding="utf-8").count("save_local_permission(") == 1
