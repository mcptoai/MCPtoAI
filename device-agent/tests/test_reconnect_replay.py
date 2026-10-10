import asyncio, json, uuid
from dataclasses import replace
from pathlib import Path

from mcptoai_agent.config import Settings
from mcptoai_agent.relay_client import RelayClient


def run(coro):
    return asyncio.run(coro)


class FakeWS:
    def __init__(self): self.sent=[]
    async def send(self,data): self.sent.append(json.loads(data))


def test_event_sequence_and_replay(monkeypatch,tmp_path):
    import mcptoai_agent.relay_client as rc
    monkeypatch.setattr(rc,'config_dir',lambda:tmp_path)
    client=RelayClient(Settings())
    ws=FakeWS(); client.ws=ws
    run(client._send_event('chat-1',{'type':'tool_request','id':'a'}))
    run(client._send_event('chat-1',{'type':'tool_result','id':'a'}))
    assert [x['seq'] for x in ws.sent]==[1,2]
    assert all(x['event_epoch']==client._event_epoch for x in ws.sent)
    ws.sent.clear()
    run(client._handle_event_replay_request({'session_id':'chat-1','after_seq':1}))
    assert len(ws.sent)==2 and ws.sent[0]['seq']==2
    assert ws.sent[0]['replay']=='after_seq'
    assert ws.sent[1]['type']=='replay_complete' and ws.sent[1]['through_seq']==2
