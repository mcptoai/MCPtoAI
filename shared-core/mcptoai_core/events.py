"""Pure relay event envelope creation; no persistence or network I/O."""
from __future__ import annotations


def event_envelope(session_id, seq, event_epoch, event, recorded_at, turn_id=None):
    packet = {'type': 'event', 'session_id': session_id, 'seq': seq,
              'event_epoch': event_epoch, 'event': event, 'recorded_at': recorded_at}
    if turn_id is not None:
        packet['turn_id'] = turn_id
    return packet
