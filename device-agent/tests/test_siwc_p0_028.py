"""SIWC P0: no plan-sharing permission, refresh identity and rotation recovery."""
from contextlib import nullcontext
from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_auth


def test_no_sharing_scope_blocks_model_token_before_network():
    record={'mcptoai_owner_sub':'owner','access_token':'canary','expires_at':9999999999,'scopes':[]}
    with patch.object(siwc_auth,'vault_get',return_value=record), patch.object(siwc_auth,'paired_owner',return_value='owner'),patch.object(siwc_auth,'request_json') as network:
        with pytest.raises(PermissionError,match='Plan kullanımı izni verilmedi'):
            siwc_auth.access_token()
        network.assert_not_called()
        assert siwc_auth.status()['reason']=='plan_permission_missing'
        assert not siwc_auth.status()['sharing']


def test_refresh_verifies_rotated_id_token_and_preserves_pending_on_jwks_failure():
    record={'mcptoai_owner_sub':'owner','client_id':'client','subject':'subject','access_token':'old','refresh_token':'old-refresh','id_token':'old-id','scopes':[siwc_auth.SHARING_SCOPE],'expires_at':0}
    store={'account':record}
    rotated={'access_token':'new','refresh_token':'new-refresh','id_token':'new-id','expires_in':3600}
    with patch.object(siwc_auth,'paired_owner',return_value='owner'),patch.object(siwc_auth,'credential_lock',return_value=nullcontext()),patch.object(siwc_auth,'vault_get',side_effect=store.get),patch.object(siwc_auth,'vault_put',side_effect=store.__setitem__),patch.object(siwc_auth,'request_json',return_value=rotated) as request,patch.object(siwc_auth,'verify_identity',side_effect=[RuntimeError('JWKS offline'),{'sub':'subject'}]) as verify:
        with pytest.raises(RuntimeError,match='JWKS offline'):
            siwc_auth.refresh()
        assert store['account']['pending_refresh']['refresh_token']=='new-refresh'
        assert siwc_auth.refresh()=='new'
        assert store['account']['refresh_token']=='new-refresh'
        assert 'pending_refresh' not in store['account']
        assert request.call_count==1
        assert verify.call_count==2
