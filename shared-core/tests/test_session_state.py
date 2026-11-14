from mcptoai_core.session_state import prune_session_state


def test_session_eviction_is_bounded_and_consistent():
    journal = {str(i): [i] for i in range(55)}
    seq = {str(i): i for i in range(55)}
    turns = {str(i): {} for i in range(55)}
    state = {str(i): {} for i in range(55)}
    prune_session_state(journal, seq, state, turns)
    assert list(journal) == [str(i) for i in range(5, 55)]
    assert set(journal) == set(seq) == set(turns) == set(state)


def test_no_eviction_under_limit():
    journal = {'s': []}
    seq, turns, state = {}, {}, {}
    prune_session_state(journal, seq, state, turns)
    assert journal == {'s': []}
