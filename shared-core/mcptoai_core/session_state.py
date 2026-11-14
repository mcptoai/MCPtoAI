"""Bounded relay session bookkeeping, independent of transport and storage."""
from __future__ import annotations


def prune_session_state(journal, seq, turn_state, turn_events, *, maximum=50):
    """Evict oldest sessions exactly as legacy relay insertion ordering does."""
    if len(journal) <= maximum:
        return
    for session_id in list(journal)[:-maximum]:
        journal.pop(session_id, None)
        seq.pop(session_id, None)
        turn_state.pop(session_id, None)
        turn_events.pop(session_id, None)


def expire_idle_sessions(sessions, last_used, now, *, ttl=3600):
    """Expire idle cached sessions using the original strict TTL comparison."""
    for key, last in list(last_used.items()):
        if now - last > ttl:
            sessions.pop(key, None)
            last_used.pop(key, None)


def evict_session_if_full(sessions, last_used, session_exists, *, maximum=50):
    """Evict the least recently used session only for a cache miss."""
    if not session_exists and len(sessions) >= maximum:
        oldest = min(last_used, key=last_used.get)
        sessions.pop(oldest, None)
        last_used.pop(oldest, None)


def begin_turn(turn_state, turn_events, session_id, turn_id):
    """Record an active turn and its bounded replay buffer."""
    from collections import OrderedDict, deque
    turn_state[session_id] = {"id": turn_id, "active": True}
    turn_events.setdefault(session_id, OrderedDict()).setdefault(turn_id, deque(maxlen=500))


def finish_turn(turn_state, session_id, turn_id):
    """Never deactivate a newer turn when an older task finishes."""
    if turn_state.get(session_id, {}).get("id") == turn_id:
        turn_state[session_id]["active"] = False


def turn_is_busy(turn_state, session_id, incoming_id):
    """Preserve Desktop's duplicate-ID allowance for an active turn."""
    active = turn_state.get(session_id)
    return bool(active and active["active"] and incoming_id != active["id"])


def deactivate_new_turn_on_error(turn_state, session_id, previous):
    """Clear only a newly created active turn after an unexpected error."""
    current = turn_state.get(session_id)
    if current is not None and current is not previous and current.get("active"):
        current["active"] = False
