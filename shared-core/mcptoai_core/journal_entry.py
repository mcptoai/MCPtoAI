"""Shared allowlist for persisted replay event records.

Never persist tool arguments, credentials or actionable approval futures.
"""
from __future__ import annotations


def safe_journal_event(event):
    typ = event.get('type')
    if typ not in ('text', 'done', 'error', 'approval_required', 'approval_resolved'):
        return None
    if typ == 'text':
        return {'type': 'text', 'text': str(event.get('text') or '')[:100000],
                'model': str(event.get('model') or '')[:160]}
    if typ == 'error':
        return {'type': 'error', 'message': str(event.get('message') or '')[:2000]}
    if typ == 'approval_required':
        return {'type': 'approval_interrupted',
                'approval_id': str(event.get('approval_id') or ''),
                'tool': str(event.get('tool') or '')[:160]}
    if typ == 'approval_resolved':
        return {'type': 'approval_resolved',
                'approval_id': str(event.get('approval_id') or ''),
                'status': str(event.get('status') or '')}
    return {'type': 'done', 'model': str(event.get('model') or '')[:160]}
