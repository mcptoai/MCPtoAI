import asyncio
from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_gate
from mcptoai_agent import siwc_auth

@pytest.fixture(autouse=True)
def owner_fixture():
    with patch.object(siwc_auth, "assert_owner", return_value="auth0|owner"):
        yield
from mcptoai_agent.providers.siwc_provider import SIWCProvider


def test_web_never_enabled():
    with patch.object(siwc_gate, 'local_permission', return_value=True):
        for origin in ('relay', 'web', 'unknown', ''):
            with pytest.raises(PermissionError, match='web plan usage is disabled'):
                siwc_gate.enforce(origin=origin, user_initiated=True)


def test_preview_defaults_off_and_requires_user_turn():
    with patch.object(siwc_gate, 'local_permission', return_value=False):
        with pytest.raises(PermissionError, match='Preview is off'):
            siwc_gate.enforce(origin='desktop-local', user_initiated=True)
    with patch.object(siwc_gate, 'local_permission', return_value=True):
        with pytest.raises(PermissionError, match='user-initiated'):
            siwc_gate.enforce(origin='desktop-local', user_initiated=False)
        siwc_gate.enforce(origin='desktop-local', user_initiated=True)


def test_guard_prevents_token_access_and_network():
    touched=[]
    async def supplier():
        touched.append('token')
        return 'secret'
    provider=SIWCProvider('test', supplier, origin='relay', user_initiated=True)
    with patch.object(siwc_gate, 'local_permission', return_value=True):
        with pytest.raises(PermissionError, match='web plan usage is disabled'):
            asyncio.run(provider.complete('', [], []))
    assert touched == []
