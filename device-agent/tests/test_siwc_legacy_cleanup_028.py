from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_auth

LEGACY={'refresh_token':'synthetic','access_token':'synthetic','client_id':'synthetic-client','expires_at':0}

def test_legacy_login_rejected_before_browser():
    with patch.object(siwc_auth,'paired_owner',return_value='owner'),patch.object(siwc_auth,'vault_get',return_value=LEGACY),patch.object(siwc_auth,'webbrowser') as browser:
        with pytest.raises(PermissionError,match='eski bir ChatGPT bağlantısı'):
            siwc_auth.sign_in()
        browser.open.assert_not_called()

def test_legacy_logout_does_not_delete_or_revoke():
    with patch.object(siwc_auth,'vault_get',return_value=LEGACY),patch.object(siwc_auth,'delete_secret') as delete,patch.object(siwc_auth,'request_json') as network:
        with pytest.raises(PermissionError,match='eski bir ChatGPT bağlantısı'):
            siwc_auth.sign_out()
        delete.assert_not_called()
        network.assert_not_called()

def test_clear_local_only_deletes_siwc_account():
    deleted=[]
    with patch.object(siwc_auth,'vault_get',return_value=LEGACY),patch.object(siwc_auth,'request_json',side_effect=RuntimeError('offline')),patch.object(siwc_auth,'delete_secret',side_effect=deleted.append):
        assert siwc_auth.clear_local()=={'disconnected':True,'revoked':False}
    assert deleted==['siwc:account']
