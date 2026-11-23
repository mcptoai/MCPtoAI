"""v0.2.14: a 60-second native grant must not expire halfway through a 600s upload."""
import asyncio
import base64
import errno
import hashlib
import os
from pathlib import Path
import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from mcptoai_agent.inbound_approval import InboundApproval
from mcptoai_agent.inbound_session import InboundSession
from mcptoai_agent.inbound_manager import InboundManager
from mcptoai_agent.relay_client import RelayClient


def session_at(root, subfolder='Heictest'):
    b=b'hello 0.2.14'
    return InboundSession(transfer_id=str(uuid4()),name='proof.txt',size=len(b),
        sha256=hashlib.sha256(b).hexdigest(),workspace=str(root),allowed_roots=[root],subfolder=subfolder),b


def test_old_60_second_grant_failure_is_reproduced(tmp_path):
    s,data=session_at(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        gate=InboundApproval()
        grant=gate.request(s,prompt=lambda request,preview:True)
        s.chunk(index=0,data=base64.b64encode(data).decode())
        with patch('mcptoai_core.action_contract.time.time',return_value=grant.expires_at+1):
            with pytest.raises(PermissionError,match='inbound_approval_scope_invalid'):
                s.finish(consume_grant=lambda:gate.consume(s,grant),revalidate_destination=lambda:s.target)
    assert not (tmp_path/'Heictest').exists()


def test_bound_native_consent_survives_long_transfer_but_is_one_use(tmp_path):
    s,data=session_at(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        gate=InboundApproval()
        grant=gate.request(s,prompt=lambda request,preview:True)
        bound=gate.bind_for_transfer(s,grant)
        assert bound is not None
        assert not gate.gate._pending
        assert not gate.consume(s,grant)  # already consumed exactly once
        assert not (tmp_path/'Heictest').exists()  # no preapproval filesystem mutation
        s.chunk(index=0,data=base64.b64encode(data).decode())
        # Deliberately exceed the old ActionGrant's 60-second lifetime.
        with patch('mcptoai_core.action_contract.time.time',return_value=grant.expires_at+110):
            assert s.finish(consume_grant=lambda:gate.verify_bound_transfer(s,bound),
                            revalidate_destination=lambda:s.target).read_bytes()==data
        assert (tmp_path/'Heictest'/'proof.txt').read_bytes()==data
        assert not gate.verify_bound_transfer(s,bound)  # closed session cannot be reused


def test_scoped_authorization_rejects_changed_identity_or_preview(tmp_path):
    s,data=session_at(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        gate=InboundApproval();grant=gate.request(s,prompt=lambda r,p:True)
        bound=gate.bind_for_transfer(s,grant)
        s.chunk(index=0,data=base64.b64encode(data).decode())
        s.preview+='\nInjected change'
        assert not gate.verify_bound_transfer(s,bound)
        s.preview=s.preview.replace('\nInjected change','')
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','different-device')):
        with pytest.raises(PermissionError,match='inbound_approval_scope_invalid'):
            s.finish(consume_grant=lambda:gate.verify_bound_transfer(s,bound),revalidate_destination=lambda:s.target)
    assert not (tmp_path/'Heictest').exists()


def test_session_expiry_cannot_create_folder_even_with_bound_approval(tmp_path):
    s,data=session_at(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        gate=InboundApproval();bound=gate.bind_for_transfer(s,gate.request(s,prompt=lambda r,p:True))
        s.chunk(index=0,data=base64.b64encode(data).decode())
        s.deadline=time.monotonic()-1
        with pytest.raises(PermissionError,match='expired'):
            s.finish(consume_grant=lambda:gate.verify_bound_transfer(s,bound),revalidate_destination=lambda:s.target)
    assert not (tmp_path/'Heictest').exists()


def test_mkdirat_errno_and_component_are_preserved(tmp_path):
    s,data=session_at(tmp_path)
    s.approve(trusted_native_approval=True)
    s.chunk(index=0,data=base64.b64encode(data).decode())
    original=os.mkdir
    def denied(name,*args,**kwargs):
        if kwargs.get('dir_fd') is not None and name=='Heictest':
            raise PermissionError(errno.EACCES,'simulated mkdirat denial',name)
        return original(name,*args,**kwargs)
    with patch('mcptoai_core.safe_subfolders.os.mkdir',side_effect=denied):
        with pytest.raises(PermissionError) as raised:
            s.finish(consume_grant=lambda:True,revalidate_destination=lambda:s.target)
    assert raised.value.operation=='mkdirat'
    assert raised.value.kind=='subfolder'
    assert raised.value.path_component=='Heictest'
    assert raised.value.errno==errno.EACCES
    assert not (tmp_path/'Heictest').exists()


def test_relay_consumes_native_grant_before_first_chunk_and_finishes_after_60s(tmp_path,monkeypatch):
    monkeypatch.setenv('MCPTOAI_INBOUND_UPLOAD_CLI','1')
    client=object.__new__(RelayClient)
    client.cfg=type('Cfg',(),{'allowed_roots':[tmp_path]})()
    client._inbound=InboundManager(allowed_roots=[tmp_path]);client._inbound_approval=InboundApproval()
    client._inbound_grants={};client._saved_chat_pending={};client._send=AsyncMock()
    session,data=session_at(tmp_path)
    tid=session.transfer_id
    async def scenario():
        with patch('mcptoai_agent.relay_client.sys.platform','linux'), \
             patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')), \
             patch('mcptoai_agent.inbound_approval.local_headless_prompt',return_value=True):
            await client._handle_inbound_upload({'type':'file_offer','transfer_id':tid,
                 'name':'proof.txt','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                 'workspace':str(tmp_path),'subfolder':'Heictest'})
            assert client._send.await_args.args[0]['status']=='ready'
            assert len(client._inbound_grants)==1
            assert not client._inbound_approval.gate._pending
            assert not (tmp_path/'Heictest').exists()
            await client._handle_inbound_upload({'type':'file_chunk','transfer_id':tid,
                 'index':0,'data':base64.b64encode(data).decode()})
            with patch('mcptoai_core.action_contract.time.time',return_value=time.time()+110):
                await client._handle_inbound_upload({'type':'file_finish','transfer_id':tid})
            assert client._send.await_args.args[0]['status']=='completed'
            assert not client._inbound_grants
            assert (tmp_path/'Heictest'/'proof.txt').read_bytes()==data
    asyncio.run(scenario())


def test_relay_mkdirat_denial_logs_exact_operation_and_relative_component(tmp_path,monkeypatch,caplog):
    monkeypatch.setenv('MCPTOAI_INBOUND_UPLOAD_CLI','1')
    c=object.__new__(RelayClient)
    c.cfg=type('Cfg',(),{'allowed_roots':[tmp_path]})()
    c._inbound=InboundManager(allowed_roots=[tmp_path]);c._inbound_approval=InboundApproval()
    c._inbound_grants={};c._saved_chat_pending={};c._send=AsyncMock()
    tid=str(uuid4());data=b'hello'
    offer={'type':'file_offer','transfer_id':tid,'name':'proof.txt',
           'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
           'workspace':str(tmp_path),'subfolder':'Heictest'}
    original=os.mkdir
    def fail_mkdir(name,*args,**kwargs):
        if name=='Heictest' and kwargs.get('dir_fd') is not None:
            raise PermissionError(errno.EACCES,'injected test EACCES',name)
        return original(name,*args,**kwargs)
    async def scenario():
        with patch('mcptoai_agent.relay_client.sys.platform','linux'), \
             patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')), \
             patch('mcptoai_agent.inbound_approval.local_headless_prompt',return_value=True), \
             patch('mcptoai_core.safe_subfolders.os.mkdir',side_effect=fail_mkdir):
            await c._handle_inbound_upload(offer)
            assert c._send.await_args.args[0]['status']=='ready'
            await c._handle_inbound_upload({'type':'file_chunk','transfer_id':tid,
                    'index':0,'data':base64.b64encode(data).decode()})
            await c._handle_inbound_upload({'type':'file_finish','transfer_id':tid})
            response=c._send.await_args.args[0]
            assert response['status']=='failed' and response['reason']=='device_error'
    asyncio.run(scenario())
    assert not (tmp_path/'Heictest').exists()
    failure='\n'.join(r.getMessage() for r in caplog.records if 'Inbound upload rejected' in r.getMessage())
    assert 'operation=mkdirat' in failure
    assert 'path_kind=subfolder' in failure
    assert 'subfolder=Heictest' in failure
    assert 'component=Heictest' in failure
    assert 'errno=13' in failure
    assert str(tmp_path) not in failure  # no absolute private filesystem path
