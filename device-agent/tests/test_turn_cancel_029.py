"""Durdur (turn_cancel): çalışan turun iptali, onay ve gerçek alt süreç davranışı."""
import asyncio
import os
import time
import uuid
from dataclasses import replace

import pytest

from mcptoai_agent.activity_store import ActivityStore
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import Settings, settings
from mcptoai_agent.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_agent.relay_client import RelayClient
from mcptoai_agent.reliability import MessageReceiptStore
from mcptoai_agent.tools import build_server


def _client(tmp_path):
    client = RelayClient(Settings(provider="ollama", model="test-model"), receipt_store=MessageReceiptStore(tmp_path / "r.json"))
    client.sent = []

    async def send_event(sid, event, turn_id=None):
        client.sent.append(event)

    client._send_event = send_event
    return client


def _types(client):
    return [(e.get("type"), e.get("status")) for e in client.sent]


def test_stop_while_waiting_for_approval(tmp_path, monkeypatch):
    client = _client(tmp_path)
    started = asyncio.Event()

    async def fake_run(self, text, approver, emit, **kw):
        started.set()
        await approver("write_file", {"path": "x"})

    monkeypatch.setattr(AgentSession, "run", fake_run)
    mid = str(uuid.uuid4())

    async def scenario():
        task = asyncio.create_task(client._run_message({"type": "message", "message_id": mid, "session_id": "chat-1", "message": "hi"}))
        await started.wait(); await asyncio.sleep(0.05)
        await client._cancel_turn({"session_id": "chat-1"})
        await asyncio.wait_for(task, 5)  # kullanıcı iptali hata olarak yükselmez

    asyncio.run(scenario())
    types = _types(client)
    assert ("approval_resolved", "cancelled") in types
    assert ("cancelled", "cancelled") in types
    assert not any(t == "error" for t, _ in types)
    assert client._turn_state["chat-1"]["active"] is False
    assert client._turn_tasks == {} and client._cancel_requested == set()


def test_stop_without_running_turn_reports_not_running(tmp_path):
    client = _client(tmp_path)
    asyncio.run(client._cancel_turn({"session_id": "chat-1"}))
    assert _types(client) == [("cancelled", "not_running")]


def test_stop_for_another_turn_does_not_cancel_running_turn(tmp_path, monkeypatch):
    client = _client(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(self, text, approver, emit, **kw):
        started.set()
        await release.wait()

    monkeypatch.setattr(AgentSession, "run", fake_run)

    async def scenario():
        task = asyncio.create_task(client._run_message({"type": "message", "message_id": str(uuid.uuid4()), "session_id": "chat-1", "message": "hi"}))
        await started.wait()
        await client._cancel_turn({"session_id": "chat-1", "turn_id": "some-other-turn"})
        assert not task.done()
        await client._cancel_turn({"session_id": "chat-1"})
        await client._cancel_turn({"session_id": "chat-1"})  # ikinci basış zararsız
        await asyncio.wait_for(task, 5)

    asyncio.run(scenario())
    types = _types(client)
    assert types.count(("cancelled", "not_running")) == 1
    assert types.count(("cancelled", "cancelled")) == 1


def test_unrequested_cancellation_is_not_swallowed(tmp_path, monkeypatch):
    client = _client(tmp_path)
    started = asyncio.Event()

    async def fake_run(self, text, approver, emit, **kw):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(AgentSession, "run", fake_run)

    async def scenario():
        task = asyncio.create_task(client._run_message({"type": "message", "message_id": str(uuid.uuid4()), "session_id": "chat-1", "message": "hi"}))
        await started.wait()
        task.cancel()  # ör. agent kapanıyor; kullanıcı istemedi
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert ("cancelled", "cancelled") not in _types(client)
    assert client._turn_state["chat-1"]["active"] is False


class ScriptProvider(Provider):
    name = "fake"

    def __init__(self, calls):
        super().__init__("x", "fake")
        self.calls = list(calls)

    async def complete(self, system, messages, tools):
        if self.calls:
            return AssistantTurn(tool_calls=[self.calls.pop(0)])
        return AssistantTurn(text="done")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = f"/proc/{pid}/stat"
    if os.path.exists(stat):
        with open(stat) as f:
            return f.read().rsplit(")", 1)[-1].split()[0] != "Z"
    return True


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell command")
def test_stop_kills_a_running_command(tmp_path):
    pidfile = tmp_path / "pid"
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()], enable_shell=True)
    call = ToolCall("1", "run_command", {"command": f"echo $$ > {pidfile}; exec sleep 30"})
    session = AgentSession(cfg, ScriptProvider([call]), build_server(cfg))
    session.policy.session_grants.add("run_command")
    session.activity_store = ActivityStore(tmp_path / "a.db")

    async def emit(e):
        pass

    async def approver(tool, args):
        return True

    async def scenario():
        task = asyncio.create_task(session.run("go", approver, emit))
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            await asyncio.sleep(0.05)
        pid = int(pidfile.read_text())
        assert _alive(pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return pid

    pid = asyncio.run(scenario())
    end = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < end:
        time.sleep(0.1)
    assert not _alive(pid), "durdurulan komut hâlâ çalışıyor"
    phases = [r["phase"] for r in session.activity_store.list_events(limit=50)[::-1] if r["tool_name"] == "run_command"]
    assert phases[-1] == "cancelled"
    session.activity_store.close()


def test_hello_advertises_turn_cancel():
    import inspect
    from mcptoai_agent import relay_client
    assert "turn_cancel_v1" in inspect.getsource(relay_client.RelayClient._send_hello)


def test_replay_complete_reports_whether_turn_is_still_active(tmp_path):
    client = _client(tmp_path)
    sent = []

    class Socket:
        async def send(self, data):
            import json as _json
            sent.append(_json.loads(data))

    client.ws = Socket()
    client._turn_state["chat-1"] = {"id": "t-1", "active": True}
    client._turn_events["chat-1"] = {"t-1": []}
    asyncio.run(client._handle_event_replay_request({"session_id": "chat-1", "mode": "active_turn"}))
    assert sent[-1]["turn_active"] is True and sent[-1]["turn_id"] == "t-1"
    client._turn_state["chat-1"]["active"] = False
    asyncio.run(client._handle_event_replay_request({"session_id": "chat-1", "mode": "last_turn"}))
    assert sent[-1]["turn_active"] is False
