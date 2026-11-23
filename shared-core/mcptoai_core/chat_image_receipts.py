"""Device-local, short-lived proof of explicitly approved chat image saves.

Only the inbound Agent creates receipts after a trusted native approval AND a
verified, quarantined, complete device write. Browser/model supplied paths or
boolean approvals never enter this store. No durable history or byte storage.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import time
import uuid

IMAGE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.webp'})
MAX_IMAGES = 4
TTL_SECONDS = 120


def _uuid(s):
    if not isinstance(s, str) or str(uuid.UUID(s)) != s:
        raise ValueError('invalid_saved_image_id')
    return s


class SavedChatImageReceipts:
    def __init__(self, *, clock=time.monotonic):
        self._items = {}
        self._clock = clock

    def clear(self):
        self._items.clear()

    def expire(self):
        now = self._clock()
        for tid, entry in tuple(self._items.items()):
            if entry['expires'] <= now:
                self._items.pop(tid, None)

    def add(self, *, transfer_id, session_id, turn_id, path, sha256, paired_identity):
        self.expire()
        tid, sid, turn = _uuid(transfer_id), _uuid(session_id), _uuid(turn_id)
        if tid in self._items:
            raise PermissionError('saved_image_replay')
        p = Path(path)
        if not p.is_absolute() or p.is_symlink() or p.suffix.lower() not in IMAGE_SUFFIXES:
            raise PermissionError('saved_image_bad_path')
        if not isinstance(paired_identity, tuple) or len(paired_identity) != 2 or not all(paired_identity):
            raise PermissionError('saved_image_identity_invalid')
        if not isinstance(sha256, str) or len(sha256) != 64 or any(ch not in '0123456789abcdef' for ch in sha256):
            raise ValueError('saved_image_digest_invalid')
        if sum((item['session_id'], item['turn_id']) == (sid, turn) for item in self._items.values()) >= MAX_IMAGES:
            raise PermissionError('saved_image_turn_limit')
        self._items[tid] = dict(session_id=sid, turn_id=turn, path=str(p), sha256=sha256,
                                identity=paired_identity, expires=self._clock() + TTL_SECONDS)

    def consume(self, ids, *, session_id, turn_id, paired_identity, allowed_roots):
        self.expire()
        sid, turn = _uuid(session_id), _uuid(turn_id)
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_IMAGES or len(set(map(str, ids))) != len(ids):
            raise PermissionError('saved_image_ids_invalid')
        paths = []
        seen = []
        try:
            roots = {Path(root).resolve(strict=True) for root in allowed_roots if Path(root).is_dir()}
            for raw in ids:
                tid = _uuid(raw)
                entry = self._items.get(tid)
                if entry is None:
                    raise PermissionError('saved_image_receipt_missing')
                seen.append(tid)
                if ((entry['session_id'], entry['turn_id']) != (sid, turn)
                        or entry['identity'] != paired_identity):
                    raise PermissionError('saved_image_cross_turn_or_device')
                path = Path(entry['path'])
                if path.is_symlink() or path.suffix.lower() not in IMAGE_SUFFIXES:
                    raise PermissionError('saved_image_path_changed')
                parent = path.parent.resolve(strict=True)
                if parent not in roots and not any(parent.is_relative_to(root) for root in roots):
                    raise PermissionError('saved_image_outside_workspace')
                if not path.is_file() or path.resolve(strict=True) != path:
                    raise PermissionError('saved_image_path_changed')
                h = hashlib.sha256()
                with path.open('rb') as f:
                    for part in iter(lambda: f.read(128 * 1024), b''):
                        h.update(part)
                if h.hexdigest() != entry['sha256']:
                    raise PermissionError('saved_image_content_changed')
                paths.append(str(path))
            return paths
        finally:
            # One-use even on a partial failure: never silently retry a stale
            # or conflicting receipt. Other turns retain independent grants.
            for tid in seen:
                self._items.pop(tid, None)


def needs_saved_image_tool_confirmation(arguments, saved_paths):
    """Narrow an existing tool permission, never expand it.

    If model-supplied tool arguments refer to a current-turn saved image,
    require a fresh per-call approval even if read_file/image_preview was
    previously set to AUTO. Shell and remote tool payloads are included.
    """
    if not saved_paths or not isinstance(arguments, dict):
        return False
    def refers(value):
        if isinstance(value, str):
            return any(path in value for path in saved_paths if isinstance(path, str) and path)
        if isinstance(value, (tuple, list)):
            return any(refers(v) for v in value)
        if isinstance(value, dict):
            return any(refers(v) for v in value.values())
        return False
    return refers(arguments)
