import pytest
from mcptoai_agent.turn_timing import PHASES, TurnTiming


def test_unknown_phases_not_fabricated_and_duration_is_monotonic():
    timing = TurnTiming()
    timing.record('approval_wait_ms', 100_000_000, 107_761_000_000)
    result = timing.snapshot()
    assert result['phases_ms']['approval_wait_ms'] == 107661
    assert result['phases_ms']['model_first_token_ms'] is None
    assert set(result['unknown_phases']) == set(PHASES) - {'approval_wait_ms'}
    assert 'prompt' not in str(result) and 'arguments' not in str(result)


def test_invalid_phase_or_clock_order_fails_closed():
    timing = TurnTiming()
    with pytest.raises(ValueError):
        timing.record('raw_prompt', 0, 1)
    with pytest.raises(ValueError):
        timing.record('tool_execution_ms', 10, 9)


def test_snapshot_strict_allowlist_excludes_sensitive_content():
    """Only opaque ID and fixed phase names can leave the timing object."""
    timing = TurnTiming()
    timing.record('tool_execution_ms', 1_000_000, 9_000_000)
    payload = timing.snapshot()
    assert set(payload) == {'correlation_id', 'phases_ms', 'clock', 'unknown_phases'}
    assert set(payload['phases_ms']) == set(PHASES)
    assert all(value is None or isinstance(value, int) for value in payload['phases_ms'].values())
    from uuid import UUID
    assert str(UUID(payload['correlation_id'])) == payload['correlation_id']
    sensitive = ('secret prompt', 'password', '/Users/alice/private', 'tool_arguments', 'tool_output')
    assert not any(value in str(payload) for value in sensitive)


def test_log_is_single_info_allowlisted_and_no_content(caplog):
    import json
    import logging
    from mcptoai_agent.turn_timing import log_turn_timing
    logger = logging.getLogger('timing_privacy_test')
    timing = TurnTiming()
    timing.record('tool_execution_ms', 1_000_000, 9_000_000)
    with caplog.at_level(logging.INFO, logger='timing_privacy_test'):
        log_turn_timing(logger, timing, {'read_file', 'secret prompt /Users/alice/private', 'run_command'})
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.INFO
    assert record.message.startswith('turn_timing ')
    payload = json.loads(record.message.removeprefix('turn_timing '))
    assert set(payload) == {'correlation_id', 'tools', 'phases_ms', 'unknown_phases'}
    assert payload['tools'] == ['read_file', 'run_command']
    assert set(payload['phases_ms']) == set(PHASES)
    assert all(value is None or isinstance(value, int) for value in payload['phases_ms'].values())
    assert 'secret prompt' not in record.message
    assert '/Users/alice/private' not in record.message
    assert 'password' not in record.message
