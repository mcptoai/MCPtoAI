"""Komut araçlarının iptal ve olay döngüsü davranışı.

Agent araçları her tur için `async with Client(server)` içinde çağırır; Durdur bu tur
görevini iptal eder. Testler aynı yapıyı kurar. Platformdan bağımsız olması için
alt süreçler Python yardımcı betiğiyle başlatılır.
"""
import asyncio
import dataclasses
import inspect
import os
import subprocess
import sys
import textwrap
import time

import pytest
from fastmcp import Client

from mcptoai_linux.config import settings
from mcptoai_linux.tools.host_tools import build_server

PY = sys.executable

HELPER = textwrap.dedent('''
    import os, subprocess, sys, time
    d = sys.argv[1]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    open(os.path.join(d, "pid"), "w").write(str(os.getpid()))
    open(os.path.join(d, "child"), "w").write(str(child.pid))
    time.sleep(float(sys.argv[2]))
    open(os.path.join(d, "done"), "w").write("1")
''')


def _server():
    return build_server(dataclasses.replace(settings, enable_shell=True))


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def _q(path) -> str:
    return f'"{path}"'


async def _wait_for_file(path, timeout=10.0):
    end = time.monotonic() + timeout
    while not os.path.exists(path):
        assert time.monotonic() < end, f"{path} oluşmadı"
        await asyncio.sleep(0.05)


def _start_turn(server, command, timeout=60):
    async def turn():
        async with Client(server) as client:
            return await client.call_tool("run_command", {"command": command, "timeout": timeout}, raise_on_error=False)
    return asyncio.create_task(turn())


def test_tum_araclar_olay_dongusunu_tikamaz():
    async def check():
        tools = await _server().get_tools()
        sync = [name for name, tool in tools.items() if not inspect.iscoroutinefunction(tool.fn)]
        assert sync == [], f"olay döngüsünde çalışan senkron araçlar: {sync}"
    asyncio.run(check())


def test_komut_suresince_agent_yanit_verir(tmp_path):
    async def check():
        script = tmp_path / "h.py"; script.write_text(HELPER)
        task = _start_turn(_server(), f"{_q(PY)} {_q(script)} {_q(tmp_path)} 5")
        await _wait_for_file(tmp_path / "pid")
        t0 = time.monotonic(); await asyncio.sleep(0.5)
        assert time.monotonic() - t0 < 1.5, "olay döngüsü komut sırasında tıkandı"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(check())


def test_durdur_komutu_ve_alt_sureclerini_oldurur(tmp_path):
    async def check():
        script = tmp_path / "h.py"; script.write_text(HELPER)
        task = _start_turn(_server(), f"{_q(PY)} {_q(script)} {_q(tmp_path)} 4")
        await _wait_for_file(tmp_path / "child")
        pid = int((tmp_path / "pid").read_text()); child = int((tmp_path / "child").read_text())
        assert _alive(pid) and _alive(child)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        end = time.monotonic() + 3
        while (_alive(pid) or _alive(child)) and time.monotonic() < end:
            await asyncio.sleep(0.1)
        assert not _alive(pid), "komut Durdur'dan sonra çalışmaya devam ediyor"
        assert not _alive(child), "komutun alt süreci Durdur'dan sonra çalışmaya devam ediyor"
        await asyncio.sleep(5)
        assert not (tmp_path / "done").exists(), "komut Durdur'a rağmen tamamlandı"
    asyncio.run(check())


def test_zaman_asimi_komut_agacini_oldurur(tmp_path):
    async def check():
        script = tmp_path / "h.py"; script.write_text(HELPER)
        t0 = time.monotonic()
        result = await _start_turn(_server(), f"{_q(PY)} {_q(script)} {_q(tmp_path)} 30", timeout=2)
        text = " ".join(getattr(c, "text", "") for c in result.content)
        assert "zaman aşımı" in text
        assert time.monotonic() - t0 < 10
        child = int((tmp_path / "child").read_text())
        end = time.monotonic() + 3
        while _alive(child) and time.monotonic() < end:
            await asyncio.sleep(0.1)
        assert not _alive(child), "zaman aşımından sonra alt süreç çalışıyor"
    asyncio.run(check())


def test_stdin_devralinmaz_ve_git_soru_sormaz():
    async def check():
        server = _server()
        async with Client(server) as client:
            t0 = time.monotonic()
            r = await client.call_tool("run_command", {"command": f'{_q(PY)} -c "import sys;print(len(sys.stdin.read()))"', "timeout": 20}, raise_on_error=False)
            assert " ".join(getattr(c, "text", "") for c in r.content).strip() == "0"
            assert time.monotonic() - t0 < 10, "komut girdi beklerken takıldı"
            r = await client.call_tool("run_command", {"command": f"{_q(PY)} -c \"import os;print(os.environ.get('GIT_TERMINAL_PROMPT'))\"", "timeout": 20}, raise_on_error=False)
            assert " ".join(getattr(c, "text", "") for c in r.content).strip() == "0"
    asyncio.run(check())
