"""Small device-local reliability ledger for relay message deduplication.

Only request identifiers and status metadata are persisted. Conversation text, tool
arguments, tool results and credentials are deliberately not written here.
"""
from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from pathlib import Path

from .paths import config_dir

from mcptoai_core.receipts import prune_receipts as _prune_receipts

from mcptoai_core.persistence import (load_receipt_payload as _load_receipt_payload,
    interrupt_running_receipts as _interrupt_running_receipts)

RECEIPT_TTL_SECONDS = 24 * 60 * 60
MAX_RECEIPTS = 1024


class MessageReceiptStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else config_dir() / "relay-receipts.json"
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = _load_receipt_payload(raw)
        except FileNotFoundError:
            pass
        except Exception:
            # Reliability metadata must never prevent the agent from starting.
            self._items.clear()
        now = time.time()
        changed = _interrupt_running_receipts(self._items, now)
        changed = self._prune(now) or changed
        if changed:
            self._save()

    def _prune(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return _prune_receipts(self._items, now, ttl=RECEIPT_TTL_SECONDS, maximum=MAX_RECEIPTS)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "items": self._items}
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def claim(self, message_id: str, session_id: str) -> tuple[bool, str | None]:
        """Claim a request id.

        Returns (True, None) for a new request. For a duplicate, returns
        (False, prior_status) and never changes it back to running.
        """
        now = time.time()
        self._prune(now)
        existing = self._items.get(message_id)
        if existing is not None:
            self._items.move_to_end(message_id)
            return False, str(existing.get("status") or "unknown")
        self._items[message_id] = {
            "session_id": session_id,
            "status": "running",
            "created_at": now,
            "updated_at": now,
        }
        self._prune(now)
        self._save()
        return True, None

    def finish(self, message_id: str, status: str = "completed") -> None:
        item = self._items.get(message_id)
        if item is None:
            return
        item["status"] = status
        item["updated_at"] = time.time()
        self._items.move_to_end(message_id)
        self._prune()
        self._save()

    def status(self, message_id: str) -> str | None:
        item = self._items.get(message_id)
        return None if item is None else str(item.get("status") or "unknown")
