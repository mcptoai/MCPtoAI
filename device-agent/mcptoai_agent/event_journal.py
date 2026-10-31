"""Bounded, device-local replay journal. Private chat content is stored mode 0600."""
from __future__ import annotations
import json
import os
import logging
import threading
import time
import uuid
import subprocess
from collections import deque
from pathlib import Path
from .paths import config_dir

logger = logging.getLogger(__name__)

class EventJournal:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_dir() / 'relay-events.json'
        self._lock = threading.RLock()
        self._timer = None
        self._retry_after = 0.0
        self._failures = 0
        self.data = {}
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw, dict) and raw.get('version') == 1:
                self.data = raw.get('sessions', {})
        except (OSError, ValueError, TypeError):
            pass
        if not isinstance(self.data, dict): self.data = {}

    def append(self, session_id: str, envelope: dict):
        try:
            with self._lock:
                self._append_locked(session_id, envelope)
        except Exception:
            logger.exception("Event journal append failed (best effort)")

    def _append_locked(self, session_id: str, envelope: dict):
        # Never persist tool arguments, approval tokens, image data, or credentials.
        event = envelope.get('event') or {}
        if event.get('type') not in {'text', 'done', 'error', 'approval_resolved', 'approval_required'}: return
        if event.get('type') == 'text':
            safe = {'type':'text', 'text':str(event.get('text') or '')[:100000], 'model':str(event.get('model') or '')[:160]}
        elif event.get('type') == 'error':
            safe = {'type':'error', 'message':str(event.get('message') or '')[:2000]}
        elif event.get('type') == 'approval_required':
            # Persist only the existence of an interrupted approval. The original
            # future and execution context are gone after restart, so never
            # represent this as an actionable authorization.
            safe = {'type':'approval_interrupted', 'approval_id':str(event.get('approval_id') or ''), 'tool':str(event.get('tool') or '')[:160]}
        elif event.get('type') == 'approval_resolved':
            safe = {'type':'approval_resolved', 'approval_id':str(event.get('approval_id') or ''), 'status':str(event.get('status') or '')}
        else: safe = {'type':'done', 'model':str(event.get('model') or '')[:160]}
        entry = {k:envelope[k] for k in ('type','session_id','seq','event_epoch','turn_id') if k in envelope}
        entry['event'] = safe
        records = self.data.setdefault(session_id, [])
        records.append(entry)
        self.data[session_id] = records[-250:]
        while len(self.data)>50: self.data.pop(next(iter(self.data)))
        if event.get('type') == 'done':
            self._save()
        elif self._timer is None:
            self._timer = threading.Timer(0.5, self._flush_timer)
            self._timer.daemon = True
            self._timer.start()

    def _flush_timer(self):
        with self._lock:
            self._timer = None
            self._save()

    def flush(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            self._save()

    def _save(self):
        with self._lock:
            if time.monotonic() < self._retry_after:
                return
            try:
                self._save_locked()
                self._failures = 0
                self._retry_after = 0
            except Exception:
                self._failures += 1
                self._retry_after = time.monotonic() + min(30, 0.5 * 2 ** min(self._failures, 6))
                logger.exception("Event journal write failed; retry temporarily suspended")

    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({'version':1,'sessions':self.data},ensure_ascii=False)
        last_error = None
        for attempt in range(7):
            tmp = self.path.with_name(f"relay-events.{os.getpid()}.{uuid.uuid4().hex}.tmp")
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                if os.name == 'nt':
                    # Her yeni geçici dosyanın ACL'sini atomik değiştirmeden önce kısıtla.
                    account = os.environ.get('USERNAME')
                    if not account:
                        raise OSError('Missing Windows user for journal ACL')
                    subprocess.run(
                        ['icacls', str(tmp), '/inheritance:r', '/grant:r', account + ':F'],
                        check=True, capture_output=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10,
                    )
                os.replace(tmp, self.path)
                if os.name != 'nt':
                    os.chmod(self.path, 0o600)
                return
            except (OSError, subprocess.SubprocessError) as exc:
                last_error = exc
                if attempt < 6:
                    time.sleep(min(0.04 * (2 ** attempt), 0.7))
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        raise OSError("Event journal atomic replace failed after retries") from last_error
