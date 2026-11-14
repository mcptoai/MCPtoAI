"""Platform-independent decoding of persisted relay state.

Adapters retain filesystem ownership, atomic writes, permissions and retry policy.
"""
from __future__ import annotations

from collections import OrderedDict

from .journal import prune_expired


def load_journal_payload(raw, *, now=None):
    """Read version-one event snapshots; reject unknown versions."""
    data = raw.get('sessions', {}) if isinstance(raw, dict) and raw.get('version') == 1 else {}
    return prune_expired(data, now)


def load_receipt_payload(raw):
    """Restore only string-keyed receipt objects in original insertion order."""
    items = OrderedDict()
    source = raw.get('items') if isinstance(raw, dict) else None
    if isinstance(source, dict):
        for message_id, item in source.items():
            if isinstance(message_id, str) and isinstance(item, dict):
                items[message_id] = dict(item)
    return items


def interrupt_running_receipts(items, now):
    """A process restart must not make a previously running request executable again."""
    changed = False
    for item in items.values():
        if item.get('status') == 'running':
            item['status'] = 'interrupted'
            item['updated_at'] = now
            changed = True
    return changed
