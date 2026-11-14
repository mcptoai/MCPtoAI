"""Pure reconnect scheduling shared by Desktop and Linux relay clients.

Callers provide the jitter so no random state, timers, or platform state
is introduced into the core. Device removal remains a terminal condition.
"""
from __future__ import annotations


def reconnect_delay(delay: float, maximum: float, jitter: float) -> tuple[float, float]:
    """Return (sleep seconds, next exponential delay), preserving legacy ordering."""
    return delay + jitter, min(delay * 2, maximum)
