"""MCP SDK 2 response and transport compatibility regressions."""
from types import SimpleNamespace

from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from mcptoai_linux.mcp_streamable_compat import _tool_result_is_error, streamablehttp_client


def test_sdk2_http_transport_exports_exist():
    assert callable(create_mcp_http_client)
    assert callable(streamable_http_client)
    assert callable(streamablehttp_client)


def test_sdk2_result_error_field_and_legacy_compatibility():
    assert _tool_result_is_error(SimpleNamespace(is_error=True)) is True
    assert _tool_result_is_error(SimpleNamespace(is_error=False)) is False
    assert _tool_result_is_error(SimpleNamespace(isError=True)) is True
    assert _tool_result_is_error(SimpleNamespace(isError=False)) is False
    assert _tool_result_is_error(SimpleNamespace()) is False
