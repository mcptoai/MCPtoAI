"""Sağlayıcı fabrikası. API anahtarı her zaman Keychain'den okunur."""

from __future__ import annotations

from ..config import Settings
from ..secret_store import api_key_name, get_secret
from .base import AssistantTurn, Provider, ToolCall, ToolSpec

__all__ = ["AssistantTurn", "Provider", "ToolCall", "ToolSpec", "make_provider"]


def make_provider(cfg: Settings) -> Provider:
    from ..provider_registry import preset,registry
    info=preset(cfg.provider)
    if not info and cfg.provider.startswith("custom-"):
        info=registry(cfg.user_settings.get("custom_providers") or {}).get(cfg.provider)
    if cfg.provider == "anthropic":
        key=get_secret(api_key_name("anthropic"))
        if not key: raise RuntimeError("Anthropic API key is not configured.")
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(key,cfg.model)
    if cfg.provider == "evren":
        key=get_secret(api_key_name("evren"))
        if not key: raise RuntimeError("EVREN API key is not configured.")
        from .evren_provider import EvrenProvider
        return EvrenProvider(key,cfg.model)
    if not info: raise RuntimeError(f"Unknown provider: {cfg.provider}")
    from .openai_provider import OpenAIProvider
    key="local" if not info.get("key",True) else get_secret(api_key_name(cfg.provider))
    if not key: raise RuntimeError(f"{info['name']} API key is not configured.")
    base=cfg.openai_base_url or info.get("base_url")
    if cfg.provider in {"local","custom"} and not base: raise RuntimeError("Provider base URL is required.")
    p=OpenAIProvider(key,cfg.model,base); p.name=cfg.provider; return p
