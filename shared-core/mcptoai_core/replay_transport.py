"""Platform-neutral replay sender; no session state, credentials or socket ownership."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from .replay import replay_batch


async def send_replay_events(socket, is_current: Callable[[], bool], mode, cursor,
                             turn_id, journal, turn_events, session_id,
                             *, interval=0.125):
    """Return (cursor, sent_count, complete); false means stale/failed socket.

    Snapshot batches are recomputed after each send, allowing new events to be
    replayed without replaying old sequence numbers. Cancellation propagates.
    """
    sent = 0
    while socket is not None and is_current():
        items = replay_batch(mode, cursor, turn_id, journal, turn_events, session_id)
        if not items:
            break
        for envelope in items:
            if not is_current():
                return cursor, sent, False
            try:
                await socket.send(json.dumps({**envelope, 'replay': mode}, ensure_ascii=False, default=str))
            except asyncio.CancelledError:
                raise
            except Exception:
                return cursor, sent, False
            cursor = envelope['seq']
            sent += 1
            await asyncio.sleep(interval)
    return cursor, sent, socket is not None and is_current()
