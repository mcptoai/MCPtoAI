"""Core #40 provider, turn, relay, and privacy integration."""
import asyncio
import base64
import copy
import hashlib
import json
import uuid
from dataclasses import replace

import pytest
from mcptoai_core.documents import DocumentError, NOTICE
from mcptoai_agent.agent import AgentSession
from mcptoai_agent.config import Settings, settings
from mcptoai_agent.providers.base import AssistantTurn, Provider
from mcptoai_agent.providers.anthropic_provider import AnthropicProvider
from mcptoai_agent.providers.openai_provider import OpenAIProvider
from mcptoai_agent.relay_client import RelayClient
from mcptoai_agent.reliability import MessageReceiptStore
from mcptoai_agent.tools import build_server


def envelope(text='PRIVATE_ATTACHMENT_CANARY', name='notes.txt'):
    data = text.encode()
    return {'version':1,'files':[{'name':name,'size':len(data),'media_type':'text/plain','data_base64':base64.b64encode(data).decode()}]}


class FakeProvider(Provider):
    context_window_tokens = 262144
    name = 'openai'
    def __init__(self):
        super().__init__('fake','gpt-5')
        self.calls = []
    async def complete(self, system, messages, tools):
        self.calls.append((system, copy.deepcopy(messages)))
        return AssistantTurn(text='Reviewed.')


def test_agent_extraction_privacy_and_visible_truncation(tmp_path, monkeypatch):
    monkeypatch.setenv('MCPTOAI_ACTIVITY_LOG', '0')
    cfg = replace(settings, allowed_roots=[tmp_path], enable_shell=False)
    provider = FakeProvider(); session = AgentSession(cfg, provider, build_server(cfg))
    events = []
    async def emit(e): events.append(e)
    async def deny(*args): pytest.fail('Document processing must not invoke tools or approval')
    asyncio.run(session.run('Read it', deny, emit, attachments=envelope('PRIVATE_ATTACHMENT_CANARY' * 6500)))
    message = provider.calls[0][1][0]
    assert 'PRIVATE_ATTACHMENT_CANARY' in message['content']
    assert NOTICE not in message['content']
    assert 'untrusted reference data' in provider.calls[0][0]
    assert any(e['type']=='document_activity' and set(e['attachment'])=={'name','size','type'} for e in events)
    assert any(e['type']=='document_notice' and NOTICE in e['message'] for e in events)
    assert 'PRIVATE_ATTACHMENT_CANARY' not in json.dumps(events)
    assert not session.audit


def test_invalid_batch_never_reaches_provider_or_history(tmp_path, monkeypatch):
    monkeypatch.setenv('MCPTOAI_ACTIVITY_LOG', '0')
    cfg = replace(settings, allowed_roots=[tmp_path], enable_shell=False)
    provider = FakeProvider(); session = AgentSession(cfg, provider, build_server(cfg))
    async def emit(e): pytest.fail('Failed batch must not emit activity')
    with pytest.raises(DocumentError):
        asyncio.run(session.run('Read', None, emit, attachments=envelope(name='bad.exe')))
    assert not provider.calls and not session.history


def test_both_provider_native_file_parts():
    file = {'name':'report.pdf','media_type':'application/pdf','data_base64':'JVBERi0='}
    msg = {'role':'user','content':'Review','files':[file], 'images':[{'data_url':'data:image/png;base64,YWJj'}]}
    anthropic = AnthropicProvider._convert([msg])[0]['content']
    assert [b['type'] for b in anthropic] == ['text','image','document']
    assert anthropic[-1]['source']['data'] == 'JVBERi0='
    openai = OpenAIProvider._convert('system',[msg])[1]['content']
    assert [b['type'] for b in openai] == ['text','image_url','file']
    assert openai[-1]['file'] == {'filename':'report.pdf','file_data':'data:application/pdf;base64,JVBERi0='}


def test_relay_forwards_and_deduplicates_attachment_only_turn(tmp_path, monkeypatch):
    client = RelayClient(Settings(provider='ollama', model='test'), receipt_store=MessageReceiptStore(tmp_path/'receipts.json'))
    events=[]; calls=[]
    async def send(sid,e,turn_id=None): events.append(e)
    async def run(self,text,approver,emit,**kwargs):
        calls.append((text,kwargs)); await emit({'type':'done'})
    client._send_event=send
    monkeypatch.setattr(AgentSession,'run',run)
    data=b'PRIVATE_ATTACHMENT_CANARY'
    tid=str(uuid.uuid4()); turn=str(uuid.uuid4()); sid=str(uuid.uuid4())
    async def scenario():
        offer={'type':'file_offer','purpose':'chat','transfer_id':tid,'session_id':sid,'turn_id':turn,'name':'notes.txt','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        assert (await client._chat_attachments.handle(offer))['status']=='ready'
        assert (await client._chat_attachments.handle({'type':'file_chunk','transfer_id':tid,'index':0,'data':base64.b64encode(data).decode()}))['type']=='file_ack'
        assert (await client._chat_attachments.handle({'type':'file_finish','transfer_id':tid}))['status']=='completed'
        msg={'type':'message','session_id':sid,'message_id':turn,'attachment_ids':[tid]}
        # The websocket is normally present when the relay delivers a turn.
        client.ws=object()
        await client._run_message(msg)
        await client._run_message(msg)
    asyncio.run(scenario())
    assert len(calls)==1
    assert calls[0][0]=='Please review the attached files.'
    assert base64.b64decode(calls[0][1]['attachments']['files'][0]['data_base64'])==data
    assert not client._turn_state[sid]['active']


def test_relay_document_error_is_sanitized(tmp_path, monkeypatch, caplog):
    client=RelayClient(Settings(provider='ollama',model='test'),receipt_store=MessageReceiptStore(tmp_path/'receipts.json'))
    events=[]
    async def send(sid,e,turn_id=None): events.append(e)
    client._send_event=send
    async def run(*args,**kw): raise DocumentError('invalid_type','Attachment is invalid.')
    monkeypatch.setattr(AgentSession,'run',run)
    data=b'PRIVATE_ATTACHMENT_CANARY';tid=str(uuid.uuid4());turn=str(uuid.uuid4());sid=str(uuid.uuid4())
    async def scenario():
        offer={'type':'file_offer','purpose':'chat','transfer_id':tid,'session_id':sid,'turn_id':turn,'name':'notes.txt','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        await client._chat_attachments.handle(offer)
        await client._chat_attachments.handle({'type':'file_chunk','transfer_id':tid,'index':0,'data':base64.b64encode(data).decode()})
        await client._chat_attachments.handle({'type':'file_finish','transfer_id':tid})
        client.ws=object()
        await client._run_message({'type':'message','session_id':sid,'message_id':turn,'message':'Read','attachment_ids':[tid]})
    asyncio.run(scenario())
    assert events[-1]=={'type':'error','code':'invalid_type','message':'Attachment is invalid.'}
    assert 'PRIVATE_ATTACHMENT_CANARY' not in caplog.text


def test_hello_advertises_document_contract(tmp_path):
    client = RelayClient(Settings(provider='ollama',model='test'), receipt_store=MessageReceiptStore(tmp_path/'receipts.json'))
    messages = []
    async def send(e): messages.append(e)
    client._send = send
    asyncio.run(client._send_hello())
    assert 'document_processing_v1' in messages[0]['capabilities']


def test_local_history_attachment_metadata_round_trip(tmp_path):
    import uuid
    from mcptoai_agent.history import LocalHistoryProvider
    history = LocalHistoryProvider(tmp_path / 'history.sqlite3')
    async def check():
        chat = await history.create_chat(title='Files', provider='openai', model='gpt-5')
        metadata = [{'name': 'table.csv', 'size': 512, 'type': 'text/csv'}]
        await history.add_message(chat['id'], role='user', content='Analyze', tool_data={'attachment_metadata': metadata})
        saved = await history.get_chat(chat['id'])
        assert saved['messages'][0]['tool_data']['attachment_metadata'] == metadata
        assert 'data_base64' not in str(saved)
    asyncio.run(check())
