"""Atomic, no-overwrite macOS save without exposing a partially written image."""
from hashlib import sha256
from io import BytesIO
from PIL import Image

def real_png():
    f=BytesIO()
    Image.new('RGB',(16,16),(10,20,30)).save(f,format='PNG')
    return f.getvalue()

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest
from mcptoai_agent.inbound_transfer import InboundStaging


def stage(path, data):
    item=InboundStaging(expected_size=len(data),sha256=sha256(data).hexdigest(),target=path)
    for offset in range(0,len(data),128*1024):
        item.append(data[offset:offset+128*1024])
    return item


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS atomic quarantine')
def test_not_visible_until_quarantined_and_fully_written(tmp_path):
    data=real_png()
    target=tmp_path/'picture.png'
    item=stage(target,data)
    actual=item._mark_origin
    def assert_before_link(fd):
        assert not target.exists()
        assert os.fstat(fd).st_size == len(data)
        return actual(fd)
    with patch.object(item,'_mark_origin',assert_before_link):
        result=item.commit_atomic_chat_image(approved=True,revalidate=lambda: True)
    assert result==target and target.read_bytes()==data
    assert b';0081;MCPtoAI;' in subprocess.check_output(['xattr','-p','com.apple.quarantine',str(target)])
    assert not list(tmp_path.glob('.mcptoai-image-*.part'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS atomic quarantine')
def test_existing_target_does_not_overwrite_or_leave_staging(tmp_path):
    data=real_png()
    target=tmp_path/'picture.png'
    item=stage(target,data)
    target.write_bytes(b'original')
    with pytest.raises(FileExistsError):
        item.commit_atomic_chat_image(approved=True,revalidate=lambda: True)
    assert target.read_bytes()==b'original'
    assert not list(tmp_path.glob('.mcptoai-image-*.part'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS atomic quarantine')
@pytest.mark.parametrize('approved,revalidate',[(False,True),(True,False)])
def test_denied_grant_does_not_create_file(tmp_path,approved,revalidate):
    data=real_png()
    target=tmp_path/'picture.png'
    with pytest.raises(PermissionError):
        stage(target,data).commit_atomic_chat_image(approved=approved,revalidate=lambda: revalidate)
    assert not target.exists() and not list(tmp_path.glob('.mcptoai-image-*.part'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS atomic quarantine')
def test_malicious_content_rejected_before_creating_file(tmp_path):
    data=b'MZ'+b'evil binary'
    target=tmp_path/'picture.png'
    with pytest.raises(ValueError):
        stage(target,data).commit_atomic_chat_image(approved=True,revalidate=lambda: True)
    assert not target.exists() and not list(tmp_path.glob('.mcptoai-image-*.part'))
