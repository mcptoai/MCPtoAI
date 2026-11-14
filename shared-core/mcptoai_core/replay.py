"""Pure replay request validation, without socket or session side effects."""
from __future__ import annotations

REPLAY_MODES = frozenset({'after_seq', 'active_turn', 'last_turn'})


def parse_replay_request(msg: dict, *, reject_turn_cursor: bool = False):
    """Return (session_id, mode, cursor) or None for invalid requests.

    ``reject_turn_cursor`` preserves Linux's stricter handling of an
    after_seq field in active_turn/last_turn requests during migration.
    """
    if not isinstance(msg, dict):
        return None
    sid = str(msg.get('session_id') or '')
    mode = msg.get('mode') or 'after_seq'
    after = msg.get('after_seq')
    if not sid or len(sid) > 128 or mode not in REPLAY_MODES:
        return None
    if mode == 'after_seq' and (not isinstance(after, int) or isinstance(after, bool) or after < 0):
        return None
    if reject_turn_cursor and mode != 'after_seq' and 'after_seq' in msg:
        return None
    return sid, mode, after


def replay_batch(mode, cursor, turn_id, event_journal, turn_events, session_id):
    """Select the next ordered replay batch without touching sockets or approvals."""
    source = (event_journal.get(session_id, ()) if mode == 'after_seq'
              else turn_events.get(session_id, {}).get(turn_id, ()))
    return [item for item in source if item['seq'] > cursor] if (mode == 'after_seq' or turn_id) else []


def replay_completion(session_id, mode, turn_id, cursor, event_epoch):
    """Build a safe replay cursor acknowledgement; never authorize tool execution."""
    return {'type': 'replay_complete', 'session_id': session_id, 'mode': mode,
            'turn_id': turn_id, 'through_seq': cursor, 'event_epoch': event_epoch}
