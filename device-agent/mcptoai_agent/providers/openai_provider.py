"""OpenAI Chat Completions adapter'ı. base_url ile Ollama gibi OpenAI-uyumlu
uç noktalar da kullanılabilir."""

from __future__ import annotations

import json
from pathlib import Path
from openai import NotFoundError, BadRequestError, APIStatusError
from ..paths import config_dir

from openai import AsyncOpenAI

from .base import AssistantTurn, Provider, ToolCall, ToolSpec


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        super().__init__(api_key, model)
        self.base_url = (base_url or "").rstrip("/")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    @property
    def _is_nvidia(self) -> bool:
        return self.base_url == "https://integrate.api.nvidia.com/v1"

    @staticmethod
    def _nvidia_unavailable_path() -> Path:
        return config_dir() / "nvidia-unavailable-models.json"

    @classmethod
    def _nvidia_unavailable(cls) -> set[str]:
        try:
            data=json.loads(cls._nvidia_unavailable_path().read_text())
            return {str(x) for x in data if isinstance(x,str)} if isinstance(data,list) else set()
        except (FileNotFoundError,json.JSONDecodeError,OSError):
            return set()

    @classmethod
    def _mark_nvidia_unavailable(cls, model: str) -> None:
        items=cls._nvidia_unavailable(); items.add(model)
        path=cls._nvidia_unavailable_path(); path.parent.mkdir(parents=True,exist_ok=True)
        tmp=path.with_suffix(".tmp"); tmp.write_text(json.dumps(sorted(items))); tmp.chmod(0o600); tmp.replace(path)

    async def list_models(self) -> list[dict]:
        page = await self.client.models.list()
        blocked=self._nvidia_unavailable() if self._is_nvidia else set()
        def chat_candidate(model_id: str) -> bool:
            if not self._is_nvidia:
                return True
            # NVIDIA /models mixes chat, embedding, safety, parsing, reward and detector endpoints.
            non_chat = ("embed", "retriever", "safety", "guard", "reward", "detector", "nvclip", "deplot", "nemotron-parse")
            return not any(token in model_id.lower() for token in non_chat)
        return [{"id": m.id, "task": getattr(m, "task", None), "modalities": getattr(m, "modalities", None)} for m in page.data if m.id not in blocked and chat_candidate(m.id)]

    @staticmethod
    def _convert(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                content = m["content"]
                if m.get("images"):
                    content = [{"type":"text","text":content}] + [
                        {"type":"image_url","image_url":{"url":img["data_url"]}} for img in m["images"]
                    ]
                out.append({"role": "user", "content": content})
            elif role == "assistant":
                msg: dict = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> AssistantTurn:
        try:
            kwargs = {
                "model": self.model,
                "messages": self._convert(system, messages),
            }
            if tools:
                kwargs["tools"] = [
                    {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                    for t in tools
                ]
            resp = await self.client.chat.completions.create(**kwargs)
        except NotFoundError as exc:
            detail=str(exc)
            if self._is_nvidia and "Function '" in detail and "Not found for account" in detail:
                self._mark_nvidia_unavailable(self.model)
                raise RuntimeError("This NVIDIA model is not available for your account. Please select another model.") from None
            raise
        except BadRequestError as exc:
            detail=str(exc)
            if self._is_nvidia and "Expected exactly one message" in detail:
                self._mark_nvidia_unavailable(self.model)
                raise RuntimeError("This NVIDIA endpoint is not a compatible chat model. Please select another model.") from None
            raise
        except APIStatusError as exc:
            if self._is_nvidia and getattr(exc, "status_code", None) == 410:
                self._mark_nvidia_unavailable(self.model)
                raise RuntimeError("This NVIDIA model has been retired and is no longer available.") from None
            raise
        choice = resp.choices[0].message
        turn = AssistantTurn(text=choice.content or "")
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            turn.tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return turn
