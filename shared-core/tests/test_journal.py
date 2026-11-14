from mcptoai_core.journal import JOURNAL_TTL_SECONDS, prune_expired


def test_prunes_expired_and_future_entries():
    now = 200000.0
    data = {'s': [{'recorded_at': now}, {'recorded_at': now - JOURNAL_TTL_SECONDS - 1},
                  {'recorded_at': now + 61}, {'recorded_at': True}]}
    assert prune_expired(data, now=now) == {'s': [{'recorded_at': now}]}


def test_bounds_sessions_and_entries():
    data = {f's{i}': [{'recorded_at': 10.0, 'seq': j} for j in range(300)] for i in range(55)}
    result = prune_expired(data, now=10.0)
    assert len(result) == 50
    assert 's0' not in result
    assert len(result['s54']) == 250
    assert result['s54'][0]['seq'] == 50


def test_rejects_invalid_input():
    assert prune_expired(None) == {}
    assert prune_expired({'s': 'bad'}, now=10.0) == {}
