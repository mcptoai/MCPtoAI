import asyncio, json, uuid
from mcptoai_linux.config import Settings
from mcptoai_linux.relay_client import RelayClient

def run(coro): return asyncio.run(coro)
class FakeWS:
    def __init__(self): self.sent=[]
    async def send(self,data): self.sent.append(json.loads(data))

def test_event_sequence_and_replay(monkeypatch,tmp_path):
    import mcptoai_linux.relay_client as rc
    monkeypatch.setattr(rc,'config_dir',lambda:tmp_path)
    c=RelayClient(Settings()); c.ws=FakeWS()
    run(c._send_event('s',{'type':'tool_request'})); run(c._send_event('s',{'type':'tool_result'}))
    assert [x['seq'] for x in c.ws.sent]==[1,2]
    c.ws.sent.clear(); run(c._handle_event_replay_request({'session_id':'s','after_seq':1}))
    assert [x['seq'] for x in c.ws.sent if x['type']=='event']==[2]
    assert c.ws.sent[-1]['type']=='replay_complete'
