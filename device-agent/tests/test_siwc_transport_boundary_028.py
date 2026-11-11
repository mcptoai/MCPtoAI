"""Synthetic SIWC transport tests; no OAuth, real token or external network."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcptoai_agent.providers.siwc_provider import SIWCProvider
from mcptoai_agent.siwc_gate import WEB_DENIAL

CANARY = 'SIWC_TRANSPORT_CANARY_NEVER_REAL_028'


def test_relay_denied_before_token_supplier_and_network():
    supplier = AsyncMock(return_value=CANARY)
    client = AsyncMock()
    provider = SIWCProvider('fake-model', supplier, client=client, origin='relay', user_initiated=True)
    with pytest.raises(PermissionError, match='web plan usage is disabled'):
        asyncio.run(provider.complete('system', [{'role':'user','content':'test'}], []))
    supplier.assert_not_awaited()
    client.stream.assert_not_called()


def test_automated_desktop_turn_denied_before_token_supplier():
    supplier = AsyncMock(return_value=CANARY)
    client = AsyncMock()
    provider = SIWCProvider('fake-model', supplier, client=client, origin='desktop-local', user_initiated=False)
    with pytest.raises(PermissionError, match='user-initiated'):
        asyncio.run(provider.complete('system', [{'role':'user','content':'test'}], []))
    supplier.assert_not_awaited()
    client.stream.assert_not_called()


def test_preview_disabled_denied_before_token_supplier():
    supplier = AsyncMock(return_value=CANARY)
    client = AsyncMock()
    provider = SIWCProvider('fake-model', supplier, client=client, origin='desktop-local', user_initiated=True)
    with patch('mcptoai_agent.siwc_auth.assert_owner'), patch('mcptoai_agent.siwc_gate.local_permission', return_value=False):
        with pytest.raises(PermissionError, match='Preview is off'):
            asyncio.run(provider.complete('system', [{'role':'user','content':'test'}], []))
    supplier.assert_not_awaited()
    client.stream.assert_not_called()


def test_relay_denial_does_not_include_canary():
    provider = SIWCProvider('fake-model', AsyncMock(return_value=CANARY), origin='relay', user_initiated=True)
    with pytest.raises(PermissionError) as exc:
        asyncio.run(provider.complete('system', [], []))
    assert str(exc.value) == WEB_DENIAL
    assert CANARY not in str(exc.value)
