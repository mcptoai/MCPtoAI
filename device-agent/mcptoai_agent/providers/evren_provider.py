"""EVREN OpenAI-compatible Chat Completions adapter."""
from __future__ import annotations
from .openai_provider import OpenAIProvider
from openai import AsyncOpenAI, InternalServerError, APITimeoutError
from httpx2 import ReadTimeout
import logging
import time
import asyncio

logger = logging.getLogger("mcptoai.evren")

EVREN_BASE_URL = "https://evren-llmapi.ssyz.org.tr/v1"

class EvrenProvider(OpenAIProvider):
    name = "evren"
    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key, model, EVREN_BASE_URL)
        # Fail fast on EVREN 503s; fallback below handles model failover.
        self.client = AsyncOpenAI(api_key=api_key, base_url=EVREN_BASE_URL, max_retries=0, timeout=20.0)
        self.last_model = model
        self._models_cache = []
        self._models_cache_at = 0.0
        # EVREN accepts OpenAI-compatible bearer auth via the OpenAI SDK.

    async def list_models(self) -> list[dict]:
        if self._models_cache and time.monotonic() - self._models_cache_at < 300:
            return self._models_cache
        page = await self.client.models.list()
        out = []
        for m in page.data:
            extra = getattr(m, "model_extra", {}) or {}
            task = extra.get("task")
            if task in {"chat", "vision_chat"}:
                out.append({"id": m.id, "task": task, "modalities": extra.get("modalities") or ["text"]})
        self._models_cache, self._models_cache_at = out, time.monotonic()
        return out

    async def complete(self, system, messages, tools):
        preferred = self.model
        discovered = await self.list_models()
        candidates = [preferred] + [m["id"] for m in discovered if m["id"] != preferred]
        last_exc = None
        for candidate in candidates:
            self.model = candidate
            try:
                turn = None
                for attempt, delay in enumerate((0, 2)):
                    if delay:
                        logger.warning("EVREN timeout retry %s/1 for %s after %ss", attempt, candidate, delay)
                        await asyncio.sleep(delay)
                    try:
                        turn = await super().complete(system, messages, tools)
                        break
                    except (APITimeoutError, ReadTimeout) as exc:
                        last_exc = exc
                        if attempt == 1:
                            raise RuntimeError("EVREN model API did not respond in time. Please retry or select another model.") from None
                self.last_model = candidate
                self.model = preferred
                if candidate != preferred:
                    logger.warning("EVREN fallback: %s -> %s", preferred, candidate)
                return turn
            except InternalServerError as exc:
                last_exc = exc
                if getattr(exc, "status_code", None) != 503:
                    self.model = preferred
                    raise
                logger.warning("EVREN model unavailable (503): %s", candidate)
        self.model = preferred
        raise last_exc or RuntimeError("No EVREN chat model available")
