import asyncio
import json
import os
from mcptoai_linux.config import Settings
from mcptoai_linux.event_journal import EventJournal
from mcptoai_linux.relay_client import RelayClient

class Socket:
    def __init__(self):self.sent=[]
    async def send(self,data):self.sent.append(json.loads(data))

def test_pending_approval_is_interrupted_not_actionable_after_restart(tmp_path,monkeypatch):
    import mcptoai_linux.relay_client as rc
    monkeypatch.setattr(rc,'EventJournal',lambda:EventJournal(tmp_path/'events.json'))
    c=RelayClient(Settings());c.ws=Socket()
    async def run():
        c._turn_state['s']={'id':'turn','active':True}
        await c._send_event('s',{'type':'approval_required','approval_id':'approval1','tool':'write_file','arguments':{'content':'secret'}},turn_id='turn')
    asyncio.run(run())
    assert os.stat(tmp_path/'events.json').st_mode & 0o077 == 0
    assert 'secret' not in (tmp_path/'events.json').read_text()
    restarted=RelayClient(Settings());restarted.ws=Socket()
    asyncio.run(restarted._handle_event_replay_request({'session_id':'s','mode':'last_turn'}))
    events=[x['event'] for x in restarted.ws.sent if x['type']=='event']
    assert events==[{'type':'approval_interrupted','approval_id':'approval1','tool':'write_file'}]
    assert restarted.ws.sent[-1]['type']=='replay_complete'
    assert not restarted.pending_approvals

def test_replay_modes_and_invalid_cursor(tmp_path,monkeypatch):
    import mcptoai_linux.relay_client as rc
    monkeypatch.setattr(rc,'EventJournal',lambda:EventJournal(tmp_path/'events.json'))
    c=RelayClient(Settings());c.ws=Socket()
    async def run():
        c._turn_state['s']={'id':'t','active':True}
        await c._send_event('s',{'type':'text','text':'ok'},turn_id='t')
        await c._handle_event_replay_request({'session_id':'s','mode':'active_turn'})
        count=len(c.ws.sent)
        await c._handle_event_replay_request({'session_id':'s','mode':'last_turn','after_seq':0})
        assert len(c.ws.sent)==count
    asyncio.run(run())
    assert c.ws.sent[-1]['type']=='replay_complete'
