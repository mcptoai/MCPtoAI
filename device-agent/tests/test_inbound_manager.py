import hashlib
import pytest
from mcptoai_agent.inbound_manager import InboundManager


def test_cancel_disconnect_and_expiry_clean_local_staging(tmp_path):
    mgr=InboundManager(allowed_roots=[tmp_path],max_concurrent=1)
    offer=dict(name='a.pdf',size=3,sha256=hashlib.sha256(b'abc').hexdigest(),workspace=str(tmp_path))
    first=mgr.offer(transfer_id='one',**offer)
    with pytest.raises(PermissionError): mgr.offer(transfer_id='two',**offer)
    first.deadline=0
    with pytest.raises(PermissionError): mgr.get('one')
    assert first.closed
    second=mgr.offer(transfer_id='two',**offer)
    mgr.disconnect()
    assert second.closed
    assert not (tmp_path/'a.pdf').exists()


def test_existing_destination_never_overwritten(tmp_path):
    target=tmp_path/'a.pdf';target.write_bytes(b'original')
    mgr=InboundManager(allowed_roots=[tmp_path])
    with pytest.raises(FileExistsError):
        mgr.offer(transfer_id='collision',name='a.pdf',size=3,
                  sha256=hashlib.sha256(b'abc').hexdigest(),workspace=str(tmp_path))
    assert target.read_bytes()==b'original'


def test_maximum_50_mib_and_one_byte_over(tmp_path):
    from mcptoai_agent.inbound_transfer import MAX_FILE_BYTES
    mgr=InboundManager(allowed_roots=[tmp_path])
    offer=dict(name='large.pdf',sha256='a'*64,workspace=str(tmp_path))
    session=mgr.offer(transfer_id='max',size=MAX_FILE_BYTES,**offer)
    assert session.staging.expected_size==50*1024*1024
    mgr.cancel('max')
    with pytest.raises(ValueError):mgr.offer(transfer_id='oversize',size=MAX_FILE_BYTES+1,**offer)
