"""Privacy-safe, monotonic, per-process timing spans for issue #66.

Never compare monotonic values between browser, relay and agent processes.
Only durations and opaque correlation IDs may cross process boundaries.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from time import monotonic_ns
from uuid import uuid4

PHASES = ('model_first_token_ms', 'tool_call_ready_ms', 'approval_wait_ms',
          'relay_delivery_ms', 'tool_execution_ms', 'result_to_ui_ms')


@dataclass
class TurnTiming:
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    started_ns: int = field(default_factory=monotonic_ns)
    spans: dict[str, int | None] = field(default_factory=lambda: dict.fromkeys(PHASES))

    def record(self, phase: str, start_ns: int, end_ns: int | None = None) -> None:
        if phase not in PHASES:
            raise ValueError('Unknown timing phase')
        end = monotonic_ns() if end_ns is None else end_ns
        if start_ns < 0 or end < start_ns:
            raise ValueError('Invalid monotonic interval')
        self.spans[phase] = (end - start_ns) // 1_000_000

    def snapshot(self) -> dict:
        return {'correlation_id': self.correlation_id, 'phases_ms': dict(self.spans),
                'clock': 'monotonic-per-process', 'unknown_phases':
                [phase for phase, value in self.spans.items() if value is None]}


def log_turn_timing(logger, timing: TurnTiming, tool_names: set[str]) -> None:
    """Exactly one allowlisted INFO record; never interpolate user content."""
    import json
    import re
    safe_tools = sorted({name for name in tool_names if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,79}', name)})
    snapshot = timing.snapshot()
    record = {'correlation_id': snapshot['correlation_id'], 'tools': safe_tools,
              'phases_ms': snapshot['phases_ms'], 'unknown_phases': snapshot['unknown_phases']}
    logger.info('turn_timing %s', json.dumps(record, sort_keys=True, separators=(',', ':')))
