"""In-memory transfer lifecycle. No durable state, no journal, no file bytes in logs."""
from __future__ import annotations
import time
from .inbound_session import InboundSession


class InboundManager:
    def __init__(self, *, allowed_roots, max_concurrent=2, ttl=600):
        self.allowed_roots = allowed_roots
        self.max_concurrent = max_concurrent
        self.ttl = ttl
        self._sessions = {}

    def offer(self, *, transfer_id, name, size, sha256, workspace, rename_if_exists=False, subfolder=None):
        self.reap()
        if transfer_id in self._sessions or len(self._sessions) >= self.max_concurrent:
            raise PermissionError('Duplicate or too many active transfers')
        session = InboundSession(transfer_id=transfer_id,name=name,size=size,
            sha256=sha256,workspace=workspace,allowed_roots=self.allowed_roots,ttl=self.ttl,rename_if_exists=rename_if_exists,subfolder=subfolder)
        self._sessions[transfer_id] = session
        return session

    def owns(self, transfer_id):
        self.reap()
        return transfer_id in self._sessions

    def get(self, transfer_id):
        self.reap()
        session = self._sessions.get(transfer_id)
        if session is None:
            raise PermissionError('Unknown or expired transfer')
        return session

    def cancel(self, transfer_id):
        session = self._sessions.pop(transfer_id, None)
        if session is not None:
            session.close()

    def reap(self):
        now = time.monotonic()
        for tid, session in list(self._sessions.items()):
            if session.closed or session.deadline <= now:
                self.cancel(tid)

    def disconnect(self):
        for tid in list(self._sessions):
            self.cancel(tid)
