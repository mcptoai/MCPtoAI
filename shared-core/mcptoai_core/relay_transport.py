"""Shared WebSocket receive loop, preserving adapter socket ownership."""
import json

async def receive_messages(socket, handle):
    async for raw in socket:
        await handle(json.loads(raw))


def relay_url(configured_url, server_url, device_id):
    """Preserve the legacy URL transformation and configured override."""
    return configured_url or server_url.replace("https://", "wss://").replace(
        "http://", "ws://").rstrip("/") + f"/ws/device/{device_id}/"


def open_relay(connect, url, headers):
    """Build a connection context with the existing ping and frame limits.

    The adapter supplies its websocket implementation and owns authentication,
    the socket, and the connected/disconnected state.
    """
    return connect(url, additional_headers=headers, ping_interval=20,
                   ping_timeout=20, max_size=2**20)
