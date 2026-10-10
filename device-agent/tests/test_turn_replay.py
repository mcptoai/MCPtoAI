"""Tur bazlı olay günlüğü ve yeniden oynatma sözleşmesi testleri."""
import asyncio
import json
from collections import OrderedDict, deque
from mcptoai_agent.config import Settings
from mcptoai_agent.relay_client import RelayClient

class Socket:
    def __init__(self): self.sent=[]; self.on_send=None
    async def send(self,data):
        packet=json.loads(data); self.sent.append(packet)
        if self.on_send: await self.on_send(packet)

def run(coro): return asyncio.run(coro)

def client():
    c=RelayClient(Settings()); c.ws=Socket(); return c

def test_active_turn_replay_and_completion():
    async def scenario():
        c=client();c._turn_state['s']={'id':'t','active':True}
        await c._send_event('s',{'type':'text'},turn_id='t')
        await c._send_event('s',{'type':'tool_result'},turn_id='t')
        c.ws.sent.clear()
        await c._handle_event_replay_request({'session_id':'s','mode':'active_turn'})
        assert [p['seq'] for p in c.ws.sent if p['type']=='event']==[1,2]
        assert all(p['turn_id']=='t' and p['replay']=='active_turn' for p in c.ws.sent[:-1])
        assert c.ws.sent[-1]['type']=='replay_complete' and c.ws.sent[-1]['through_seq']==2
    run(scenario())

def test_active_turn_missing_returns_completion():
    c=client();run(c._handle_event_replay_request({'session_id':'s','mode':'active_turn'}))
    assert c.ws.sent==[{'type':'replay_complete','session_id':'s','mode':'active_turn','turn_id':None,'through_seq':0,'event_epoch':c._event_epoch}]

def test_last_turn_completed():
    async def scenario():
        c=client();c._turn_state['s']={'id':'t','active':False}
        await c._send_event('s',{'type':'done'},turn_id='t')
        c.ws.sent.clear();await c._handle_event_replay_request({'session_id':'s','mode':'last_turn'})
        assert c.ws.sent[0]['turn_id']=='t' and c.ws.sent[0]['replay']=='last_turn'
        assert c.ws.sent[-1]['turn_id']=='t'
    run(scenario())

def test_replay_catches_new_events():
    async def scenario():
        c=client();c._turn_state['s']={'id':'t','active':True}
        await c._send_event('s',{'type':'text'},turn_id='t')
        async def inject(packet):
            if packet.get('replay') and packet['seq']==1:
                await c._send_event('s',{'type':'tool_result'},turn_id='t')
        c.ws.sent.clear();c.ws.on_send=inject
        await c._handle_event_replay_request({'session_id':'s','mode':'active_turn'})
        assert [p['seq'] for p in c.ws.sent if p.get('replay')]==[1,2]
        assert c.ws.sent[-1]['through_seq']==2
    run(scenario())

def test_turn_binding_and_memory_limits():
    async def scenario():
        c=client()
        for i in range(60):
            sid=f's{i}'
            for j in range(3):
                await c._send_event(sid,{'type':'approval_required'},turn_id=f't{j}')
                await c._send_event(sid,{'type':'approval_resolved'},turn_id=f't{j}')
        assert len(c._event_journal)==len(c._turn_events)==50
        assert len(c._turn_events['s59'])==2
        assert list(c._turn_events['s59'])==['t1','t2']
        assert all(p['turn_id']=='t2' for p in c._turn_events['s59']['t2'])
    run(scenario())

def test_disconnection_skips_completion():
    async def scenario():
        c=client();c._turn_state['s']={'id':'t','active':True}
        await c._send_event('s',{'type':'text'},turn_id='t')
        sock=c.ws;sock.sent.clear()
        async def disconnect(packet):
            if packet.get('replay'):c.ws=None
        sock.on_send=disconnect
        await c._handle_event_replay_request({'session_id':'s','mode':'active_turn'})
        assert not any(p['type']=='replay_complete' for p in sock.sent)
    run(scenario())

def test_concurrent_turn_rejected_without_receipt(monkeypatch,tmp_path):
    """Çalışan tur sırasında ikinci mesaj makbuzlanmadan reddedilir."""
    import uuid
    from mcptoai_agent.reliability import MessageReceiptStore
    c=RelayClient(Settings(),receipt_store=MessageReceiptStore(tmp_path/'receipts.json'))
    c.ws=Socket()
    first=str(uuid.uuid4()); second=str(uuid.uuid4())
    c._turn_state['s']={'id':first,'active':True}
    async def scenario():
        await c._run_message({'session_id':'s','message':'second','message_id':second})
    # Tur denetimi sağlayıcı çağrısından önce yapılmalıdır.
    run(scenario())
    assert any(p.get('event',{}).get('code')=='turn_in_progress' for p in c.ws.sent)
    assert not (tmp_path/'receipts.json').exists()
