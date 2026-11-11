import asyncio
from types import SimpleNamespace
import httpx
from mcptoai_agent.event_journal import EventJournal
from mcptoai_agent import answer_sync


def test_404_stops_only_missing_session_and_other_errors_retry(tmp_path, monkeypatch):
    journal = EventJournal(tmp_path / 'events.json')
    for sid in ('gone', 'retry', 'good'):
        journal.append(sid, {'type':'event','session_id':sid,'seq':1,'event':{'type':'text','text':'answer'}})
    calls = []
    class Provider:
        async def _request(self, method, path, body=None):
            sid = path.split('/')[0]
            calls.append(sid)
            if sid in ('gone', 'retry'):
                code = 404 if sid == 'gone' else 503
                response = httpx.Response(code, request=httpx.Request('POST', 'https://example.invalid/'))
                raise httpx.HTTPStatusError('failed', request=response.request, response=response)
            return {'ok':True}
    monkeypatch.setattr(answer_sync,'history_provider',lambda cfg:Provider())
    monkeypatch.setattr(answer_sync,'selected_history_provider_name',lambda cfg:'mcptoai')
    asyncio.run(answer_sync.sync_answers(SimpleNamespace(),journal))
    asyncio.run(answer_sync.sync_answers(SimpleNamespace(),journal))
    assert calls == ['gone','retry','good','retry']
