from pathlib import Path


def test_background_discovery_is_noninteractive():
    src = Path('mcptoai_agent/relay_client.py').read_text(encoding="utf-8")
    assert 'async def _discover_mcp_tools(self, allow_oauth_prompt=False):' in src
    assert 'create_task(self._discover_mcp_tools(allow_oauth_prompt=False))' in src


def test_local_chat_discovery_is_noninteractive():
    src = Path('mcptoai_agent/__main__.py').read_text(encoding="utf-8")
    assert 'await remote_runtime._discover_mcp_tools(allow_oauth_prompt=False)' in src


def test_explicit_discover_cli_remains_interactive_entrypoint():
    src = Path('mcptoai_agent/discover_cli.py').read_text(encoding="utf-8")
    assert "print('AUTH_URL '+url,flush=True)" in src
