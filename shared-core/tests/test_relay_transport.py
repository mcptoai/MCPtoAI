import asyncio
import json
import pytest
from mcptoai_core.relay_transport import receive_messages

class Socket:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        async def messages():
            for item in self.items:
                yield item
        return messages()

def test_order_and_bytes():
    async def run():
        received = []
        async def handle(item):
            received.append(item)
        await receive_messages(Socket(['{"seq":1}', b'{"seq":2}']), handle)
        assert received == [{"seq": 1}, {"seq": 2}]
    asyncio.run(run())

def test_bad_json_propagates():
    async def run():
        async def handle(item):
            raise AssertionError("should not dispatch")
        await receive_messages(Socket(['bad']), handle)
    with pytest.raises(json.JSONDecodeError):
        asyncio.run(run())

def test_handler_failure_propagates():
    async def run():
        async def handle(item):
            raise RuntimeError("failure")
        await receive_messages(Socket(['{}']), handle)
    with pytest.raises(RuntimeError):
        asyncio.run(run())

def test_cancel_propagates():
    async def run():
        async def handle(item):
            raise asyncio.CancelledError()
        await receive_messages(Socket(['{}']), handle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())


from mcptoai_core.relay_transport import relay_url, open_relay


@pytest.mark.parametrize("server, expected", [
    ("https://example.test/", "wss://example.test/ws/device/abc/"),
    ("http://example.test/", "ws://example.test/ws/device/abc/"),
])
def test_relay_url_default(server, expected):
    assert relay_url(None, server, "abc") == expected


def test_relay_url_override():
    assert relay_url("wss://relay.example/ws/", "https://unused/", "abc") == "wss://relay.example/ws/"


def test_connection_options_and_context_ownership():
    calls = []
    class Context:
        async def __aenter__(self):
            calls.append("enter")
            return self
        async def __aexit__(self, *args):
            calls.append("exit")
    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return Context()
    async def run():
        async with open_relay(connect, "wss://relay/", {"Authorization": "test"}):
            calls.append("body")
    asyncio.run(run())
    assert calls == [
        ("wss://relay/", {"additional_headers": {"Authorization": "test"},
                          "ping_interval": 20, "ping_timeout": 20, "max_size": 2**20}),
        "enter", "body", "exit"
    ]
