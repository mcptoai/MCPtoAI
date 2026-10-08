from types import SimpleNamespace

from mcptoai_agent.providers import ToolSpec
from mcptoai_agent.policy import ToolPolicy
from mcptoai_agent.relay_client import RelayClient


def test_mcp_discovery_refreshes_existing_session_tool_snapshot(monkeypatch):
    client = object.__new__(RelayClient)
    client.sessions = {
        "existing": SimpleNamespace(remote_tools=[], policy=ToolPolicy(rules={}), server_aliases={})
    }
    server = {"id": "mcp-cf", "name": "Cloudflare", "tools": {"execute": "auto"}}
    spec = ToolSpec("mcp__cloudflare__execute", "Cloudflare execute", {"type": "object"})
    client._remote_tool_specs = {spec.name: spec}
    client._remote_tool_map = {spec.name: (server, "execute")}
    monkeypatch.setattr("mcptoai_agent.relay_client.load_rules", lambda: {})
    monkeypatch.setattr(client, "_server_aliases", lambda: {"Cloudflare": {"id": "mcp-cf", "aliases": ["cloudflare"]}})

    client._refresh_session_remote_tools()

    session = client.sessions["existing"]
    assert [t.name for t in session.remote_tools] == ["mcp__cloudflare__execute"]
    assert session.policy.decide("mcp__cloudflare__execute").value == "auto"
    assert session.server_aliases["Cloudflare"]["id"] == "mcp-cf"
