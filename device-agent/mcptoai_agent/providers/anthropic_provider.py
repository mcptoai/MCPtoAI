"""Anthropic Messages API adapter'ı."""

from __future__ import annotations

from anthropic import AsyncAnthropic

from .base import AssistantTurn, Provider, ToolCall, ToolSpec


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key, model)
        self.client = AsyncAnthropic(api_key=api_key)

    async def list_models(self) -> list[dict]:
        """Discover models available to this Anthropic API key via /v1/models."""
        page = await self.client.models.list(limit=100)
        out = []
        while True:
            for m in page.data:
                out.append({
                    "id": m.id,
                    "name": getattr(m, "display_name", None),
                    "task": "chat",
                    "modalities": ["text"],
                })
            if not getattr(page, "has_more", False):
                break
            last_id = getattr(page, "last_id", None)
            if not last_id:
                break
            page = await self.client.models.list(limit=100, after_id=last_id)
        return out

    @staticmethod
    def _convert(messages: list[dict]) -> list[dict]:
        """Kanonik geçmişi Anthropic formatına çevirir.
        Ardışık tool mesajları tek bir user mesajında tool_result blokları olur."""
        out: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            elif role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                    "is_error": bool(m.get("is_error")),
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> AssistantTurn:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=self._convert(messages),
            tools=[{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools],
        )
        turn = AssistantTurn()
        for block in resp.content:
            if block.type == "text":
                turn.text += block.text
            elif block.type == "tool_use":
                turn.tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})))
        return turn
