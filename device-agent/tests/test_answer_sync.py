import asyncio
from types import SimpleNamespace
from mcptoai_agent.event_journal import EventJournal
from mcptoai_agent import answer_sync

def test_answer_history_retry_and_idempotency(tmp_path,monkeypatch):
    journal=EventJournal(tmp_path/'journal.json')
    journal.append('session',{'type':'event','session_id':'session','event_epoch':'epoch','turn_id':'turn','seq':1,'event':{'type':'text','text':'answer','model':'model'}})
    class Provider:
        calls=[]
        async def _request(self,method,path,body=None):
            self.calls.append(body)
            return {'id':'saved'}
    provider=Provider()
    monkeypatch.setattr(answer_sync,'history_provider',lambda cfg:provider)
    monkeypatch.setattr(answer_sync,'selected_history_provider_name',lambda cfg:'mcptoai')
    asyncio.run(answer_sync.sync_answers(SimpleNamespace(),journal))
    asyncio.run(answer_sync.sync_answers(SimpleNamespace(),journal))
    assert len(provider.calls)==1
    assert provider.calls[0]['event_key']=='session:epoch:turn:1'
    assert EventJournal(tmp_path/'journal.json').data['session'][0]['history_saved'] is True
