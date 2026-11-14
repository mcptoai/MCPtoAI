"""Araç çağrılarından aktivite olayları üretir (tek olay üreticisi).

- Bütün aşamalar (requested, approval_pending, approved/denied, started, sonuç) yalnızca
  cihazdaki SQLite kaydına (ActivityStore) yazılır.
- Relay'e ayrı mesaj gönderilmez: mevcut tool_request / tool_result olaylarına yalnızca
  meta veri içeren bir 'activity' alanı eklenir. Böylece relay hız sınırı ve yeniden
  bağlanma günlüğü etkilenmez; araç çıktısı yalnızca sohbet akışında kalır.
- Hedef gösterimi her zaman activity_redaction üzerinden geçer; ham argüman saklanmaz.
- Kayıt hatası araç çalışmasını ASLA bozmaz.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid

from .activity_events import make_event
from .activity_redaction import hidden, safe_target

logger = logging.getLogger(__name__)

_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')
FINAL_PHASES = frozenset(('completed', 'failed', 'cancelled', 'timed_out', 'denied'))
_ARG_FOR = {
    'command': {'run_command': 'command'},
    'file': {'read_file': 'path', 'write_file': 'path', 'list_dir': 'path', 'send_artifact': 'path', 'find_files': 'root'},
    'url': {'open_url': 'url', 'web_fetch': 'url'},
    'application': {'open_app': 'name'},
}
_OFF = {'0', 'false', 'off', 'no'}


def safe_identifier(value) -> str:
    """Olay şemasının kimlik biçimine uymayan değerler kısaltılmış bir özetle değiştirilir."""
    text = str(value or '')
    if _ID.fullmatch(text) and not re.search(r'(?i)(?:sk-|key-|token|secret|bearer|password|api[_-]?key)', text):
        return text
    return 'h-' + hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:32]


def classify(tool_name: str, arguments) -> tuple[str, object]:
    """(hedef türü, SafeDisplay). Bilinmeyen araçlarda hedef gizlidir."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if tool_name.startswith('mcp__'):
            parts = tool_name.split('__', 2)
            server = parts[1] if len(parts) > 1 else ''
            tool = parts[2] if len(parts) > 2 else ''
            return 'mcp', safe_target('mcp', server, mcp_tool=tool)
        for kind, table in _ARG_FOR.items():
            key = table.get(tool_name)
            if key:
                value = args.get(key)
                if isinstance(value, str) and value:
                    return kind, safe_target(kind, value)
                return kind, hidden()
    except Exception:
        pass
    return 'other', hidden()


_STORE = None
_STORE_FAILED = False


def _default_store():
    """İşlem başına tek ActivityStore; açılamazsa bir kez uyarılır ve kayıt kapatılır."""
    global _STORE, _STORE_FAILED
    if _STORE is None and not _STORE_FAILED:
        try:
            from .activity_store import ActivityStore
            _STORE = ActivityStore()
        except Exception as exc:
            _STORE_FAILED = True
            logger.warning('Activity history disabled for this process: %s', type(exc).__name__)
    return _STORE


def recording_enabled() -> bool:
    if os.environ.get('MCPTOAI_ACTIVITY_LOG', '').strip().lower() in _OFF:
        return False
    try:
        import json
        from .activity_paths import config_dir
        path = config_dir() / "settings.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        return isinstance(data, dict) and data.get('activity_recording_enabled', True) is not False
    except (OSError, ValueError):
        return False


class ToolActivity:
    """Tek bir araç çağrısının aşamaları; aynı activity_id ile kaydedilir."""

    def __init__(self, recorder: 'ActivityRecorder', tool_name: str, arguments):
        self.recorder = recorder
        self.activity_id = uuid.uuid4().hex
        self.tool_name = safe_identifier(tool_name)
        self.target_type, self.target_display = classify(tool_name, arguments)
        self.decision = None
        self._started = None
        self.last_payload = None

    async def mark(self, phase: str, *, decision: str | None = None) -> dict | None:
        """Aşamayı kaydeder ve relay'e eklenecek meta veriyi döndürür (hata olursa None)."""
        try:
            duration = None
            if phase == 'started':
                self._started = time.monotonic()
            elif phase in FINAL_PHASES and self._started is not None:
                duration = max(0, int((time.monotonic() - self._started) * 1000))
            if decision is not None:
                self.decision = decision
            event = make_event(
                session_id=self.recorder.session_id, turn_id=self.recorder.turn_id,
                tool_name=self.tool_name, phase=phase, target_type=self.target_type,
                target_display=self.target_display, activity_id=self.activity_id,
                permission_decision=self.decision, duration_ms=duration,
                provider=self.recorder.provider, model=self.recorder.model)
            self.last_payload = event.payload()
        except Exception as exc:
            logger.debug('activity event not created: %s', type(exc).__name__)
            return None
        await self.recorder.persist(event)
        return self.last_payload


class ActivityRecorder:
    def __init__(self, session_id=None, store=None, *, enabled: bool | None = None, provider=None, model=None):
        self.session_id = safe_identifier(session_id or uuid.uuid4().hex)
        self.provider = safe_identifier(provider) if provider else None
        self.model = safe_identifier(model) if model else None
        self.turn_id = uuid.uuid4().hex
        self._store = store
        self.enabled = recording_enabled() if enabled is None else enabled

    def new_turn(self) -> None:
        self.turn_id = uuid.uuid4().hex

    def begin(self, tool_name: str, arguments) -> ToolActivity:
        return ToolActivity(self, tool_name, arguments)

    async def persist(self, event) -> None:
        if not self.enabled:
            return
        store = self._store or _default_store()
        if store is None:
            return
        try:
            await asyncio.to_thread(store.append, event)
        except Exception as exc:
            logger.debug('activity store append failed: %s', type(exc).__name__)
