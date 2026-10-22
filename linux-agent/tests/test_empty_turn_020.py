"""Regression tests for provider empty-turn handling (no external API)."""
import asyncio
from dataclasses import replace
from mcptoai_linux.agent import AgentSession
from mcptoai_linux.config import settings
from mcptoai_linux.providers.base import AssistantTurn, Provider
from mcptoai_linux.tools import build_server

class EmptyProvider(Provider):
    name = "empty"
    def __init__(self, reason):
        super().__init__("test", "fake")
        self.reason = reason
    async def complete(self, system, messages, tools):
        return AssistantTurn(text="", stop_reason=self.reason)

def test_empty_turn_not_silent_and_history_remains_valid(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, EmptyProvider("end_turn"), build_server(cfg))
    events = []
    async def emit(e): events.append(e)
    async def approver(*_): raise AssertionError("No tools should run")
    result = asyncio.run(session.run("hi", approver, emit, language="English"))
    assert "empty response" in result
    assert session.history[-1]["role"] == "assistant"
    assert session.history[-1]["content"] == result
    assert [e["type"] for e in events[-2:]] == ["text", "done"]

def test_exhausted_reasoning_budget_not_silent_turkish(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, EmptyProvider("max_tokens"), build_server(cfg))
    events = []
    async def emit(e): events.append(e)
    async def approver(*_): raise AssertionError("No tools should run")
    result = asyncio.run(session.run("merhaba", approver, emit, language="Turkish"))
    assert "çıktı sınırına" in result
    assert events[-1]["type"] == "done"
    assert session.history[-1]["content"] == result

class PartialProvider(Provider):
    name = "partial"
    def __init__(self): super().__init__("test", "fake")
    async def complete(self, system, messages, tools):
        return AssistantTurn(text="Here is a partial answer", stop_reason="max_tokens")

def test_partial_answer_truncation_is_visible(tmp_path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, PartialProvider(), build_server(cfg))
    events = []
    async def emit(e): events.append(e)
    async def deny(*_): raise AssertionError("No tools expected")
    result = asyncio.run(session.run("Explain", deny, emit, language="English"))
    assert "Here is a partial answer" in result
    assert "cut off" in result
    assert session.history[-1]["content"] == result
    assert events[-2]["text"] == result

def test_anthropic_uses_16000_output_tokens():
    from types import SimpleNamespace
    from mcptoai_linux.providers.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider.model = "fake-model"
    class FakeMessages:
        async def create(self, **kwargs):
            assert kwargs["max_tokens"] == 16000
            return SimpleNamespace(stop_reason="max_tokens", content=[SimpleNamespace(type="text", text="partial")])
    provider.client = SimpleNamespace(messages=FakeMessages())
    turn = asyncio.run(provider.complete("system", [{"role":"user","content":"test"}], []))
    assert turn.text == "partial"
    assert turn.stop_reason == "max_tokens"
