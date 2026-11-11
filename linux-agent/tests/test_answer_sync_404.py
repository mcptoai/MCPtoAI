import asyncio
from types import SimpleNamespace
import httpx
from mcptoai_linux.event_journal import EventJournal
from mcptoai_linux import answer_sync, relay_client


def test_404_stops_only_missing_session(tmp_path, monkeypatch):
    journal = EventJournal(tmp_path/'events.json')
    for sid in ('gone', 'retry'):
        journal.append(sid,{'type':'event','session_id':sid,'seq':1,'event':{'type':'text','text':'answer'}})
    calls = []
    async def fake(cfg,req):
        sid=req['session_id'];calls.append(sid)
        response=httpx.Response(404 if sid=='gone' else 503,request=httpx.Request('POST','https://example.invalid/'))
        raise httpx.HTTPStatusError('failed',request=response.request,response=response)
    monkeypatch.setattr(relay_client,'handle_cloud_chat_request',fake)
    cfg=SimpleNamespace(user_settings={'history_provider':'mcptoai'})
    asyncio.run(answer_sync.sync_answers(cfg,journal))
    asyncio.run(answer_sync.sync_answers(cfg,journal))
    assert calls==['gone','retry','retry']
