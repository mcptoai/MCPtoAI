import time
from contextlib import nullcontext
from unittest.mock import patch
from mcptoai_agent import siwc_auth


def test_second_refresh_uses_rotated_token_without_network():
    record={'mcptoai_owner_sub':'owner','refresh_token':'rotated','access_token':'fresh','expires_at':time.time()+3600}
    with patch.object(siwc_auth,'credential_lock',return_value=nullcontext()), patch.object(siwc_auth,'vault_get',return_value=record), patch.object(siwc_auth,'assert_owner',return_value='owner'), patch.object(siwc_auth,'request_json') as request:
        assert siwc_auth.refresh(expected_refresh_token='stale')=='fresh'
        request.assert_not_called()


def test_stale_expired_token_does_not_bypass_refresh():
    record={'mcptoai_owner_sub':'owner','client_id':'issued','refresh_token':'rotated','access_token':'expired','expires_at':0,'scopes':['chatgpt.tokens.use.direct']}
    with patch.object(siwc_auth,'credential_lock',return_value=nullcontext()), patch.object(siwc_auth,'vault_get',return_value=record), patch.object(siwc_auth,'vault_put'), patch.object(siwc_auth,'assert_owner',return_value='owner'), patch.object(siwc_auth,'request_json',return_value={'access_token':'new','refresh_token':'new-refresh','expires_in':3600}) as request:
        assert siwc_auth.refresh(expected_refresh_token='stale')=='new'
        request.assert_called_once()
