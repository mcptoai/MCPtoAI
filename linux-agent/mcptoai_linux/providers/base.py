"""Sağlayıcıdan bağımsız ortak tipler.

Kanonik mesaj formatı (tüm adapter'lar bundan kendi formatına çevirir):
    {"role": "user", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}

Araç tanımları MCP'nin kendi şemasıdır (name, description, inputSchema);
ayrı bir MCPtoAI formatı icat edilmez.
"""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass, field
from typing import Any


_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>", re.IGNORECASE)

def strip_hidden_reasoning(text: str) -> str:
    value=str(text or "")
    previous=None
    while value != previous:
        previous=value
        value=_THINK_BLOCK_RE.sub("",value)
    m=_THINK_OPEN_RE.search(value)
    if m:
        value=value[:m.start()]
    return value.strip()

@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class Provider(abc.ABC):
    name: str

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def list_models(self) -> list[dict]:
        """Return models actually advertised by the provider. Never invent a fallback model."""
        raise NotImplementedError(f"Automatic model discovery is not supported by {self.name}")

    @abc.abstractmethod
    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> AssistantTurn:
        """Bir model turu çalıştırır ve normalize edilmiş sonucu döndürür."""
