"""OpenAI'nin çıktı sınırı (finish_reason=length) 'max_tokens' olarak aktarılır: boş turda kullanıcı nedeni görür (Anthropic eşi test_empty_turn_020'de)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mcptoai_linux.providers.openai_provider import OpenAIProvider


@pytest.mark.parametrize("finish, expected", [("length", "max_tokens"), ("stop", "stop"), ("tool_calls", "tool_calls"), (None, "")])
def test_finish_reason_is_mapped(finish, expected):
    message = SimpleNamespace(content="", tool_calls=None)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)])
    provider = OpenAIProvider("k", "m")
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response))))
    turn = asyncio.run(provider.complete("sys", [{"role": "user", "content": "x"}], []))
    assert turn.stop_reason == expected
