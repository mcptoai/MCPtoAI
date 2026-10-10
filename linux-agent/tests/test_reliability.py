import asyncio, os, uuid, json
from mcptoai_linux.reliability import MessageReceiptStore
from mcptoai_linux.config import Settings
from mcptoai_linux.relay_client import RelayClient

def test_receipt_store_deduplicates_and_persists_status(tmp_path):
    path=tmp_path/'receipts.json'; store=MessageReceiptStore(path); mid=str(uuid.uuid4())
    assert store.claim(mid,'chat-1')==(True,None)
    assert store.claim(mid,'chat-1')==(False,'running')
    store.finish(mid,'completed')
    assert MessageReceiptStore(path).status(mid)=='completed'
    assert os.stat(path).st_mode & 0o077 == 0

def test_running_receipt_becomes_interrupted_after_restart(tmp_path):
    path=tmp_path/'receipts.json'; mid=str(uuid.uuid4()); store=MessageReceiptStore(path)
    assert store.claim(mid,'chat-1')[0] is True
    restarted=MessageReceiptStore(path)
    assert restarted.status(mid)=='interrupted'

def test_event_sequence_and_replay(tmp_path):
    client=RelayClient(Settings(),receipt_store=MessageReceiptStore(tmp_path/'receipts.json'))
    sent=[]
    class FakeWS:
        async def send(self,data): sent.append(json.loads(data))
    client.ws=FakeWS()
    async def scenario():
        await client._send_event('chat-1',{'type':'tool_request'})
        await client._send_event('chat-1',{'type':'tool_result'})
        assert [x['seq'] for x in sent]==[1,2]
        sent.clear(); await client._handle_event_replay_request({'session_id':'chat-1','after_seq':1})
        assert [x['seq'] for x in sent if x['type']=='event']==[2]
        assert sent[-1]['type']=='replay_complete'
    asyncio.run(scenario())
