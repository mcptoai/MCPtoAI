import asyncio
from types import SimpleNamespace

from mcptoai_linux.relay_client import RelayClient
from mcptoai_linux.providers import ToolSpec
from mcptoai_linux.policy import Decision


class DummySession:
    def __init__(self):
        self.remote_tools=[]
        self.server_aliases={}
        self.policy=SimpleNamespace(decide=lambda _name: Decision.CONFIRM)


def test_discovery_refreshes_existing_chat_sessions(monkeypatch, tmp_path):
    from mcptoai_linux import relay_client as rc
    from mcptoai_linux.config import Settings

    cfg=Settings()
    client=RelayClient(cfg)
    session=DummySession()
    client.sessions['existing']=session
    client._mcp_discovered=None
    client._mcp_discovered_at=0.0

    tool=ToolSpec('mcp__cloudflare__search','Cloudflare search',{'type':'object'})
    client._remote_tool_specs={tool.name:tool}
    server={'id':'cf','name':'Cloudflare','tools':{'search':'confirm'}}
    client._remote_tool_map={tool.name:(server,'search')}

    async def discover(*, allow_oauth_prompt=False):
        return {'cf':['search']}
    async def send(_event):
        return None

    monkeypatch.setattr(client,'_discover_mcp_tools',discover)
    monkeypatch.setattr(client,'_send',send)
    monkeypatch.setattr(client,'_server_aliases',lambda:{'Cloudflare':{'id':'cf','aliases':['cloudflare','mcp.cloudflare.com']}})
    monkeypatch.setattr(rc,'load_rules',lambda:{})

    asyncio.run(client._send_mcp_state(force=True))

    assert [t.name for t in session.remote_tools]==['mcp__cloudflare__search']
    assert session.server_aliases['Cloudflare']['id']=='cf'
    assert session.policy.decide('mcp__cloudflare__search') is Decision.CONFIRM
