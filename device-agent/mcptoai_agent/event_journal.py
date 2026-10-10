"""Bounded, device-local replay journal. Private chat content is stored mode 0600."""
from __future__ import annotations
import json
import os
from collections import deque
from pathlib import Path
from .paths import config_dir

class EventJournal:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_dir() / 'relay-events.json'
        self.data = {}
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw, dict) and raw.get('version') == 1:
                self.data = raw.get('sessions', {})
        except (OSError, ValueError, TypeError):
            pass
        if not isinstance(self.data, dict): self.data = {}

    def append(self, session_id: str, envelope: dict):
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
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp=self.path.with_suffix('.tmp')
        fd=os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump({'version':1,'sessions':self.data},f,ensure_ascii=False)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
            os.chmod(self.path,0o600)
            if os.name == 'nt':
                import subprocess
                account = os.environ.get('USERNAME')
                if not account:
                    raise OSError('Missing Windows user for journal ACL')
                subprocess.run(
                    ['icacls', str(self.path), '/inheritance:r', '/grant:r', account + ':F'],
                    check=True, capture_output=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
        finally:
            if tmp.exists(): tmp.unlink()
