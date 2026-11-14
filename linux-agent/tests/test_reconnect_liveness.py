"""Ping/pong liveness and reconnect task ownership; no extra watchdog process."""
import asyncio
import websockets.exceptions
from contextlib import asynccontextmanager
from types import SimpleNamespace

from mcptoai_core.relay_transport import open_relay
from mcptoai_linux import relay_client as relay


def test_websocket_ping_pong_timeout_is_enabled():
    captured={}
    def connect(url,**kwargs):
        captured.update(kwargs)
        return object()
    open_relay(connect,'wss://example.invalid/ws',{'Authorization':'Bearer fake'})
    assert captured['ping_interval']==20
    assert captured['ping_timeout']==20
    assert captured['max_size']==2**20


def test_silent_ping_timeout_reconnects_without_duplicate_background_tasks(monkeypatch):
    async def check():
        client=object.__new__(relay.RelayClient)
        client.cfg=SimpleNamespace(relay_url='wss://example.invalid/ws',server_url='https://example.invalid',reconnect_max_seconds=2)
        client.ws=None
        client._answer_sync_task=None
        client._job_watch_task=None
        client._ipc_server=object()  # no real socket, filesystem, or local profile
        opened=[]
        async def get_token(_): return 'fake'
        async def register(_cfg,_token): return 'device'
        async def noop(*args,**kwargs): pass
        async def background():
            await asyncio.Event().wait()
        async def receive(_ws,_handler):
            opened.append('receive')
            if len(opened)==1:
                raise TimeoutError('simulated missing pong')
            asyncio.current_task().cancel()
            await asyncio.sleep(0)
        @asynccontextmanager
        async def fake_open(_connect,_url,_headers):
            yield object()
        monkeypatch.setattr(relay,'get_access_token',get_token)
        monkeypatch.setattr(relay,'register_device',register)
        monkeypatch.setattr(relay,'device_ws_proof',lambda _: {})
        monkeypatch.setattr(relay,'_open_relay',fake_open)
        monkeypatch.setattr(relay,'_receive_messages',receive)
        monkeypatch.setattr(relay,'answer_sync_loop',lambda *args:background())
        monkeypatch.setattr(relay,'_reconnect_delay',lambda *args:(0,1))
        client._start_local_ipc=noop
        client._send_hello=noop
        client._flush_outbox=noop
        client._send_jobs_snapshot=noop
        client._send_mcp_state=noop
        client._watch_jobs=background
        client._durable_events=object()
        created=[]
        original=asyncio.create_task
        def track(coro):
            task=original(coro)
            created.append(task)
            return task
        monkeypatch.setattr(relay.asyncio,'create_task',track)
        runner=asyncio.create_task(client.run_forever())
        try:
            await asyncio.wait_for(runner,timeout=2)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            runner.cancel()
            await asyncio.gather(runner,return_exceptions=True)
        assert opened==['receive','receive']
        assert sum(t.get_coro().__name__=='background' for t in created)==2
        assert client._answer_sync_task is not None and not client._answer_sync_task.done()
        assert client._job_watch_task is not None and not client._job_watch_task.done()
        for task in created: task.cancel()
        await asyncio.gather(*created,return_exceptions=True)
    asyncio.run(check())
