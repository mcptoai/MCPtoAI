"""Owner switching must not expose or revoke another user's synthetic SIWC tokens."""
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from mcptoai_agent import siwc_auth
from mcptoai_agent.providers.siwc_provider import SIWCProvider

RECORD = {'mcptoai_owner_sub':'owner-a', 'client_id':'fake', 'access_token':'fake-access', 'refresh_token':'fake-refresh', 'expires_at':0, 'scopes':[]}


def test_owner_switch_denies_access_and_refresh_before_network():
    with patch.object(siwc_auth, 'vault_get', return_value=dict(RECORD)), patch.object(siwc_auth, 'paired_owner', return_value='owner-b'), patch.object(siwc_auth, 'request_json') as network:
        with pytest.raises(PermissionError): siwc_auth.access_token()
        with pytest.raises(PermissionError): siwc_auth.refresh()
        network.assert_not_called()


def test_owner_switch_does_not_revoke_or_delete_other_account():
    with patch.object(siwc_auth, 'vault_get', return_value=dict(RECORD)), patch.object(siwc_auth, 'paired_owner', return_value='owner-b'), patch.object(siwc_auth, 'request_json') as network, patch.object(siwc_auth, 'delete_secret') as delete:
        with pytest.raises(PermissionError): siwc_auth.sign_out()
        network.assert_not_called()
        delete.assert_not_called()


def test_owner_switch_denied_before_provider_token_supplier():
    supplier = AsyncMock(return_value='fake-access')
    provider = SIWCProvider('fake-model', supplier, origin='desktop-local', user_initiated=True)
    with patch.object(siwc_auth, 'vault_get', return_value=dict(RECORD)), patch.object(siwc_auth, 'paired_owner', return_value='owner-b'):
        with pytest.raises(PermissionError): asyncio.run(provider.complete('system', [], []))
    supplier.assert_not_awaited()
