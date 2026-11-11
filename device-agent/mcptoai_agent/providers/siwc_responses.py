"""SIWC Responses wire-format adapter. No credentials or transport here."""
from __future__ import annotations
import json
from .base import AssistantTurn, ToolCall, ToolSpec


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
        elif kind in ('response.failed','response.incomplete'):
            raise RuntimeError('SIWC response failed or incomplete')
        elif kind=='response.completed':
            completed=True
            break
    if not completed:
        raise RuntimeError('SIWC response ended without completion')
    return AssistantTurn(text=''.join(text_parts),tool_calls=calls)
