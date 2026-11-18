"""Conservative, deterministic prompt assembly; canonical history is never modified.

Model limits must come from trusted provider metadata, never from user content.
Unknown models deliberately use a small bounded fallback, not a character cap.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# Only verified/explicitly configured limits belong here. Unknown models are not
# guessed from model name; a provider may expose context_window_tokens directly.
UNKNOWN_CONTEXT_TOKENS = 128 * 1024
# Provider-family defaults are conservative estimates, not model guarantees.
# Providers can override with a validated context_window_tokens attribute.
UNKNOWN_PROVIDER_CONTEXT_TOKENS = {
    'openai': 128 * 1024,
    'anthropic': 128 * 1024,
    'ollama': 128 * 1024,
}


@dataclass(frozen=True)
class ContextBudget:
    context_tokens: int
    input_tokens: int
    output_reserve: int
    tool_reserve: int
    source: str
    provider_name: str = ''


def resolve_budget(provider: Any, *, tool_count: int = 0) -> ContextBudget:
    advertised = getattr(provider, 'context_window_tokens', None)
    if type(advertised) is int and 4096 <= advertised <= 10_000_000:
        limit, source = advertised, 'provider'
    else:
        limit, source = UNKNOWN_PROVIDER_CONTEXT_TOKENS.get(getattr(provider, 'name', ''), UNKNOWN_CONTEXT_TOKENS), 'conservative_unknown'
    provider_limit = getattr(provider, 'max_input_tokens', None)
    if type(provider_limit) is int and provider_limit > 0:
        limit = min(limit, provider_limit)
    output = min(4096, max(1024, limit // 4))
    # Tool definitions are submitted alongside the prompt, but should not take
    # virtually the entire context of an unknown model. Preserve at least half
    # the context for system instructions, recent turns and safety notices.
    tool = min(limit // 8, max(256, tool_count * 24))
    margin = max(256, limit // 20)
    return ContextBudget(limit, max(512, limit - output - tool - margin), output, tool, source, getattr(provider, 'name', ''))


def estimate_tokens(value: Any, provider: str = '') -> int:
    """Count visible text separately from image patches; never count base64 as text.

    The original structured data is returned to provider adapters unchanged.
    """
    if isinstance(value, dict):
        from .image_token_budget import visual_tokens
        image_cost = 0
        if isinstance(value.get('images'), list):
            image_cost = sum(visual_tokens(img, provider) for img in value['images'][:16])
        return 2 + sum(estimate_tokens(str(key), provider) + estimate_tokens(item, provider) for key, item in value.items() if key != 'images') + image_cost
    if isinstance(value, list):
        return sum(estimate_tokens(item, provider) for item in value) + len(value)
    if isinstance(value, str):
        data = value
    else:
        data = json.dumps(value, ensure_ascii=False, default=str)
    return max(1, len(data.encode('utf-8')) // 2 + 1)


def assemble(system: str, history: list[dict], budget: ContextBudget) -> tuple[str, list[dict], bool]:
    """Keep newest complete messages; never break an assistant/tool-call sequence.

    The caller must not silently claim omitted history is summarized. Older turns
    are omitted from this request only; canonical history remains untouched.
    """
    available = budget.input_tokens - estimate_tokens(system)
    if available <= 0:
        raise ValueError('System instructions exceed the selected model input budget')
    if sum(estimate_tokens(m, budget.provider_name) for m in history) <= available:
        return system, list(history), False
    # Preserve the most recent user request and its tool-call sequence. Each
    # assistant tool call and corresponding tool results form an indivisible unit.
    groups: list[list[dict]] = []
    for message in history:
        if message.get('role') == 'tool' and groups and groups[-1][-1].get('role') in {'assistant', 'tool'}:
            groups[-1].append(message)
        else:
            groups.append([message])
    selected: list[list[dict]] = []
    for group in reversed(groups):
        size = sum(estimate_tokens(m, budget.provider_name) for m in group)
        if size > available:
            break
        selected.append(group)
        available -= size
    if not selected:
        raise ValueError('Latest conversation item exceeds the model input budget')
    retained = [m for group in reversed(selected) for m in group]
    notice = ('\n\n[Context limit: older conversation entries were omitted from this model request. '
              'They remain in canonical history. Do not claim to remember omitted facts or tool results; '
              'request the relevant history or fresh authorized evidence before asserting them.]')
    if estimate_tokens(notice) > available:
        # Reserve for notice by dropping an older group, never the latest one.
        while len(selected) > 1 and estimate_tokens(notice) > available:
            removed = selected.pop()
            available += sum(estimate_tokens(m, budget.provider_name) for m in removed)
        retained = [m for group in reversed(selected) for m in group]
    if estimate_tokens(notice) > available:
        raise ValueError('Insufficient room for safe history truncation notice')
    return system + notice, retained, True


def is_context_exceeded(exc: Exception) -> bool:
    """Match provider context errors only, never auth/rate/network errors."""
    code = getattr(exc, 'code', None)
    if code in {'context_length_exceeded', 'context_window_exceeded'}:
        return True
    body = getattr(exc, 'body', None)
    if isinstance(body, dict):
        error = body.get('error', body)
        if isinstance(error, dict) and error.get('code') in {'context_length_exceeded', 'context_window_exceeded'}:
            return True
    message = str(exc).lower()
    return any(marker in message for marker in (
        'context length exceeded', 'context_length_exceeded',
        'maximum context length', 'context window exceeded',
        'prompt is too long', 'too many tokens', 'exceeds the context window',
    ))


async def complete_with_context_retry(provider: Any, system: str, history: list[dict],
                                      tools: list[Any], *, timeout: int = 600, layers=None):
    """Rebudget on every call and retry context overflow once with half budget."""
    import asyncio
    from dataclasses import replace

    from .context_errors import ContextBudgetError
    budget = resolve_budget(provider, tool_count=len(tools))
    try:
        if layers is None:
            prompt, messages, truncated = assemble(system, history, budget)
        else:
            from .context_layers import select_layered
            prompt, messages, truncated = select_layered(system, history, budget, layers)
    except ValueError as exc:
        raise ContextBudgetError('context_budget_exceeded') from exc
    try:
        return await asyncio.wait_for(provider.complete(prompt, messages, tools), timeout=timeout), truncated
    except Exception as exc:
        if not is_context_exceeded(exc):
            raise
    smaller = replace(budget, input_tokens=max(512, budget.input_tokens // 2))
    try:
        if layers is None:
            prompt, messages, _ = assemble(system, history, smaller)
        else:
            from .context_layers import select_layered
            prompt, messages, _ = select_layered(system, history, smaller, layers)
        return await asyncio.wait_for(provider.complete(prompt, messages, tools), timeout=timeout), True
    except Exception as exc:
        if is_context_exceeded(exc) or isinstance(exc, ValueError):
            raise ContextBudgetError('context_budget_exceeded') from exc
        raise
