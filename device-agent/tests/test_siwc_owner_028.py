import asyncio
from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_auth, siwc_gate
from mcptoai_agent.providers.siwc_provider import SIWCProvider


def test_missing_device_owner_fails_closed():
    with patch('mcptoai_agent.auth._auth_bundle', return_value={}):
        with pytest.raises(PermissionError, match='MCPtoAI account'):
            siwc_auth.paired_owner()


@pytest.mark.parametrize('record', [None, {}, {'mcptoai_owner_sub':'auth0|other'}])
def test_missing_or_different_binding_rejected(record):
    with patch.object(siwc_auth, 'paired_owner', return_value='auth0|correct'):
        with pytest.raises(PermissionError):
            siwc_auth.assert_owner(record)


def test_matching_binding_accepted():
    with patch.object(siwc_auth, 'paired_owner', return_value='auth0|correct'):
        assert siwc_auth.assert_owner({'mcptoai_owner_sub':'auth0|correct'}) == 'auth0|correct'


def test_mismatch_rejected_before_token_supplier():
    accessed=[]
    async def supplier():
        accessed.append(True)
        return 'secret'
    p=SIWCProvider('test', supplier, origin='desktop-local', user_initiated=True)
    with patch.object(siwc_gate, 'local_permission', return_value=True), patch.object(siwc_auth, 'paired_owner', return_value='auth0|different'), patch.object(siwc_auth, 'vault_get', return_value={'mcptoai_owner_sub':'auth0|owner'}):
        with pytest.raises(PermissionError, match='another MCPtoAI user'):
            asyncio.run(p.complete('', [], []))
    assert accessed == []
