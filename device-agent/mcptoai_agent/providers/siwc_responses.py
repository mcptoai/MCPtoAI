"""SIWC Responses wire-format adapter. No credentials or transport here."""
from __future__ import annotations
import json
import re
from .base import AssistantTurn, ToolCall, ToolSpec

_SAFE_CODE=re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
_LIMIT_HINTS=('rate_limit','usage_limit','usage','quota','insufficient')


class SiwcResponseError(RuntimeError):
    """Responses akışındaki failed / incomplete / error olayı.

    code: OpenAI hata kodu ya da incomplete nedeni (yalnızca güvenli karakterler).
    detail: ham mesajın kısaltılmış hali; yalnızca cihaz loguna gider, ekranda gösterilmez.
    """

    def __init__(self, kind, code=None, message=None):
        self.kind=kind
        code=str(code) if code is not None else ''
        self.code=code if _SAFE_CODE.match(code) else None
        self.detail=str(message)[:200] if message else ''
        self.status_code=429 if self.is_usage_limit else None
        text=f'SIWC response {kind}'
        if self.code: text+=f': {self.code}'
        if self.detail: text+=f' - {self.detail}'
        super().__init__(text)

    @property
    def is_usage_limit(self):
        code=(self.code or '').lower()
        return any(hint in code for hint in _LIMIT_HINTS)


def to_input(messages: list[dict]) -> list[dict]:
    result=[]
    for msg in messages:
        role=msg.get('role')
        if role=='user':
            if msg.get('images'):
                raise ValueError('SIWC image input is not yet supported')
            result.append({'role':'user','content':str(msg.get('content') or '')})
        elif role=='assistant':
            if msg.get('content'):
                result.append({'role':'assistant','content':str(msg['content'])})
            for call in msg.get('tool_calls') or []:
                result.append({'type':'function_call','call_id':call.id,'name':call.name,
                               'arguments':json.dumps(call.arguments,ensure_ascii=False)})
        elif role=='tool':
            result.append({'type':'function_call_output','call_id':msg['tool_call_id'],
                           'output':str(msg.get('content') or '')})
    return result


def request_payload(model: str, system: str, messages: list[dict], tools: list[ToolSpec]) -> dict:
    payload={'model':model,'instructions':system,'input':to_input(messages),'store':False,'stream':True}
    if tools:
        payload['tools']=[{'type':'function','name':t.name,'description':t.description,
                           'parameters':t.input_schema} for t in tools]
    return payload


def parse_events(lines) -> AssistantTurn:
    """Fail closed unless a completed terminal event is observed."""
    text_parts=[]; calls=[]; completed=False
    for raw in lines:
        line=raw.decode('utf-8','replace') if isinstance(raw,bytes) else str(raw)
        line=line.strip()
        if not line.startswith('data:') or line=='data: [DONE]':
            continue
        try:
            event=json.loads(line[5:].strip())
        except (ValueError,TypeError):
            raise ValueError('Invalid SIWC Responses event') from None
        if not isinstance(event,dict):
            raise ValueError('Invalid SIWC Responses event')
        kind=event.get('type')
        if kind=='response.output_text.delta':
            text_parts.append(str(event.get('delta') or ''))
        elif kind=='response.output_item.done':
            item=event.get('item') or {}
            if item.get('type')=='function_call':
                if not item.get('call_id') or not item.get('name'):
                    raise ValueError('Invalid SIWC function call')
                try:
                    args=json.loads(item.get('arguments') or '{}')
                except ValueError:
                    raise ValueError('Invalid SIWC function arguments') from None
                if not isinstance(args,dict):
                    raise ValueError('Invalid SIWC function arguments')
                calls.append(ToolCall(id=item['call_id'],name=item['name'],arguments=args))
        elif kind=='response.failed':
            error=(event.get('response') or {}).get('error') or {}
            raise SiwcResponseError('failed',error.get('code'),error.get('message'))
        elif kind=='response.incomplete':
            details=(event.get('response') or {}).get('incomplete_details') or {}
            raise SiwcResponseError('incomplete',details.get('reason'))
        elif kind=='error':
            raise SiwcResponseError('failed',event.get('code'),event.get('message'))
        elif kind=='response.completed':
            completed=True
            break
    if not completed:
        raise RuntimeError('SIWC response ended without completion')
    return AssistantTurn(text=''.join(text_parts),tool_calls=calls)
