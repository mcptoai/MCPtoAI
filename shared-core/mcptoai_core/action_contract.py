"""Strict v1 Action Tools envelope and device-side, one-shot approval verification.

Not a network protocol by itself: callers must bind a trusted authenticated user/device
and verify a locally recorded grant. Untrusted model content never creates a grant.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import secrets
import time
from typing import Any

MAX_BYTES = 16_384
MAX_STRING = 2_048
MAX_TTL_SECONDS = 300
ACTION_SCHEMAS: dict[str, dict[str, type]] = {
    'file.read': {'path': str},
    'file.write': {'path': str, 'content': str},
    'url.open': {'url': str},
    'file.receive': {'path': str, 'name': str, 'size': str, 'sha256': str},
}
WRITE_ACTIONS = frozenset({'file.write', 'file.receive', 'url.open'})


def _canonical(value: dict[str, Any]) -> bytes:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ValueError('Action exceeds maximum payload size')
    return encoded


@dataclass(frozen=True)
class ActionRequest:
    version: int
    name: str
    arguments: dict[str, Any]

    @classmethod
    def parse(cls, payload: object) -> 'ActionRequest':
        if type(payload) is not dict or set(payload) != {'version', 'name', 'arguments'}:
            raise ValueError('Invalid action envelope')
        version, name, arguments = payload['version'], payload['name'], payload['arguments']
        if type(version) is not int or version != 1 or type(name) is not str or name not in ACTION_SCHEMAS:
            raise ValueError('Unknown action or version')
        schema = ACTION_SCHEMAS[name]
        if type(arguments) is not dict or set(arguments) != set(schema):
            raise ValueError('Unexpected or missing arguments')
        for key, expected_type in schema.items():
            value = arguments[key]
            if type(value) is not expected_type or not value or len(value) > MAX_STRING or '\x00' in value:
                raise ValueError('Invalid action argument: ' + key)
        result = cls(version, name, dict(arguments))
        _canonical(result.as_dict())
        return result

    def as_dict(self) -> dict[str, Any]:
        return {'version': self.version, 'name': self.name, 'arguments': self.arguments}

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict())).hexdigest()


def preview_digest(request: ActionRequest, preview: str) -> str:
    """Digest exact canonical request and locally rendered preview (not model preview)."""
    if type(preview) is not str or not preview or len(preview) > MAX_STRING:
        raise ValueError('Invalid preview')
    return hashlib.sha256(_canonical({'request': request.as_dict(), 'preview': preview})).hexdigest()


@dataclass(frozen=True)
class ApprovalGrant:
    nonce: str
    user_id: str
    device_id: str
    turn_id: str
    action_digest: str
    preview_digest: str
    expires_at: float


class DeviceApprovalGate:
    """In-memory, one-use grants. Approval must come from trusted local UI only."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalGrant] = {}

    def record_local_approval(self, *, user_id: str, device_id: str,
                              request: ActionRequest, preview: str, turn_id: str,
                              ttl_seconds: int = 60, now: float | None = None) -> ApprovalGrant:
        if not user_id or not device_id or not turn_id or type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError('Invalid approval scope or lifetime')
        now = time.time() if now is None else now
        if not math.isfinite(now):
            raise ValueError('Invalid timestamp')
        grant = ApprovalGrant(secrets.token_urlsafe(24), user_id, device_id, turn_id,
                              request.digest(), preview_digest(request, preview), now + ttl_seconds)
        self._pending[grant.nonce] = grant
        return grant

    def consume(self, *, nonce: str, user_id: str, device_id: str, turn_id: str,
                request: ActionRequest, preview: str, now: float | None = None) -> bool:
        # Pop first: even failed verification cannot be replayed or raced.
        if type(nonce) is not str:
            return False
        grant = self._pending.pop(nonce, None)
        if grant is None:
            return False
        now = time.time() if now is None else now
        if not math.isfinite(now) or now >= grant.expires_at:
            return False
        try:
            return (hmac.compare_digest(grant.user_id, user_id)
                    and hmac.compare_digest(grant.device_id, device_id)
                    and hmac.compare_digest(grant.turn_id, turn_id)
                    and hmac.compare_digest(grant.action_digest, request.digest())
                    and hmac.compare_digest(grant.preview_digest, preview_digest(request, preview)))
        except (ValueError, TypeError):
            return False
