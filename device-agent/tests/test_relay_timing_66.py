"""Contract for ephemeral, content-free relay timing events."""
from pathlib import Path
from mcptoai_agent.turn_timing import PHASES, TurnTiming
from mcptoai_core.journal_entry import safe_journal_event


def test_relay_timing_not_persisted_to_replay_journal():
    timing = TurnTiming()
    timing.record('tool_execution_ms', 1_000_000, 4_000_000)
    snapshot = timing.snapshot()
    event = {'type': 'turn_timing', 'correlation_id': snapshot['correlation_id'],
             'phases_ms': snapshot['phases_ms'], 'unknown_phases': snapshot['unknown_phases']}
    assert set(event['phases_ms']) == set(PHASES)
    assert safe_journal_event(event) is None
    assert not any(k in event for k in ('prompt', 'arguments', 'output', 'path', 'text'))


def test_relay_emitter_uses_snapshot_allowlist():
    import mcptoai_agent.turn_timing as module
    source = Path(module.__file__).with_name('relay_client.py').read_text()
    assert "'type':'turn_timing'" in source
    assert "{key:phases[key] for key in PHASES}" in source
