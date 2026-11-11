"""Web SIWC policy must block token/network before model calls."""
import asyncio
from unittest.mock import AsyncMock,patch
import pytest
from mcptoai_agent.providers.siwc_provider import SIWCProvider
from mcptoai_agent import siwc_gate


def test_web_provider_requires_preflight_before_token_or_network():
    supplier=AsyncMock(return_value='fake-token')
    client=AsyncMock()
    provider=SIWCProvider('gpt-test',supplier,client=client,origin='web-relay',user_initiated=True,web_authorized=False)
    async def run():
        with pytest.raises(PermissionError):
            await provider.complete('system',[{'role':'user','content':'hi'}],[])
    asyncio.run(run())
    supplier.assert_not_awaited()
    client.stream.assert_not_called()


def test_authorized_web_provider_reaches_supplier_only_after_gate():
    supplier=AsyncMock(return_value='fake-token')
    provider=SIWCProvider('gpt-test',supplier,origin='web-relay',user_initiated=True,web_authorized=True)
    with patch.object(siwc_gate,'enforce',side_effect=PermissionError('blocked')):
        async def run():
            with pytest.raises(PermissionError,match='blocked'):
                await provider.complete('system',[],[])
        asyncio.run(run())
    supplier.assert_not_awaited()
