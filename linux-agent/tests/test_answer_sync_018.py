import asyncio
from types import SimpleNamespace
from mcptoai_linux.event_journal import EventJournal
from mcptoai_linux.answer_sync import sync_answers

def test_cloud_answer_sync_is_retryable_and_deduplicated(tmp_path,monkeypatch):
    from mcptoai_linux import relay_client
    journal=EventJournal(tmp_path/'journal.json')
    journal.append('12345678-1234-4234-8234-123456789abc',{'type':'event','session_id':'12345678-1234-4234-8234-123456789abc','event_epoch':'epoch','turn_id':'turn','seq':1,'event':{'type':'text','text':'answer','model':'test'}})
    sent=[]
    async def fake_request(cfg,req):
        sent.append(req)
        return {'ok':True}
    monkeypatch.setattr(relay_client,'handle_cloud_chat_request',fake_request)
    cfg=SimpleNamespace(user_settings={'history_provider':'mcptoai'})
    asyncio.run(sync_answers(cfg,journal));asyncio.run(sync_answers(cfg,journal))
    assert len(sent)==1
    assert sent[0]['tool_data']['mcptoai_event_key']=='12345678-1234-4234-8234-123456789abc:epoch:turn:1'
    assert EventJournal(tmp_path/'journal.json').data['12345678-1234-4234-8234-123456789abc'][0]['history_saved']
