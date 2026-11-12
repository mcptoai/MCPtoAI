"""MCP SDK 2 streamable HTTP transport with explicit client ownership."""
from contextlib import asynccontextmanager
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
import httpx2


@asynccontextmanager
async def streamablehttp_client(url, *, headers=None, timeout=20, auth=None):
    client = create_mcp_http_client(headers=headers, timeout=httpx2.Timeout(timeout), auth=auth)
    async with client:
        async with streamable_http_client(url, http_client=client) as streams:
            yield streams

def _tool_result_is_error(result):
    """MCP SDK 2 alanı 'is_error'; eski sunucu yanıtları ve SDK 1 için 'isError' yedeği."""
    value = getattr(result, "is_error", None)
    if value is None:
        value = result.__dict__.get("isError") if hasattr(result, "__dict__") else None
    return bool(value)
