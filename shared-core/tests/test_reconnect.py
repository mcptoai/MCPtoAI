from mcptoai_core.reconnect import reconnect_delay


def test_exponential_backoff_with_jitter():
    delay = 1
    for expected in (1, 2, 4, 8, 16, 32):
        sleep, delay = reconnect_delay(delay, 32, 0.25)
        assert sleep == expected + 0.25
        assert delay == min(expected * 2, 32)


def test_legacy_edge_case_behavior():
    assert reconnect_delay(1, 0.5, 0.7) == (1.7, 0.5)
    assert reconnect_delay(32, 32, 0.0) == (32.0, 32)
