from mcptoai_core.session_state import expire_idle_sessions, evict_session_if_full


def test_idle_expiration_strict_boundary_and_cleanup():
    sessions = {"expired": 1, "boundary": 2, "fresh": 3}
    last_used = {"expired": 99, "boundary": 100, "fresh": 101}
    expire_idle_sessions(sessions, last_used, 3700)
    assert sessions == {"boundary": 2, "fresh": 3}
    assert last_used == {"boundary": 100, "fresh": 101}


def test_lru_eviction_only_on_miss():
    sessions = {"old": 1, "new": 2}
    last_used = {"old": 10, "new": 20}
    evict_session_if_full(sessions, last_used, True, maximum=2)
    assert list(sessions) == ["old", "new"]
    evict_session_if_full(sessions, last_used, False, maximum=2)
    assert sessions == {"new": 2}
    assert last_used == {"new": 20}


def test_cache_below_capacity_is_unchanged():
    sessions, last_used = {"a": 1}, {"a": 5}
    evict_session_if_full(sessions, last_used, False, maximum=50)
    assert sessions == {"a": 1}


from collections import deque, OrderedDict
from mcptoai_core.session_state import begin_turn, finish_turn


def test_begin_turn_preserves_existing_replay_buffer():
    states, events = {}, {}
    begin_turn(states, events, "sid", "t1")
    events["sid"]["t1"].append({"seq": 1})
    begin_turn(states, events, "sid", "t1")
    assert states["sid"] == {"id": "t1", "active": True}
    assert list(events["sid"]["t1"]) == [{"seq": 1}]
    assert isinstance(events["sid"], OrderedDict)
    assert isinstance(events["sid"]["t1"], deque)
    assert events["sid"]["t1"].maxlen == 500


def test_finish_turn_does_not_deactivate_newer_turn():
    states, events = {}, {}
    begin_turn(states, events, "sid", "t1")
    begin_turn(states, events, "sid", "t2")
    finish_turn(states, "sid", "t1")
    assert states["sid"]["active"] is True
    finish_turn(states, "sid", "t2")
    assert states["sid"]["active"] is False
    finish_turn(states, "missing", "t1")


from mcptoai_core.session_state import turn_is_busy, deactivate_new_turn_on_error


def test_busy_turn_rejects_other_id_but_allows_same_id():
    states = {"s": {"id": "a", "active": True}}
    assert turn_is_busy(states, "s", "b")
    assert not turn_is_busy(states, "s", "a")
    assert not turn_is_busy(states, "other", "b")
    states["s"]["active"] = False
    assert not turn_is_busy(states, "s", "b")


def test_unexpected_error_clears_only_new_active_turn():
    old = {"id": "old", "active": True}
    states = {"s": old}
    deactivate_new_turn_on_error(states, "s", old)
    assert old["active"]
    states["s"] = {"id": "new", "active": True}
    deactivate_new_turn_on_error(states, "s", old)
    assert states["s"]["active"] is False
    deactivate_new_turn_on_error(states, "absent", None)
