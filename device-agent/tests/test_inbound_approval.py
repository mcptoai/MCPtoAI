import hashlib
import pytest
from unittest.mock import patch
from mcptoai_agent.inbound_session import InboundSession
from mcptoai_agent.inbound_approval import InboundApproval


def session(tmp_path):
    return InboundSession(transfer_id='tid',name='a.pdf',size=3,sha256=hashlib.sha256(b'abc').hexdigest(),workspace=str(tmp_path),allowed_roots=[tmp_path])


def test_local_grant_consumed_once(tmp_path):
    s=session(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('auth0|real','device-real')):
        a=InboundApproval()
        grant=a.request(s,prompt=lambda request,preview: True)
        assert a.consume(s,grant)
        assert not a.consume(s,grant)
    s.close()


def test_changed_identity_and_denial(tmp_path):
    s=session(tmp_path)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('auth0|real','device-real')):
        a=InboundApproval()
        with pytest.raises(PermissionError): a.request(s,prompt=lambda request,preview: False)
        grant=a.request(s,prompt=lambda request,preview: True)
    with patch('mcptoai_agent.inbound_approval.paired_identity',return_value=('auth0|other','device-real')):
        assert not a.consume(s,grant)
    s.close()


def test_cli_is_disabled_by_default(monkeypatch):
    from mcptoai_agent.inbound_approval import local_cli_prompt
    monkeypatch.delenv('MCPTOAI_INBOUND_UPLOAD_CLI',raising=False)
    assert not local_cli_prompt(None,'preview')


def test_desktop_unavailable_fails_closed(monkeypatch):
    from mcptoai_agent.inbound_approval import local_desktop_prompt, desktop_approval_available
    monkeypatch.setattr('mcptoai_agent.inbound_approval.sys.platform','darwin')
    monkeypatch.setattr('mcptoai_agent.inbound_approval.desktop_socket_path',lambda: __import__('pathlib').Path('/nonexistent/mcptoai-upload.sock'))
    assert not desktop_approval_available()
    assert not local_desktop_prompt(None,'preview',transfer_id='00000000-0000-4000-8000-000000000001')
