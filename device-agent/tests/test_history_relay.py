import asyncio
from unittest.mock import AsyncMock, patch

from mcptoai_agent.config import Settings
from mcptoai_agent.relay_client import RelayClient


def run(coro):
    return asyncio.run(coro)


def test_history_status_is_sent():
    client = RelayClient(Settings(user_settings={"history_provider": "local"}))
    client._send = AsyncMock()
    with patch("mcptoai_agent.relay_client.selected_history_provider_name", return_value="local"):
        run(client._send_history_status())
    payload = client._send.await_args.args[0]
    assert payload["type"] == "history_status"
    assert payload["provider"] == "local"
    assert any(x["id"] == "remote" and x["coming_soon"] for x in payload["options"])


def test_history_request_round_trip():
    client = RelayClient(Settings())
    client._send = AsyncMock()
    with patch("mcptoai_agent.relay_client.handle_cloud_chat_request", new=AsyncMock(return_value={"ok": True, "data": []})):
        run(client._handle_history_request({"request_id": "req-1", "request": {"action": "cloud_chats_list"}}))
    client._send.assert_awaited_once_with({"type": "history_response", "request_id": "req-1", "result": {"ok": True, "data": []}})


def test_invalid_history_request_is_not_forwarded():
    client = RelayClient(Settings())
    client._send = AsyncMock()
    with patch("mcptoai_agent.relay_client.handle_cloud_chat_request", new=AsyncMock()) as handler:
        run(client._handle_history_request({"request_id": "", "request": {}}))
    handler.assert_not_awaited()
    client._send.assert_not_awaited()


# --- tercih değişikliğinin açık web oturumlarına bildirilmesi --------------------

class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        import json as _json
        self.sent.append(_json.loads(data))


def test_tercih_degisince_web_e_bir_kez_bildirilir(monkeypatch):
    import asyncio as _asyncio
    from mcptoai_agent import relay_client as rc
    from mcptoai_agent.config import settings
    values = iter(["mcptoai", "local", "local", "local"])
    current = {"v": "mcptoai"}

    def fake_selected(_cfg):
        return current["v"]
    monkeypatch.setattr(rc, "selected_history_provider_name", fake_selected)
    monkeypatch.setattr(rc.RelayClient, "_job_views", lambda self: [])
    real_sleep = _asyncio.sleep
    ticks = {"n": 0}

    async def fake_sleep(_):
        ticks["n"] += 1
        if ticks["n"] > 4:
            raise _asyncio.CancelledError
        current["v"] = next(values)
        await real_sleep(0)
    monkeypatch.setattr(rc.asyncio, "sleep", fake_sleep)

    async def run():
        client = rc.RelayClient(settings)
        client.ws = _FakeWS()
        await client._send_history_status()  # bağlanınca bildirilen ilk tercih
        try:
            await client._watch_jobs()
        except _asyncio.CancelledError:
            pass
        return [m["provider"] for m in client.ws.sent if m["type"] == "history_status"]
    sent = _asyncio.run(run())
    assert sent == ["mcptoai", "local"], sent  # değişiklik bir kez bildirildi, tekrar edilmedi


def test_baglaninca_tercih_sorulmadan_bildirilir():
    import inspect
    from mcptoai_agent import relay_client as rc
    src = inspect.getsource(rc.RelayClient)
    i = src.index("await self._send_jobs_snapshot()\n")
    assert "await self._send_history_status()" in src[i:i + 300]
