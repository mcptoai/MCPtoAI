"""FastMCP 4 / MCP SDK 2 stdio alt süreç yaşam döngüsü testleri (Issue #33).

AnyIO cancel scope'ları açıldıkları görevde kapatılmalıdır. Bu testler gerçek bir
stdio MCP sunucusu başlatır ve açılış/kapanışın farklı görevlerden tetiklendiği,
eşzamanlı çağrıların ve kapanışsız program sonunun hatasız olduğunu doğrular.
"""
import asyncio
import os
import signal
import sys
import time

import pytest

from mcptoai_agent.relay_client import RelayClient

SERVER = '''
import os, sys
from fastmcp import FastMCP
with open(sys.argv[1], "a") as f:
    f.write(f"{os.getpid()}\\n")
m = FastMCP("smoke")
@m.tool
def ping() -> str:
    return "pong"
if __name__ == "__main__":
    m.run(transport="stdio")
'''


def _client():
    client = object.__new__(RelayClient)
    client._stdio_runtimes = {}
    return client


def _server(tmp_path, sid='smoke'):
    script = tmp_path / 'stdio_server.py'
    script.write_text(SERVER)
    pids = tmp_path / f'{sid}.pids'
    return {'id': sid, 'command': sys.executable, 'args': [str(script), str(pids)]}, pids


def _pids(path):
    return [int(x) for x in path.read_text().split()] if path.exists() else []


def _alive(pid):
    """Süreç çalışıyor mu? Linux'ta toplanmamış zombi süreç bitmiş sayılır."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = f'/proc/{pid}/stat'
    if os.path.exists(stat):
        try:
            with open(stat) as f:
                return f.read().rsplit(')', 1)[-1].split()[0] != 'Z'
        except OSError:
            return False
    return True


def _gone(pid, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def _run(coro_fn):
    """Olay döngüsüne düşen her hatayı (ör. async generator kapanışı) toplar."""
    errors = []

    async def main():
        asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: errors.append(ctx))
        return await coro_fn()

    result = asyncio.run(main())
    return result, errors


def test_stdio_child_exits_cleanly(tmp_path):
    server, pids = _server(tmp_path)

    async def check():
        client = _client()
        session = await asyncio.wait_for(client._stdio_session(server), timeout=60)
        tools = await session.list_tools()
        assert 'ping' in [t.name for t in tools.tools]
        await asyncio.wait_for(client._close_stdio('smoke'), timeout=15)
        assert not client._stdio_runtimes

    _, errors = _run(check)
    assert errors == []
    assert all(_gone(pid) for pid in _pids(pids))


def test_open_and_close_from_different_tasks(tmp_path):
    server, pids = _server(tmp_path)

    async def check():
        client = _client()
        session = await asyncio.create_task(client._stdio_session(server))
        result = await asyncio.create_task(session.call_tool('ping', {}))
        assert not result.is_error
        await asyncio.create_task(client._close_stdio('smoke'))
        assert not client._stdio_runtimes

    _, errors = _run(check)
    assert errors == []
    assert len(_pids(pids)) == 1
    assert _gone(_pids(pids)[0])


def test_concurrent_sessions_start_a_single_child(tmp_path):
    server, pids = _server(tmp_path)

    async def check():
        client = _client()
        sessions = await asyncio.gather(*[client._stdio_session(server) for _ in range(5)])
        assert all(s is sessions[0] for s in sessions)
        results = await asyncio.gather(*[sessions[0].call_tool('ping', {}) for _ in range(5)])
        assert not any(r.is_error for r in results)
        await client._close_stdio()

    _, errors = _run(check)
    assert errors == []
    assert len(_pids(pids)) == 1


def test_program_exit_without_explicit_close_is_clean(tmp_path):
    server, pids = _server(tmp_path)

    async def check():
        client = _client()
        await asyncio.create_task(client._stdio_session(server))
        # Kapatmadan dönülür: asyncio.run sahip görevi iptal eder; kapanış o görevde olmalı.

    _, errors = _run(check)
    assert errors == [], errors
    assert all(_gone(pid) for pid in _pids(pids))


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGKILL is POSIX-only')
def test_dead_child_fails_fast_and_restarts_on_next_use(tmp_path):
    """Ölen alt süreç: çağrı asılı kalmadan hata verir; _call_remote_tool'daki gibi
    kapatılınca bir sonraki kullanım temiz bir alt süreç başlatır."""
    server, pids = _server(tmp_path)

    async def check():
        client = _client()
        session = await client._stdio_session(server)
        first = _pids(pids)[0]
        os.kill(first, signal.SIGKILL)
        assert _gone(first)
        started = time.monotonic()
        with pytest.raises(Exception) as info:
            await asyncio.wait_for(session.call_tool('ping', {}), timeout=20)
        assert not isinstance(info.value, asyncio.TimeoutError), 'call to a dead stdio server hung'
        assert time.monotonic() - started < 15
        await client._close_stdio('smoke')
        session = await asyncio.wait_for(client._stdio_session(server), timeout=60)
        result = await session.call_tool('ping', {})
        assert not result.is_error
        await client._close_stdio()
        return first

    first, errors = _run(check)
    pid_list = _pids(pids)
    assert len(pid_list) == 2 and pid_list[0] == first
    assert _gone(pid_list[1])
