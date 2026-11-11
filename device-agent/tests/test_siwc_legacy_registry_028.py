import json
from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_auth, siwc_gate


def test_preview_off_no_owner_or_vault_access():
    with patch.object(siwc_gate, 'local_permission', return_value=False), patch.object(siwc_auth, 'assert_owner', side_effect=AssertionError('vault accessed')):
        with pytest.raises(PermissionError, match='Preview is off'):
            siwc_gate.enforce(origin='desktop-local', user_initiated=True)


def test_legacy_status_is_read_only():
    with patch.object(siwc_auth, 'vault_get', return_value={'refresh_token':'fake','expires_at':123}), patch.object(siwc_auth, 'paired_owner', side_effect=AssertionError('owner should not be queried')):
        result=siwc_auth.status()
    assert result['reason']=='legacy_token' and not result['linked'] and not result['connected']


def test_owner_mismatch_status_and_access_denied():
    record={'mcptoai_owner_sub':'owner-A','access_token':'synthetic','expires_at':9999999999}
    with patch.object(siwc_auth, 'vault_get', return_value=record), patch.object(siwc_auth, 'paired_owner', return_value='owner-B'):
        assert siwc_auth.status()['reason']=='owner_mismatch'
        with pytest.raises(PermissionError):
            siwc_auth.access_token()


def test_cleanup_attempts_revoke_and_always_deletes():
    record={'refresh_token':'synthetic','client_id':'test'}
    calls=[]
    def revoke_request(url, **kwargs):
        if url.endswith('/.well-known/openid-configuration'):
            return {'revocation_endpoint':siwc_auth.AUTH+'/oauth/revoke'}
        raise RuntimeError('offline')
    with patch.object(siwc_auth, 'vault_get', return_value=record), patch.object(siwc_auth, 'request_json', side_effect=revoke_request) as req, patch.object(siwc_auth, 'delete_secret', side_effect=lambda key:calls.append(key)):
        result=siwc_auth.cleanup_unlinked()
    assert req.call_count==2 and calls==['siwc:account'] and result=={'disconnected':True,'revoked':False}


def test_cleanup_rejects_linked_record():
    record={'mcptoai_owner_sub':'owner-A','refresh_token':'synthetic'}
    with patch.object(siwc_auth, 'vault_get', return_value=record), patch.object(siwc_auth, 'paired_owner', return_value='owner-A'), patch.object(siwc_auth, 'delete_secret') as delete:
        with pytest.raises(PermissionError):siwc_auth.cleanup_unlinked()
        delete.assert_not_called()


def _registry_cli(monkeypatch, capsys, enabled, record):
    import sys
    from mcptoai_agent import __main__ as cli
    from mcptoai_agent import config
    from mcptoai_agent import secret_store
    monkeypatch.setattr(sys, 'argv', ['mcptoai-agent', 'provider-registry'])
    monkeypatch.setattr(config, 'local_permission', lambda name: enabled)
    monkeypatch.setattr(cli, 'get_secret', lambda name: None)
    with patch.object(siwc_auth, 'vault_get', return_value=record), patch.object(siwc_auth, 'paired_owner', return_value='owner-B'):
        cli.main()
    return json.loads(capsys.readouterr().out)


def test_registry_off_never_touches_siwc(monkeypatch, capsys):
    with patch.object(siwc_auth, 'status', side_effect=AssertionError('SIWC accessed')), patch.object(siwc_auth, 'vault_get', side_effect=AssertionError('vault accessed')):
        result = _registry_cli(monkeypatch, capsys, False, None)
    assert 'openai' in result and 'anthropic' in result and 'chatgpt' in result
    assert result['chatgpt']['reason']=='preview_disabled'


def test_registry_legacy_only_affects_chatgpt(monkeypatch, capsys):
    result=_registry_cli(monkeypatch,capsys,True,{'refresh_token':'synthetic'})
    assert result['chatgpt']['reason']=='legacy_token'
    assert result['chatgpt']['linked'] is False
    assert 'openai' in result and 'anthropic' in result


def test_registry_provider_error_is_isolated(monkeypatch,capsys):
    with patch.object(siwc_auth,'status',side_effect=RuntimeError('synthetic status error')):
        result=_registry_cli(monkeypatch,capsys,True,None)
    assert result['chatgpt']['error']=='Provider status unavailable'
    assert 'openai' in result and 'anthropic' in result
