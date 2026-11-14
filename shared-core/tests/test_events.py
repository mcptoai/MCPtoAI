from mcptoai_core.events import event_envelope


def test_event_envelope_keeps_existing_wire_shape():
    assert event_envelope('s', 3, 'e', {'type': 'text'}, 10.5) == {
        'type': 'event', 'session_id': 's', 'seq': 3, 'event_epoch': 'e',
        'event': {'type': 'text'}, 'recorded_at': 10.5}
    assert event_envelope('s', 3, 'e', {}, 10.5, turn_id='t')['turn_id'] == 't'
    assert 'turn_id' not in event_envelope('s', 3, 'e', {}, 10.5)
