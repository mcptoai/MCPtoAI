import asyncio
from unittest.mock import AsyncMock
from mcptoai_agent.relay_client import RelayClient


def test_upload_offer_denied_until_trusted_ui_is_wired():
    client=object.__new__(RelayClient)
    client._send=AsyncMock()
    asyncio.run(client._handle({'type':'file_offer','transfer_id':'00000000-0000-4000-8000-000000000001','name':'x.pdf'}))
    client._send.assert_awaited_once_with({'type':'file_ready','transfer_id':'00000000-0000-4000-8000-000000000001','status':'denied','reason':'desktop_unavailable'})


def test_upload_chunk_never_enters_reconnect_journal():
    client=object.__new__(RelayClient)
    client._send=AsyncMock()
    asyncio.run(client._handle({'type':'file_chunk','transfer_id':'00000000-0000-4000-8000-000000000001','data':'QUJD','index':0}))
    client._send.assert_not_awaited()


def test_offer_is_dispatched_without_blocking_relay_loop():
    from unittest.mock import patch
    client=object.__new__(RelayClient)
    client._handle_inbound_upload=AsyncMock()
    with patch('asyncio.create_task') as spawn:
        asyncio.run(client._handle({'type':'file_offer','transfer_id':'00000000-0000-4000-8000-000000000001'}))
        spawn.assert_called_once()
    # Close the unawaited coroutine captured by the patched scheduler.
    spawn.call_args.args[0].close()
