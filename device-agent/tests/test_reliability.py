import asyncio
import json
import os
import uuid

from mcptoai_agent.reliability import MessageReceiptStore


def test_receipt_store_deduplicates_and_persists_status(tmp_path):
    path=tmp_path/"receipts.json"
    store=MessageReceiptStore(path)
    mid=str(uuid.uuid4())
    assert store.claim(mid,"chat-1")== (True,None)
    assert store.claim(mid,"chat-1")== (False,"running")
    store.finish(mid,"completed")
    assert MessageReceiptStore(path).status(mid)=="completed"
    assert os.stat(path).st_mode & 0o077 == 0


def test_running_receipt_becomes_interrupted_after_restart(tmp_path):
    path=tmp_path/"receipts.json"
    mid=str(uuid.uuid4())
    store=MessageReceiptStore(path)
    assert store.claim(mid,"chat-1")[0] is True
    restarted=MessageReceiptStore(path)
    assert restarted.status(mid)=="interrupted"
    assert restarted.claim(mid,"chat-1")== (False,"interrupted")


def test_event_sequence_and_replay(tmp_path):
    from dataclasses import replace
    from mcptoai_agent.config import Settings
    from mcptoai_agent.relay_client import RelayClient

    cfg=Settings()
    client=RelayClient(cfg,receipt_store=MessageReceiptStore(tmp_path/"receipts.json"))
    sent=[]
    class FakeSocket:
        async def send(self,data): sent.append(json.loads(data))
    client.ws=FakeSocket()

    async def scenario():
        await client._send_event("chat-1",{"type":"tool_request","name":"x"})
        await client._send_event("chat-1",{"type":"tool_result","name":"x"})
        assert [x["seq"] for x in sent]==[1,2]
        sent.clear()
        await client._handle_event_replay_request({"session_id":"chat-1","after_seq":1})
        assert len(sent)==2 and sent[0]["seq"]==2
        assert sent[0]["event"]["type"]=="tool_result"
        assert sent[1]["type"]=="replay_complete"
    asyncio.run(scenario())


def test_duplicate_running_message_is_suppressed_without_terminal_error(tmp_path, monkeypatch):
    from mcptoai_agent.config import Settings
    from mcptoai_agent.relay_client import RelayClient

    mid=str(uuid.uuid4())
    store=MessageReceiptStore(tmp_path/"receipts.json")
    assert store.claim(mid,"chat-1")[0] is True
    client=RelayClient(Settings(provider="ollama",model="test-model"),receipt_store=store)
    sent=[]
    async def fake_send_event(session_id,event): sent.append((session_id,event))
    client._send_event=fake_send_event

    async def scenario():
        await client._run_message({"type":"message","message_id":mid,"session_id":"chat-1","message":"hello"})
    asyncio.run(scenario())
    assert sent==[]
