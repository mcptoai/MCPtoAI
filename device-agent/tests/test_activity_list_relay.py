"""Read-only, bounded activity list; never opens the user's real profile."""
import asyncio
from mcptoai_agent import activity_store
from mcptoai_agent.relay_client import RelayClient


def test_activity_list_is_bounded_and_metadata_only(monkeypatch):
    calls=[]
    class FakeStore:
        def list_events(self, *, limit):
            calls.append(limit)
            return [{'sequence': 12, 'schema_version': 1, 'activity_id': 'a', 'session_id': 's',
                     'turn_id': 't', 'tool_name': 'read_file', 'phase': 'completed',
                     'target_type': 'file', 'target_display': '[CONTENT HIDDEN]',
                     'summary': 'Done', 'timestamp_utc': '2026-11-12T00:00:00Z',
                     'permission_decision': 'approved'}]
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(activity_store,'ActivityStore',FakeStore)
    sent=[]
    client=object.__new__(RelayClient)
    async def send(event):sent.append(event)
    client._send=send
    asyncio.run(client._handle_activity_list({'request_id':'request-1','limit':100}))
    assert calls==[100,'closed']
    assert sent[0]['type']=='activity_list_response'
    assert sent[0]['items'][0]['permission_decision']=='approved'
    assert 'sequence' not in sent[0]['items'][0]
    asyncio.run(client._handle_activity_list({'request_id':'request-2','limit':101}))
    assert len(sent)==1
