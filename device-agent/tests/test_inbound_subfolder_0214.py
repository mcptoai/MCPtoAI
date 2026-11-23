import base64
import hashlib
from pathlib import Path
from unittest.mock import patch
import pytest
from mcptoai_agent.inbound_session import InboundSession
from mcptoai_agent.inbound_approval import InboundApproval
from mcptoai_core.safe_subfolders import plan_inbound_subfolder


def new_session(root, subfolder='Heictest', data=b'hello'):
    return InboundSession(transfer_id='test-subfolder',name='photo.txt',size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),workspace=str(root),allowed_roots=[root],subfolder=subfolder)


def test_nonexistent_folder_preview_no_mutation_then_approved_creation(tmp_path):
    session=new_session(tmp_path)
    assert not (tmp_path/'Heictest').exists()
    assert 'Oluşturulacak klasör: Heictest' in session.preview
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        gate=InboundApproval()
        grant=gate.request(session,prompt=lambda req,preview:True)
        session.chunk(index=0,data=base64.b64encode(b'hello').decode())
        assert not (tmp_path/'Heictest').exists()
        actual=session.finish(consume_grant=lambda:gate.consume(session,grant),revalidate_destination=lambda:session.target)
    assert actual.read_bytes()==b'hello'
    assert actual.parent==tmp_path/'Heictest'
    assert not gate.consume(session,grant)


def test_denial_bad_digest_and_expiry_never_create(tmp_path):
    session=new_session(tmp_path)
    with pytest.raises(PermissionError):session.approve(trusted_native_approval=False)
    assert not (tmp_path/'Heictest').exists()
    session=new_session(tmp_path)
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(b'xxxxx').decode())
    with pytest.raises(ValueError):session.finish(consume_grant=lambda:True,revalidate_destination=lambda:session.target)
    assert not (tmp_path/'Heictest').exists()


def test_nested_existing_prefix_and_missing_tail(tmp_path):
    (tmp_path/'Reports').mkdir()
    session=new_session(tmp_path,'Reports/2026/Heictest')
    assert not (tmp_path/'Reports'/'2026').exists()
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(b'hello').decode())
    assert session.finish(consume_grant=lambda:True,revalidate_destination=lambda:session.target).read_bytes()==b'hello'


@pytest.mark.parametrize('relative',['../escape','/absolute','a/../../b','a//b','a/./b','a\\b','C:/evil','a'*256,'CON','a/','a.','x '*130,'x/'*16+'last'])
def test_traversal_and_invalid_components_rejected(tmp_path,relative):
    with pytest.raises((ValueError,PermissionError)):
        new_session(tmp_path,relative)
    assert not (tmp_path/'Heictest').exists()


def test_symlink_parent_and_outside_root_rejected(tmp_path):
    outside=tmp_path.parent/'outside-not-approved'
    (tmp_path/'link').symlink_to(outside,target_is_directory=True)
    with pytest.raises(PermissionError):new_session(tmp_path,'link/new')
    with pytest.raises(PermissionError):
        InboundSession(transfer_id='t',name='photo.txt',size=1,sha256='a'*64,
            workspace=str(tmp_path.parent),allowed_roots=[tmp_path],subfolder='Heictest')
    assert not (tmp_path/'Heictest').exists()


def test_alias_collision_and_approval_hash_binding(tmp_path):
    (tmp_path/'Heictest').mkdir()
    with pytest.raises(FileExistsError):new_session(tmp_path,'HEICTEST/new')
    a=new_session(tmp_path,'Heictest/new')
    b=new_session(tmp_path,'Heictest/other')
    assert a.request.digest()!=b.request.digest()
    assert a.preview!=b.preview
    assert not (tmp_path/'Heictest'/'new').exists()


def test_existing_folder_may_be_used_without_creating(tmp_path):
    (tmp_path/'Heictest').mkdir()
    session=new_session(tmp_path)
    assert session.create_folder is False
    assert 'Oluşturulacak klasör' not in session.preview


def test_symlink_inserted_after_offer_before_finish_rejected(tmp_path):
    data=b'hello'
    session=new_session(tmp_path,'Reports/Heictest',data)
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(data).decode())
    (tmp_path/'Reports').symlink_to(tmp_path.parent,target_is_directory=True)
    with pytest.raises(PermissionError):
        session.finish(consume_grant=lambda:True,revalidate_destination=lambda:session.target)
    assert not (tmp_path.parent/'Heictest'/'photo.txt').exists()


def test_creating_folder_is_bound_to_approval_preview_hash(tmp_path):
    session=new_session(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
        gate=InboundApproval()
        grant=gate.request(session,prompt=lambda request,preview:True)
        session.preview = session.preview.replace('Heictest','OtherFolder')
        assert gate.consume(session,grant) is False
    assert not (tmp_path/'Heictest').exists()


def test_revoke_on_finish_cannot_create_folder(tmp_path):
    session=new_session(tmp_path)
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(b'hello').decode())
    with pytest.raises(PermissionError):
        session.finish(consume_grant=lambda:False,revalidate_destination=lambda:session.target)
    assert not (tmp_path/'Heictest').exists()


def test_relay_inbound_offer_approval_then_create_and_distinct_invalid_path(tmp_path,monkeypatch):
    """Through actual RelayClient method, not only InboundSession unit tests."""
    import asyncio
    from unittest.mock import AsyncMock
    from mcptoai_agent.relay_client import RelayClient
    from mcptoai_agent.inbound_manager import InboundManager
    from mcptoai_agent.inbound_approval import InboundApproval
    monkeypatch.setenv('MCPTOAI_INBOUND_UPLOAD_CLI','1')
    client=object.__new__(RelayClient)
    client.cfg=type('Cfg',(),{'allowed_roots':[tmp_path]})()
    client._inbound=InboundManager(allowed_roots=[tmp_path])
    client._inbound_approval=InboundApproval()
    client._inbound_grants={}
    client._saved_chat_pending={}
    client._send=AsyncMock()
    data=b'hello'
    transfer='00000000-0000-4000-8000-000000000991'
    offer={'type':'file_offer','transfer_id':transfer,'name':'photo.txt','size':len(data),
           'sha256':hashlib.sha256(data).hexdigest(),'workspace':str(tmp_path),'subfolder':'Heictest'}
    async def scenario():
        with patch('mcptoai_agent.relay_client.sys.platform','linux'), \
             patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')), \
             patch('mcptoai_agent.inbound_approval.local_headless_prompt',return_value=True):
            await client._handle_inbound_upload(offer)
            assert client._send.await_args.args[0]['status']=='ready'
            assert not (tmp_path/'Heictest').exists()
            await client._handle_inbound_upload({'type':'file_chunk','transfer_id':transfer,'index':0,
                          'data':base64.b64encode(data).decode()})
            await client._handle_inbound_upload({'type':'file_finish','transfer_id':transfer})
            assert client._send.await_args.args[0]['status']=='completed'
            assert (tmp_path/'Heictest'/'photo.txt').read_bytes()==data
            bad={**offer,'transfer_id':'00000000-0000-4000-8000-000000000992','subfolder':'../escape'}
            await client._handle_inbound_upload(bad)
            error=client._send.await_args.args[0]
            assert error['status']=='failed' and error['reason']=='invalid_subfolder'
    asyncio.run(scenario())


def test_approval_folder_existence_state_cannot_change_before_finish(tmp_path):
    # Existing at offer -> removed before finish: no unapproved mkdir.
    existing=tmp_path/'Heictest'
    existing.mkdir()
    session=new_session(tmp_path)
    assert not session.create_folder
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(b'hello').decode())
    existing.rmdir()
    with pytest.raises(PermissionError,match='subfolder_path_changed'):
        session.finish(consume_grant=lambda:True,revalidate_destination=lambda:session.target)
    assert not existing.exists()
    # Missing at offer -> an unrelated party creates it: do not adopt silently.
    session=new_session(tmp_path)
    assert session.create_folder
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(b'hello').decode())
    existing.mkdir()
    with pytest.raises(PermissionError,match='subfolder_path_changed'):
        session.finish(consume_grant=lambda:True,revalidate_destination=lambda:session.target)
    assert not (existing/'photo.txt').exists()


def test_sensitive_subfolder_returns_explicit_invalid_path_reason(tmp_path):
    with pytest.raises(PermissionError,match='subfolder_protected_path'):
        new_session(tmp_path,'.ssh')
    assert not (tmp_path/'.ssh').exists()
