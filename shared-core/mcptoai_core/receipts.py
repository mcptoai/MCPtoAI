"""Pure bounded receipt pruning for relay message deduplication."""
from __future__ import annotations

RECEIPT_TTL_SECONDS = 24 * 60 * 60
MAX_RECEIPTS = 1024


def prune_receipts(items, now, *, ttl=RECEIPT_TTL_SECONDS, maximum=MAX_RECEIPTS):
    """Prune mutable ordered mapping in place; preserve legacy expiry semantics."""
    before = len(items)
    for key in list(items):
        updated = items[key].get('updated_at', 0)
        if not isinstance(updated, (int, float)) or now - float(updated) > ttl:
            items.pop(key, None)
    while len(items) > maximum:
        items.popitem(last=False)
    return len(items) != before
