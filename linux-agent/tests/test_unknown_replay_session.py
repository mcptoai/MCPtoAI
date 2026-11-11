import asyncio
import json
import logging
from mcptoai_linux.config import Settings
from mcptoai_linux.relay_client import RelayClient


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def test_unknown_session_returns_empty_and_logs(caplog):
    client = RelayClient(Settings())
    client.ws = FakeSocket()
    with caplog.at_level(logging.INFO):
        asyncio.run(client._handle_event_replay_request({"session_id":"not-in-history","after_seq":17}))
    assert client.ws.sent == [{"type":"replay_complete","session_id":"not-in-history",
                               "mode":"after_seq","turn_id":None,"through_seq":0,
                               "event_epoch":client._event_epoch}]
    assert "unknown local session" in caplog.text
    assert "not-in-history" not in caplog.text
    assert "not-in-history" not in client._event_journal
