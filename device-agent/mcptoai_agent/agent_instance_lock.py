"""Nonblocking process-wide relay agent singleton lock."""
from __future__ import annotations
from .credential_lock import CredentialLock, CredentialLockTimeout
from .paths import config_dir

_LOCK = CredentialLock(lambda: config_dir() / "agent.lock", timeout=0)

def agent_instance_lock():
    return _LOCK.hold(timeout=0)
