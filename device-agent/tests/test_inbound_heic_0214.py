"""HEIC is device inbound only; never modifies chat image normalization."""
from hashlib import sha256
from pathlib import Path
import os
import sys
import pytest

from mcptoai_agent.inbound_transfer import InboundStaging, validate_destination, validate_heif_container


def heif_bytes(*, brand=b'heic', compatible=(b'mif1', b'heic')):
    brands = brand + b'\0\0\0\0' + b''.join(compatible)
    def box(tag, body): return (len(body)+8).to_bytes(4,'big') + tag + body
    return box(b'ftyp',brands) + box(b'meta',b'\0'*8) + box(b'mdat',b'actual-image-blob')


def test_heic_heif_exact_bytes_and_user_grant(tmp_path):
    for ext in ('.heic', '.heif'):
        data=heif_bytes(); target=validate_destination('photo'+ext, str(tmp_path), [tmp_path])
        stage=InboundStaging(expected_size=len(data),sha256=sha256(data).hexdigest(),target=target)
        stage.append(data)
        with pytest.raises(PermissionError):
            stage.commit(approved=False,revalidate=lambda:True)
        stage.commit(approved=True,revalidate=lambda:True)
        assert target.read_bytes()==data and sha256(target.read_bytes()).hexdigest()==sha256(data).hexdigest()


@pytest.mark.parametrize('data', [
    b'', b'MZ'+heif_bytes(), b'garbage'+heif_bytes(),
    heif_bytes(brand=b'avif',compatible=(b'avif',)),
    heif_bytes(brand=b'mif1',compatible=(b'mif1',)),
    heif_bytes()[:15], heif_bytes().replace(b'mdat',b'junk'),
    heif_bytes().replace(b'actual-image-blob',b''),
])
def test_malformed_or_wrong_brand_denied(tmp_path, data):
    target=tmp_path/'blocked.heic'
    stage=InboundStaging(expected_size=len(data),sha256=sha256(data).hexdigest(),target=target) if data else None
    if data:
        stage.append(data)
        with pytest.raises(ValueError): stage.commit(approved=True,revalidate=lambda:True)
    assert not target.exists()


def test_digest_mismatch_denied(tmp_path):
    data=heif_bytes();target=tmp_path/'bad.heic'
    stage=InboundStaging(expected_size=len(data),sha256='a'*64,target=target)
    stage.append(data)
    with pytest.raises(ValueError):stage.commit(approved=True,revalidate=lambda:True)
    assert not target.exists()


@pytest.mark.skipif(sys.platform != 'darwin',reason='macOS native sample / quarantine check')
def test_real_macos_heic_original_and_quarantine(tmp_path):
    import subprocess
    candidates=list(Path('/System/Library/Desktop Pictures/.thumbnails').glob('*.heic'))
    if not candidates: pytest.skip('macOS native HEIC fixture not available')
    source=next((p for p in candidates if 0<p.stat().st_size<=10*1024*1024),None)
    if source is None: pytest.skip('sized system HEIC fixture not available')
    data=source.read_bytes()
    assert validate_heif_container(__import__('io').BytesIO(data))
    target=tmp_path/'authentic.heic'
    stage=InboundStaging(expected_size=len(data),sha256=sha256(data).hexdigest(),target=target)
    stage.append(data);stage.commit(approved=True,revalidate=lambda:True)
    assert target.read_bytes()==data
    value=subprocess.check_output(['xattr','-p','com.apple.quarantine',str(target)])
    assert b';0081;MCPtoAI;' in value


def test_heic_capability_is_separate_and_not_advertised_on_windows():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from mcptoai_agent.relay_client import RelayClient
    async def hello(platform):
        client=object.__new__(RelayClient)
        client.cfg=type('Cfg',(),{'allowed_roots':[Path('/tmp')]})()
        client._event_epoch='heic-test'
        client._send=AsyncMock()
        with patch('mcptoai_agent.relay_client.sys.platform',platform):
            if platform == 'darwin':
                with patch('mcptoai_agent.inbound_approval.desktop_approval_available',return_value=True), \
                     patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('owner','device')):
                    await client._send_hello()
            else:
                await client._send_hello()
        return client._send.await_args.args[0]['capabilities']
    mac=asyncio.run(hello('darwin'))
    assert 'inbound_upload_v1' in mac and 'inbound_heic_original_v1' in mac
    assert 'inbound_upload_50mib_v1' in mac
    assert 'inbound_subfolder_create_v1' in mac
    windows=asyncio.run(hello('win32'))
    assert 'inbound_upload_v1' not in windows and 'inbound_heic_original_v1' not in windows
    assert 'inbound_upload_50mib_v1' not in windows
    assert 'inbound_subfolder_create_v1' not in windows


@pytest.mark.skipif(sys.platform != 'darwin', reason='requires native macOS HEIC and quarantine')
def test_real_heic_offer_chunks_local_one_use_approval_finish(tmp_path, monkeypatch):
    """Local protocol integration, NOT a live browser-to-production-agent test.

    Uses a native HEIC fixture, real inbound session, approval gate and xattr;
    replaces only Electron's interactive local dialog with a trusted test stub.
    """
    import base64
    import uuid
    import subprocess
    from mcptoai_agent.inbound_manager import InboundManager
    from mcptoai_agent.inbound_approval import InboundApproval
    import mcptoai_agent.inbound_approval as approval_module
    from mcptoai_agent.inbound_transfer import MAX_CHUNK_BYTES
    source = Path('/System/Library/Desktop Pictures/.thumbnails/Valley Light.heic')
    if not source.is_file():
        pytest.skip('macOS native HEIC fixture absent')
    raw = source.read_bytes()
    assert validate_heif_container(__import__('io').BytesIO(raw))
    tid = str(uuid.uuid4())
    manager = InboundManager(allowed_roots=[tmp_path])
    session = manager.offer(transfer_id=tid, name='photo.heic', size=len(raw),
                            sha256=sha256(raw).hexdigest(), workspace=str(tmp_path))
    monkeypatch.setattr(approval_module, 'paired_identity', lambda: ('test-owner', 'test-device'))
    gate = InboundApproval()
    approval_calls = []
    def trusted_local_test_dialog(request, preview):
        approval_calls.append((request.digest(), preview))
        return True
    grant = gate.request(session, prompt=trusted_local_test_dialog)
    assert len(approval_calls) == 1
    for index, offset in enumerate(range(0, len(raw), MAX_CHUNK_BYTES)):
        encoded = base64.b64encode(raw[offset:offset+MAX_CHUNK_BYTES]).decode('ascii')
        assert session.chunk(index=index, data=encoded) == index
    target = session.finish(consume_grant=lambda: gate.consume(session, grant),
                             revalidate_destination=lambda: validate_destination('photo.heic',str(tmp_path),[tmp_path]))
    manager.cancel(tid)
    assert target.read_bytes() == raw
    assert sha256(target.read_bytes()).hexdigest() == sha256(raw).hexdigest()
    assert b';0081;MCPtoAI;' in subprocess.check_output(['xattr','-p','com.apple.quarantine',str(target)])
    assert not gate.consume(session, grant)  # one-time grant cannot be replayed
    with pytest.raises(PermissionError): manager.get(tid)
