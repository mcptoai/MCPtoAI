"""Relay SIWC is denied before any provider, skill or token processing."""
import asyncio
from unittest.mock import AsyncMock, patch
from mcptoai_agent.config import Settings
from mcptoai_agent.relay_client import RelayClient
from mcptoai_agent.siwc_gate import WEB_DENIAL


def test_relay_chatgpt_denied_before_provider_or_skills():
    client = RelayClient(Settings(provider='openai'))
    client._send_event = AsyncMock()
    with patch.object(client, '_chat_provider_cfg') as provider, patch('mcptoai_agent.relay_client.build_server') as skills:
        asyncio.run(client._run_message({'type':'message','session_id':'session-a','message':'load_skill', 'provider':'chatgpt'}))
        provider.assert_not_called()
        skills.assert_not_called()
    assert client.sessions == {}
    assert client._send_event.await_args.args[1]['message'] == WEB_DENIAL


def test_relay_default_chatgpt_denied_even_if_provider_omitted():
    client = RelayClient(Settings(provider='chatgpt'))
    client._send_event = AsyncMock()
    with patch.object(client, '_chat_provider_cfg') as provider:
        asyncio.run(client._run_message({'type':'message','session_id':'session-b','message':'hello'}))
        provider.assert_not_called()
    assert client._send_event.await_args.args[1]['message'] == WEB_DENIAL
