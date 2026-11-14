"""Bounded replay journal pruning shared by Linux and Desktop.

This module intentionally does not know about filesystem paths, secrets,
platform lifecycle, or persistence implementations.
"""
from __future__ import annotations

import time

JOURNAL_TTL_SECONDS = 24 * 60 * 60


def prune_expired(data, now=None):
    now = time.time() if now is None else now
    if not isinstance(data, dict):
        return {}
    result = {}
    for sid, entries in data.items():
        if not isinstance(sid, str) or not isinstance(entries, list):
            continue
        kept = [e for e in entries if isinstance(e, dict)
                and isinstance(e.get('recorded_at'), (int, float))
                and not isinstance(e.get('recorded_at'), bool)
                and now - JOURNAL_TTL_SECONDS <= e['recorded_at'] <= now + 60]
        if kept:
            result[sid] = kept[-250:]
    return dict(list(result.items())[-50:])
