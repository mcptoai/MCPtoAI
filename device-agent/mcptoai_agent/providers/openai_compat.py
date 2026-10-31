"""Standart dışı OpenAI uyumlu yanıtları güvenli biçimde normalleştir."""

import json
from openai.types.chat import ChatCompletion


def _safe_preview(body: str) -> str:
    """Yanıtta yanlışlıkla bulunan kimlik bilgilerini göstermeden özet üret."""
    import re
    preview = body[:200].replace('\n', ' ').replace('\r', ' ')
    preview = re.sub(r'(?i)(bearer\s+)[^\s,;]+', r'\1[REDACTED]', preview)
    preview = re.sub(r'(?i)(sk-[a-z0-9_-]+|gh[pousr]_[a-z0-9_-]+)', '[REDACTED]', preview)
    return preview


def normalize_completion(response, content_type='unknown') -> ChatCompletion:
    """JSON veya yanlışlıkla SSE olarak gelen tamamlanmış yanıtı ayrıştır."""
    if isinstance(response, ChatCompletion) or (not isinstance(response, str) and hasattr(response, "choices")):
        return response
    if not isinstance(response, str):
        raise ValueError(f'Provider returned an unexpected response (content-type={content_type}): unsupported response type')
    body = response.lstrip('\ufeff \t\r\n')
    if body.startswith('{'):
        try:
            return ChatCompletion.model_validate(json.loads(body))
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Provider returned an unexpected response (content-type={content_type}): invalid JSON') from None
    if body.startswith('data:') or body.startswith('event:') or body.startswith(':'):
        text_parts = []
        tool_parts = {}
        finish_reason = None
        usage = None
        model = ''
        response_id = ''
        created = 0
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                continue
            try:
                chunk = json.loads(payload)
            except (ValueError, TypeError):
                raise ValueError(f'Provider returned an unexpected response (content-type={content_type}): invalid SSE data') from None
            if not isinstance(chunk, dict):
                raise ValueError(f'Provider returned an unexpected response (content-type={content_type}): invalid SSE chunk')
            response_id = chunk.get('id') or response_id
            model = chunk.get('model') or model
            created = chunk.get('created') or created
            usage = chunk.get('usage') or usage
            for choice in chunk.get('choices') or []:
                if choice.get('index', 0) != 0:
                    continue
                delta = choice.get('delta') or {}
                if isinstance(delta.get('content'), str):
                    text_parts.append(delta['content'])
                for call in delta.get('tool_calls') or []:
                    index = call.get('index', 0)
                    item = tool_parts.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                    if call.get('id'):
                        item['id'] = call['id']
                    fn = call.get('function') or {}
                    if fn.get('name'):
                        item['function']['name'] += fn['name']
                    if fn.get('arguments'):
                        item['function']['arguments'] += fn['arguments']
                finish_reason = choice.get('finish_reason') or finish_reason
        if not text_parts and not tool_parts and finish_reason is None:
            raise ValueError(f'Provider returned an unexpected response (content-type={content_type}): empty SSE')
        message = {'role': 'assistant', 'content': ''.join(text_parts)}
        if tool_parts:
            message['tool_calls'] = [tool_parts[i] for i in sorted(tool_parts)]
        result = {'id': response_id or 'compat', 'object': 'chat.completion', 'created': created, 'model': model or 'unknown', 'choices': [{'index': 0, 'message': message, 'finish_reason': finish_reason}]}
        if usage:
            result['usage'] = usage
        return ChatCompletion.model_validate(result)
    raise ValueError(f'Provider returned an unexpected response (content-type={content_type}): {_safe_preview(body)}')
