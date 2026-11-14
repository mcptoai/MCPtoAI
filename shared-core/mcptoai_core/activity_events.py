"""Metadata-only activity events: display fields require minted SafeDisplay."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Literal
import re
import uuid
from .activity_redaction import SafeDisplay, safe_target, safe_summary, hidden, restore_display

Phase = Literal["requested", "approval_pending", "approved", "denied", "started", "completed", "failed", "cancelled", "timed_out"]
TargetType = Literal["file", "command", "application", "url", "mcp", "other"]
Decision = Literal["approved", "denied", "not_required", "pending"]
_PHASES = frozenset(("requested", "approval_pending", "approved", "denied", "started", "completed", "failed", "cancelled", "timed_out"))
_TARGETS = frozenset(("file", "command", "application", "url", "mcp", "other"))
_DECISIONS = frozenset(("approved", "denied", "not_required", "pending"))
_FIELDS = frozenset(("schema_version", "activity_id", "session_id", "turn_id", "tool_name", "phase", "target_type", "target_display", "summary", "timestamp_utc", "permission_decision", "duration_ms", "provider", "model"))
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


@dataclass(frozen=True)
class ActivityEvent:
    activity_id: str
    session_id: str
    turn_id: str
    tool_name: str
    phase: Phase
    target_type: TargetType
    target_display: SafeDisplay
    summary: SafeDisplay
    timestamp_utc: str
    permission_decision: Decision | None = None
    duration_ms: int | None = None
    provider: str | None = None
    model: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if not isinstance(self.target_display, SafeDisplay) or not isinstance(self.summary, SafeDisplay):
            raise TypeError("Activity display fields require minted SafeDisplay")
        if self.phase not in _PHASES or self.target_type not in _TARGETS:
            raise ValueError("Invalid phase or target type")
        if self.permission_decision is not None and self.permission_decision not in _DECISIONS:
            raise ValueError("Invalid permission decision")
        for name in ("provider", "model"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, str) or not _IDENTIFIER.fullmatch(v) or re.search(r"(?i)(?:sk-|key-|token|secret|bearer|password|api[_-]?key)", v)):
                raise ValueError("Invalid model identity: " + name)
        if self.schema_version != 1:
            raise ValueError("Unsupported schema")
        if self.duration_ms is not None and (type(self.duration_ms) is not int or not 0 <= self.duration_ms <= 86_400_000):
            raise ValueError("Invalid duration")
        for name in ("activity_id", "session_id", "turn_id", "tool_name"):
            v = getattr(self, name)
            if not isinstance(v, str) or not _IDENTIFIER.fullmatch(v):
                raise ValueError("Invalid identifier: " + name)
        if len(self.target_display.value) > 256 or len(self.summary.value) > 512:
            raise ValueError("Metadata too long")

    def payload(self) -> dict:
        d = asdict(self)
        d["target_display"] = self.target_display.value
        d["summary"] = self.summary.value
        return d


def validate_payload(data: dict) -> ActivityEvent:
    """Wire payloads are untrusted. Reconstruct only via allowlisted renderers."""
    if not isinstance(data, dict) or set(data) - _FIELDS:
        raise ValueError("Unexpected activity fields")
    if not isinstance(data.get("target_display"), str) or not isinstance(data.get("summary"), str):
        raise ValueError("Invalid display fields")
    return ActivityEvent(
        **{k: v for k, v in data.items() if k not in ("target_display", "summary")},
        target_display=hidden(), summary=safe_summary(data.get("phase")),
    )


def validate_stored_payload(data: dict) -> ActivityEvent:
    """Cihazın kendi aktivite kaydından okunan yük: gösterim metni yeniden taranarak korunur.

    validate_payload'dan farkı: hedef gösterimi atılmaz, restore_display ile yeniden doğrulanır.
    """
    if not isinstance(data, dict) or set(data) - _FIELDS:
        raise ValueError("Unexpected activity fields")
    if not isinstance(data.get("target_display"), str) or not isinstance(data.get("summary"), str):
        raise ValueError("Invalid display fields")
    return ActivityEvent(
        **{k: v for k, v in data.items() if k not in ("target_display", "summary")},
        target_display=restore_display(data.get("target_display")), summary=safe_summary(data.get("phase")),
    )


def make_event(*, session_id: str, turn_id: str, tool_name: str, phase: Phase,
               target_type: TargetType = "other", target_display: SafeDisplay | None = None,
               summary: SafeDisplay | None = None, activity_id: str | None = None,
               permission_decision: Decision | None = None, duration_ms: int | None = None,
               provider: str | None = None, model: str | None = None) -> ActivityEvent:
    return ActivityEvent(
        activity_id=activity_id or uuid.uuid4().hex, session_id=session_id,
        turn_id=turn_id, tool_name=tool_name, phase=phase,
        target_type=target_type, target_display=target_display if target_display is not None else hidden(),
        summary=summary if summary is not None else safe_summary(phase),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        permission_decision=permission_decision, duration_ms=duration_ms, provider=provider, model=model,
    )
