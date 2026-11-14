import asyncio
import json
from contextlib import contextmanager

@contextmanager
def raises_cancelled():
    try:
        yield
    except asyncio.CancelledError:
        return
    raise AssertionError("Expected CancelledError")
from mcptoai_core.replay_transport import send_replay_events


class Socket:
    def __init__(self, on_send=None):
        self.packets = []
        self.on_send = on_send

    async def send(self, data):
        self.packets.append(json.loads(data))
        if self.on_send:
            self.on_send()


def test_replay_order_and_cursor():
    async def run():
        socket = Socket()
        events = [{'seq': 1}, {'seq': 2}, {'seq': 3}]
        result = await send_replay_events(socket, lambda: True, 'after_seq', 1,
                                          None, {'s': events}, {}, 's', interval=0)
        assert result == (3, 2, True)
        assert [p['seq'] for p in socket.packets] == [2, 3]
        assert all(p['replay'] == 'after_seq' for p in socket.packets)
    asyncio.run(run())

def test_replay_disconnect_stops_before_next_packet():
    async def run():
        active = [True]
        socket = Socket(lambda: active.__setitem__(0, False))
        result = await send_replay_events(socket, lambda: active[0], 'after_seq', 0,
                                          None, {'s': [{'seq': 1}, {'seq': 2}]}, {}, 's', interval=0)
        assert result == (1, 1, False)
        assert len(socket.packets) == 1
    asyncio.run(run())

def test_replay_send_failure_does_not_ack():
    async def run():
        class BrokenSocket:
            async def send(self, data):
                raise ConnectionError('disconnect')
        assert await send_replay_events(BrokenSocket(), lambda: True, 'after_seq', 0,
                                        None, {'s': [{'seq': 1}]}, {}, 's', interval=0) == (0, 0, False)
    asyncio.run(run())

def test_replay_cancel_propagates():
    async def run():
        class CancelSocket:
            async def send(self, data):
                raise asyncio.CancelledError()
        with raises_cancelled():
            await send_replay_events(CancelSocket(), lambda: True, 'after_seq', 0,
                                     None, {'s': [{'seq': 1}]}, {}, 's', interval=0)
    asyncio.run(run())
