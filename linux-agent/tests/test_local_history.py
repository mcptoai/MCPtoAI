import asyncio
from dataclasses import replace

from mcptoai_linux.config import settings
from mcptoai_linux.local_history import LocalHistoryStore
from mcptoai_linux.relay_client import RelayClient


def test_local_history_crud(tmp_path):
    store=LocalHistoryStore(tmp_path/'history.sqlite3')
    created=store.handle({'action':'cloud_chat_create','title':'New chat','provider':'anthropic','model':'sonnet'})
    assert created['ok']
    sid=created['data']['id']
    assert store.handle({'action':'cloud_chat_add_message','session_id':sid,'role':'user','content':'Check brightforgeai.com','model':'sonnet'})['ok']
    assert store.handle({'action':'cloud_chat_add_message','session_id':sid,'role':'assistant','content':'Available','model':'sonnet'})['ok']
    detail=store.handle({'action':'cloud_chat_get','session_id':sid})['data']
    assert detail['title']=='Check brightforgeai.com'
    assert [m['role'] for m in detail['messages']]==['user','assistant']
    rows=store.handle({'action':'cloud_chats_list'})['data']
    assert rows[0]['id']==sid and rows[0]['message_count']==2
    updated=store.handle({'action':'cloud_chat_update','session_id':sid,'is_pinned':True})['data']
    assert updated['is_pinned'] is True
    assert store.handle({'action':'cloud_chat_delete','session_id':sid})['ok']
    assert store.handle({'action':'cloud_chat_get','session_id':sid})['ok'] is False


def test_relay_reports_local_history_mode():
    cfg=replace(settings,user_settings={**settings.user_settings,'history_provider':'local'})
    client=RelayClient(cfg); sent=[]
    async def fake_send(payload): sent.append(payload)
    client._send=fake_send
    async def run():
        await client._handle({'type':'history_status_request'})
        await asyncio.sleep(0)
    asyncio.run(run())
    assert sent and sent[-1]['type']=='history_status' and sent[-1]['provider']=='local'
