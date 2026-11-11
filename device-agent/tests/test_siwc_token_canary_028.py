"""Synthetic credentials only: no actual OS vault, account, or network."""
import io
import logging
import time
from contextlib import nullcontext, redirect_stdout, redirect_stderr
from unittest.mock import patch

import pytest
from mcptoai_agent import siwc_auth

CANARY = 'SIWC_TEST_SECRET_DO_NOT_LOG_028'


def test_status_does_not_disclose_synthetic_credentials():
    record = {'mcptoai_owner_sub':'owner', 'access_token':CANARY,
              'refresh_token':CANARY, 'id_token':CANARY,
              'expires_at':time.time()+3600}
    out, err = io.StringIO(), io.StringIO()
    with patch.object(siwc_auth, 'vault_get', return_value=record), patch.object(siwc_auth, 'paired_owner', return_value='owner'), redirect_stdout(out), redirect_stderr(err):
        result = siwc_auth.status()
    assert result['connected'] is True
    assert CANARY not in repr(result)+out.getvalue()+err.getvalue()


def test_oauth_http_error_never_discloses_synthetic_credentials():
    import urllib.error
    def fail(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, CANARY, {}, io.BytesIO(CANARY.encode()))
    with patch.object(siwc_auth.urllib.request, 'urlopen', side_effect=fail):
        with pytest.raises(RuntimeError) as exc:
            siwc_auth.request_json(siwc_auth.AUTH+'/api/accounts/oauth/token', data={'refresh_token':CANARY})
    assert CANARY not in str(exc.value)


def test_logout_offline_erases_local_record_without_secret_in_result():
    record={'mcptoai_owner_sub':'owner', 'client_id':'issued', 'refresh_token':CANARY}
    deleted=[]
    with patch.object(siwc_auth, 'vault_get', return_value=record), patch.object(siwc_auth, 'paired_owner', return_value='owner'), patch.object(siwc_auth, 'request_json', side_effect=RuntimeError(CANARY)), patch.object(siwc_auth, 'delete_secret', side_effect=deleted.append):
        result=siwc_auth.sign_out()
    assert result == {'disconnected':True, 'revoked':False}
    assert deleted == ['siwc:account']
    assert CANARY not in repr(result)
