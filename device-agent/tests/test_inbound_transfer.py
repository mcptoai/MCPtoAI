import hashlib
import pytest
from mcptoai_agent.inbound_transfer import InboundStaging, validate_destination, MAX_FILE_BYTES, MAX_CHUNK_BYTES


def test_workspace_and_extension_limits(tmp_path):
    root = tmp_path / 'workspace'; root.mkdir()
    assert validate_destination('report.pdf', str(root), [root]) == root / 'report.pdf'
    for name in ('../escape.pdf', 'script.sh', 'install.command', 'setup.exe', 'setup.msi', 'installer.pkg', 'bundle.app', 'disk.dmg', 'macro.docm', 'macro.xlsm', '.secret.txt', 'nested/file.pdf'):
        with pytest.raises(ValueError): validate_destination(name, str(root), [root])
    with pytest.raises(PermissionError): validate_destination('ok.pdf', str(root), [tmp_path / 'other'])
    (root / 'link.pdf').symlink_to(tmp_path / 'outside')
    with pytest.raises(FileExistsError): validate_destination('link.pdf', str(root), [root])


def test_upload_requires_trusted_grant_and_exact_digest(tmp_path):
    data = b'private local upload'; digest = hashlib.sha256(data).hexdigest()
    target = tmp_path / 'report.txt'
    stage = InboundStaging(expected_size=len(data), sha256=digest, target=target)
    stage.append(data)
    with pytest.raises(PermissionError): stage.commit(approved=False, revalidate=lambda: True)
    with pytest.raises(PermissionError): stage.commit(approved=True, revalidate=lambda: False)
    assert not target.exists()
    assert stage.commit(approved=True, revalidate=lambda: True) == target
    assert target.read_bytes() == data


def test_size_checksum_and_replay_rejected(tmp_path):
    with pytest.raises(ValueError): InboundStaging(expected_size=MAX_FILE_BYTES+1, sha256='a'*64, target=tmp_path/'a')
    stage = InboundStaging(expected_size=2, sha256='a'*64, target=tmp_path/'a')
    stage.append(b'ab')
    with pytest.raises(ValueError): stage.commit(approved=True, revalidate=lambda: True)
    with pytest.raises(ValueError): stage.append(b'c')
    stage.close()
    assert not (tmp_path/'a').exists()


def test_native_approval_is_bound_to_identity_manifest_and_one_use(tmp_path):
    from mcptoai_core.action_contract import DeviceApprovalGate
    from mcptoai_agent.inbound_transfer import approval_request, approval_preview
    digest = hashlib.sha256(b'abc').hexdigest()
    req = approval_request(target=tmp_path/'invoice.pdf',size=3,sha256=digest)
    preview = approval_preview(req)
    gate = DeviceApprovalGate()
    grant = gate.record_local_approval(user_id='auth0|owner',device_id='paired-device',turn_id='transfer-1',
                                       request=req,preview=preview,now=100)
    modified = approval_request(target=tmp_path/'invoice.pdf',size=4,sha256=digest)
    assert not gate.consume(nonce=grant.nonce,user_id='auth0|owner',device_id='paired-device',
                            turn_id='transfer-1',request=modified,preview=approval_preview(modified),now=101)
    assert not gate.consume(nonce=grant.nonce,user_id='auth0|owner',device_id='paired-device',
                            turn_id='transfer-1',request=req,preview=preview,now=101)


def test_symlinked_parent_rejected_even_after_approval(tmp_path):
    real = tmp_path / 'real'; real.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(real, target_is_directory=True)
    data = b'safe'
    stage = InboundStaging(expected_size=len(data),sha256=hashlib.sha256(data).hexdigest(),target=alias/'invoice.txt')
    stage.append(data)
    with pytest.raises(PermissionError): stage.commit(approved=True,revalidate=lambda: True)
    assert not (real/'invoice.txt').exists()
    stage.close()


def test_origin_marking_macos_and_windows(tmp_path, monkeypatch):
    import mcptoai_agent.inbound_transfer as mod
    data = b'hello'
    target = tmp_path / 'download.txt'
    calls = []

    class FakeLib:
        def fsetxattr(self, fd, key, value, length, position, options):
            calls.append((key, value, length, position, options))
            return 0

    monkeypatch.setattr(mod.ctypes, 'CDLL', lambda *args, **kwargs: FakeLib())
    monkeypatch.setattr(mod.sys, 'platform', 'darwin')
    stage = InboundStaging(expected_size=len(data), sha256=hashlib.sha256(data).hexdigest(), target=target)
    stage.append(data)
    stage.commit(approved=True, revalidate=lambda: True)
    key, value, length, position, options = calls[0]
    assert key == b'com.apple.quarantine'
    assert value.split(b';')[1:] == [b'0081', b'MCPtoAI', b'']
    assert length == len(value) and position == 0 and options == 0
    target.unlink()

    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def write(self, payload): calls.append(payload)
        def flush(self): pass
        def fileno(self): return 1

    original_open = open
    def mocked_open(name, *args, **kwargs):
        if str(name).endswith(':Zone.Identifier'):
            calls.append(str(name))
            return Stream()
        return original_open(name, *args, **kwargs)

    monkeypatch.setattr('builtins.open', mocked_open)
    monkeypatch.setattr(mod.os, 'fsync', lambda fd: None)
    monkeypatch.setattr(mod.sys, 'platform', 'win32')
    stage = InboundStaging(expected_size=len(data), sha256=hashlib.sha256(data).hexdigest(), target=target)
    stage.append(data)
    stage.commit(approved=True, revalidate=lambda: True)
    assert calls[-2] == str(target) + ':Zone.Identifier'
    assert calls[-1] == b'[ZoneTransfer]\r\nZoneId=3\r\n'


def test_origin_mark_failure_removes_file(tmp_path, monkeypatch):
    import mcptoai_agent.inbound_transfer as mod
    data = b'hello'
    target = tmp_path / 'download.txt'
    stage = InboundStaging(expected_size=len(data), sha256=hashlib.sha256(data).hexdigest(), target=target)
    stage.append(data)
    monkeypatch.setattr(mod.sys, 'platform', 'darwin')
    class FakeLib:
        def fsetxattr(self, *args): return -1
    monkeypatch.setattr(mod.ctypes, 'CDLL', lambda *args, **kwargs: FakeLib())
    with pytest.raises(OSError):
        stage.commit(approved=True, revalidate=lambda: True)
    assert not target.exists()


@pytest.mark.skipif(__import__('sys').platform != 'darwin', reason='macOS xattr integration only')
def test_real_macos_quarantine(tmp_path):
    import subprocess
    data = b'hello'
    target = tmp_path / 'download.txt'
    stage = InboundStaging(expected_size=len(data), sha256=hashlib.sha256(data).hexdigest(), target=target)
    stage.append(data)
    stage.commit(approved=True, revalidate=lambda: True)
    value = subprocess.check_output(['xattr', '-p', 'com.apple.quarantine', str(target)])
    assert b';0081;MCPtoAI;' in value


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows NTFS ADS integration only')
def test_real_windows_zone_identifier(tmp_path):
    data = b'hello'
    target = tmp_path / 'download.txt'
    stage = InboundStaging(expected_size=len(data), sha256=hashlib.sha256(data).hexdigest(), target=target)
    stage.append(data)
    stage.commit(approved=True, revalidate=lambda: True)
    with open(str(target) + ':Zone.Identifier', 'rb') as stream:
        assert stream.read() == b'[ZoneTransfer]\r\nZoneId=3\r\n'


def test_disguised_executable_and_macro_office_rejected(tmp_path):
    import io,zipfile
    cases=[('fake.pdf',b'MZ\x90\x00program'),('fake.png',b'\x7fELFbad'),
           ('fake.txt',b'#!/bin/sh\necho unsafe'),('fake.jpg',b'not a jpeg')]
    for name,data in cases:
        target=tmp_path/name
        stage=InboundStaging(expected_size=len(data),sha256=hashlib.sha256(data).hexdigest(),target=target)
        stage.append(data)
        with pytest.raises(ValueError):stage.commit(approved=True,revalidate=lambda:True)
        assert not target.exists()
        stage.close()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        z.writestr('[Content_Types].xml','ok')
        z.writestr('word/document.xml','ok')
        z.writestr('word/vbaProject.bin',b'evil')
    data=buffer.getvalue();target=tmp_path/'macro.docx'
    stage=InboundStaging(expected_size=len(data),sha256=hashlib.sha256(data).hexdigest(),target=target)
    stage.append(data)
    with pytest.raises(ValueError):stage.commit(approved=True,revalidate=lambda:True)
    assert not target.exists()
