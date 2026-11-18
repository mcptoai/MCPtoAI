import base64
import hashlib
import pytest
from mcptoai_agent.inbound_session import InboundSession


def make(tmp_path, data=b'abc'):
    return InboundSession(transfer_id='transfer',name='invoice.txt',size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),workspace=str(tmp_path),allowed_roots=[tmp_path])


def test_staged_upload_waits_for_approval_and_ack(tmp_path):
    session=make(tmp_path)
    with pytest.raises(PermissionError): session.chunk(index=0,data=base64.b64encode(b'abc').decode())
    session.approve(trusted_native_approval=True)
    assert session.chunk(index=0,data=base64.b64encode(b'abc').decode()) == 0
    with pytest.raises(PermissionError): session.chunk(index=0,data=base64.b64encode(b'abc').decode())
    assert session.finish(consume_grant=lambda: True,revalidate_destination=lambda: tmp_path/'invoice.txt').read_bytes()==b'abc'
    with pytest.raises(PermissionError): session.finish(consume_grant=lambda: True,revalidate_destination=lambda: tmp_path/'invoice.txt')


def test_denial_and_digest_mismatch_never_write(tmp_path):
    session=make(tmp_path)
    with pytest.raises(PermissionError): session.approve(trusted_native_approval=False)
    assert not (tmp_path/'invoice.txt').exists()
    session=make(tmp_path)
    session.approve(trusted_native_approval=True)
    session.chunk(index=0,data=base64.b64encode(b'bad').decode())
    with pytest.raises(ValueError): session.finish(consume_grant=lambda: True,revalidate_destination=lambda: tmp_path/'invoice.txt')
    assert not (tmp_path/'invoice.txt').exists()


def test_expiry_rejects_without_file(tmp_path):
    session=make(tmp_path)
    session.deadline=0
    with pytest.raises(PermissionError): session.approve(trusted_native_approval=True)
    assert not (tmp_path/'invoice.txt').exists()


def test_activity_metadata_excludes_bytes(tmp_path):
    import asyncio
    from mcptoai_core.activity_recorder import ActivityRecorder
    session=make(tmp_path)
    recorder=ActivityRecorder(session_id='transfer-test',enabled=False)
    activity=recorder.begin('file.receive',{'path':str(session.target),'name':'invoice.pdf','size':3})
    payload=asyncio.run(session.record_activity('requested',activity=activity))
    assert payload['tool_name']=='file.receive'
    # Rastgele kimlikler yerine izin verilen alanları ve veri sınırını doğrula.
    assert set(payload) == {
        'activity_id', 'tool_name', 'phase', 'target_type', 'target_display',
        'summary', 'timestamp_utc', 'permission_decision', 'duration_ms',
        'provider', 'model', 'schema_version', 'session_id', 'turn_id',
    }
    assert payload['target_display'] == str(session.target)
    assert payload['phase'] == 'requested'
    assert payload['summary'] == 'Tool requested'
    assert payload['permission_decision'] is None
    assert all(isinstance(v, (int, float, type(None))) or
               (isinstance(v, str) and v != 'abc') for v in payload.values())
    assert 'YWJj' not in str(payload)
    session.close()
