import pytest
from mcptoai_core.replay import parse_replay_request


@pytest.mark.parametrize('message', [None, {}, {'session_id': 's'},
    {'session_id': 's', 'after_seq': True}, {'session_id': 's', 'after_seq': -1},
    {'session_id': 's', 'after_seq': 1.0}, {'session_id': 's', 'after_seq': 0, 'mode': 'invalid'},
    {'session_id': 'x'*129, 'after_seq': 0}])
def test_invalid_replay_request(message):
    assert parse_replay_request(message) is None


def test_valid_replay_modes():
    assert parse_replay_request({'session_id': 's', 'after_seq': 0}) == ('s', 'after_seq', 0)
    assert parse_replay_request({'session_id': 's', 'mode': 'active_turn'}) == ('s', 'active_turn', None)
    assert parse_replay_request({'session_id': 's', 'mode': 'last_turn'}) == ('s', 'last_turn', None)


def test_platform_specific_cursor_compatibility():
    msg = {'session_id': 's', 'mode': 'last_turn', 'after_seq': 5}
    assert parse_replay_request(msg) == ('s', 'last_turn', 5)
    assert parse_replay_request(msg, reject_turn_cursor=True) is None


def test_replay_batch_cursor_and_turn_scope():
    from mcptoai_core.replay import replay_batch, replay_completion
    events = [{'seq': 1, 'event': {'type': 'text'}}, {'seq': 3, 'event': {'type': 'done'}}]
    assert replay_batch('after_seq', 1, None, {'s': events}, {}, 's') == [events[1]]
    assert replay_batch('active_turn', 0, None, {}, {'s': {'t': events}}, 's') == []
    assert replay_batch('last_turn', 1, 't', {}, {'s': {'t': events}}, 's') == [events[1]]
    assert replay_completion('s', 'after_seq', None, 3, 'epoch') == {
        'type': 'replay_complete', 'session_id': 's', 'mode': 'after_seq',
        'turn_id': None, 'through_seq': 3, 'event_epoch': 'epoch'}
