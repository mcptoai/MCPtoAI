import asyncio
from unittest.mock import patch

import pytest
from fastmcp import Client
from mcptoai_agent.config import Settings
from mcptoai_agent.tools import build_server


@pytest.mark.parametrize("url", [
    "", " ", "javascript:alert(1)", "file:///etc/passwd",
    "data:text/html,hi", "http://", "https://",
    "https://user:pass@example.com", "https://example.com:bad",
    "https://example.com/a b", "ftp://example.com",
])
def test_open_url_rejects_without_launch(url):
    async def check():
        with patch("mcptoai_agent.tools.host_tools.webbrowser.open") as browser:
            async with Client(build_server(Settings())) as client:
                result = await client.call_tool("open_url", {"url": url}, raise_on_error=False)
            assert result.is_error or any(
                "[ERROR]" in getattr(item, "text", "") for item in result.content
            )
            browser.assert_not_called()
    asyncio.run(check())


def test_open_url_valid_and_browser_failure():
    async def check():
        with patch("mcptoai_agent.tools.host_tools.webbrowser.open", return_value=False) as browser:
            async with Client(build_server(Settings())) as client:
                result = await client.call_tool("open_url", {"url": "https://example.com/"}, raise_on_error=False)
            assert result.is_error or any("[ERROR]" in getattr(item, "text", "") for item in result.content)
            browser.assert_called_once()
    asyncio.run(check())
