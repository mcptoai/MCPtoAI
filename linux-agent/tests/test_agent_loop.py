"""Agent döngüsü testi: gerçek API çağrısı yapmadan sahte provider ile."""

import asyncio
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from mcptoai_linux.agent import AgentSession
from mcptoai_linux.config import settings
from mcptoai_linux.providers.base import AssistantTurn, Provider, ToolCall
from mcptoai_linux.tools import build_server


class FakeProvider(Provider):
    """Önce list_dir, sonra write_file ister, en son metinle bitirir."""
    name = "fake"

    def __init__(self, root: str) -> None:
        super().__init__("x", "fake")
        self.root = root
        self.step = 0

    async def complete(self, system, messages, tools):
        self.step += 1
        if self.step == 1:
            return AssistantTurn(tool_calls=[ToolCall("1", "list_dir", {"path": self.root})])
        if self.step == 2:
            return AssistantTurn(tool_calls=[ToolCall("2", "write_file", {"path": f"{self.root}/x.txt", "content": "hi"})])
        return AssistantTurn(text="bitti")


def test_loop(tmp_path: Path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, FakeProvider(str(tmp_path)), build_server(cfg))
    events: list[dict] = []

    async def emit(e):
        events.append(e)

    async def deny(tool, args):
        return False  # write_file onay ister -> reddet

    result = asyncio.run(session.run("test", deny, emit))
    assert result == ""
    assert not (tmp_path / "x.txt").exists()          # reddedilen yazma gerçekleşmemeli
    decisions = [a["decision"] for a in session.audit]
    assert decisions == ["user_denied"]
    assert events[-1]["type"] == "done"


def test_path_outside_roots(tmp_path: Path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()])
    session = AgentSession(cfg, FakeProvider("/etc"), build_server(cfg))
    events: list[dict] = []

    async def emit(e):
        events.append(e)

    async def allow(tool, args):
        return True

    asyncio.run(session.run("test", allow, emit))
    first = next(e for e in events if e["type"] == "tool_result")
    assert "izin verilen klasörlerin dışında" in first["preview"]


def test_high_risk_auto_is_forced_to_confirm(tmp_path: Path):
    from mcptoai_linux.policy import ToolPolicy, Decision
    policy = ToolPolicy(rules={"write_file": Decision.AUTO, "run_command": Decision.AUTO})
    calls=[]
    async def deny(tool,args):
        calls.append(tool); return False
    async def check():
        a=await policy.authorize("write_file", {"path":str(tmp_path/"x")}, deny)
        b=await policy.authorize("run_command", {"command":"echo nope"}, deny)
        return a,b
    a,b=asyncio.run(check())
    assert a == (False,"user_denied")
    assert b == (False,"user_denied")
    assert calls == ["write_file","run_command"]

def test_low_risk_auto_can_remain_auto():
    from mcptoai_linux.policy import ToolPolicy, Decision
    policy=ToolPolicy(rules={"disk_usage":Decision.AUTO})
    async def should_not_run(tool,args):
        raise AssertionError("approver should not be called")
    assert asyncio.run(policy.authorize("disk_usage",{},should_not_run)) == (True,"auto")

class SingleToolProvider(Provider):
    name='single'
    def __init__(self, call): super().__init__('x','single'); self.call=call; self.step=0
    async def complete(self, system, messages, tools):
        self.step += 1
        if self.step == 1: return AssistantTurn(tool_calls=[self.call])
        return AssistantTurn(text='done')

def _run_one(tmp_path, call):
    cfg=replace(settings,allowed_roots=[tmp_path.resolve()])
    s=AgentSession(cfg,SingleToolProvider(call),build_server(cfg)); events=[]
    async def emit(e): events.append(e)
    async def allow(tool,args): return True
    asyncio.run(s.run('test',allow,emit))
    return next(e for e in events if e['type']=='tool_result')

def _make_dir_link(link: Path, target: Path) -> None:
    """Create a directory link usable by the security tests on every OS."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True, text=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def _remove_dir_link(link: Path) -> None:
    if not link.exists() and not link.is_symlink():
        return
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def test_parent_traversal_write_is_blocked(tmp_path):
    outside=tmp_path.parent/'mcptoai-escape.txt'
    try:
        e=_run_one(tmp_path,ToolCall('1','write_file',{'path':str(tmp_path/'..'/'mcptoai-escape.txt'),'content':'pwn','overwrite':True}))
        assert e['is_error'] or '[ERROR]' in e['preview']
        assert not outside.exists()
    finally: outside.unlink(missing_ok=True)

def test_symlink_escape_read_is_blocked(tmp_path):
    outside_dir = tmp_path.parent / f"{tmp_path.name}-outside-read"
    outside_dir.mkdir()
    secret = outside_dir / "secret.txt"
    secret.write_text("outside", encoding="utf-8")
    link = tmp_path / "outside"
    _make_dir_link(link, outside_dir)
    try:
        e = _run_one(tmp_path, ToolCall('1', 'read_file', {'path': str(link / secret.name)}))
        assert e['is_error'] or '[ERROR]' in e['preview']
        assert 'izin verilen klasörlerin dışında' in e['preview']
    finally:
        _remove_dir_link(link)
        secret.unlink(missing_ok=True)
        outside_dir.rmdir()

def test_symlink_escape_write_is_blocked(tmp_path):
    outside=tmp_path.parent/'mcptoai-symlink-escape.txt'; link=tmp_path/'out'
    _make_dir_link(link, tmp_path.parent)
    try:
        e=_run_one(tmp_path,ToolCall('1','write_file',{'path':str(link/outside.name),'content':'pwn','overwrite':True}))
        assert e['is_error'] or '[ERROR]' in e['preview']
        assert not outside.exists()
    finally:
        _remove_dir_link(link)
        outside.unlink(missing_ok=True)

def test_shell_tools_absent_when_shell_disabled(tmp_path):
    cfg=replace(settings,allowed_roots=[tmp_path.resolve()],enable_shell=False)
    async def names():
        from fastmcp import Client
        async with Client(build_server(cfg)) as c: return {t.name for t in await c.list_tools()}
    tools=asyncio.run(names())
    assert 'run_command' not in tools and 'run_in_project' not in tools

def test_remote_mcp_url_rejects_local_and_insecure_targets():
    from mcptoai_linux.mcp_config import validate_remote_mcp_url
    import pytest
    for url in ('http://example.com/mcp','https://localhost/mcp','https://127.0.0.1/mcp','https://10.0.0.1/mcp','https://[::1]/mcp','https://user:pass@example.com/mcp'):
        with pytest.raises(ValueError): validate_remote_mcp_url(url)
    assert validate_remote_mcp_url('https://example.com/mcp')=='https://example.com/mcp'

def test_mcp_header_and_env_bounds(tmp_path,monkeypatch):
    import pytest
    import mcptoai_linux.mcp_config as mc
    monkeypatch.setattr(mc,'PATH',tmp_path/'mcp.json')
    for headers in ({'Bad\nHeader':'x'},{'Authorization':'x\ny'},{str(i):'x' for i in range(33)}):
        with pytest.raises(ValueError): mc.add_server('x',transport='streamable-http',url='https://example.com/mcp',headers=headers)
    with pytest.raises(ValueError): mc.add_server('x',transport='streamable-http',url='https://example.com/mcp',env={'A':'x'*9000})

def test_remote_control_cannot_remove_local_stdio(tmp_path,monkeypatch):
    import mcptoai_linux.mcp_config as mc
    from mcptoai_linux.relay_client import RelayClient
    monkeypatch.setattr(mc,'PATH',tmp_path/'mcp.json')
    local=mc.add_server('local','/usr/bin/true',transport='stdio')
    client=RelayClient(replace(settings,allowed_roots=[tmp_path.resolve()])); sent=[]
    async def fake_send(x): sent.append(x)
    client._send=fake_send
    asyncio.run(client._remove_mcp_server({'server_id':local['id']}))
    assert any(s.get('id')==local['id'] for s in mc.custom_servers())
    assert 'PermissionError' in sent[-1].get('error','')

def test_mcp_dns_private_resolution_is_rejected(monkeypatch):
    import pytest, socket
    import mcptoai_linux.mcp_config as mc
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='resolves to a local/private'): mc.validate_remote_mcp_url('https://public.example/mcp')

def test_mcp_update_cannot_change_connection_fields(tmp_path,monkeypatch):
    import mcptoai_linux.mcp_config as mc
    monkeypatch.setattr(mc,'PATH',tmp_path/'mcp.json')
    s=mc.add_server('remote',transport='streamable-http',url='https://example.com/mcp')
    mc.update_server(s['id'],{'url':'https://evil.example/mcp','transport':'stdio','command':'/bin/sh','args':['-c','id'],'headers':{'X':'Y'}})
    got=next(x for x in mc.custom_servers() if x['id']==s['id'])
    assert got['url']=='https://example.com/mcp' and got['transport']=='streamable-http' and not got['command']



def test_host_inspection_tools_are_low_risk_auto():
    from mcptoai_linux.policy import ToolPolicy, DEFAULT_RULES
    policy = ToolPolicy(rules=dict(DEFAULT_RULES))
    async def should_not_run(tool,args):
        raise AssertionError(f"read-only host inspection unexpectedly requested approval: {tool}")
    async def check():
        for name in ("system_info", "service_status", "docker_status", "port_status"):
            assert await policy.authorize(name, {}, should_not_run) == (True, "auto")
    asyncio.run(check())


def test_system_info_tool_runs_with_shell_disabled(tmp_path: Path):
    cfg = replace(settings, allowed_roots=[tmp_path.resolve()], enable_shell=False)
    result = _run_one(tmp_path, ToolCall("sys", "system_info", {}))
    preview = result.get("preview") or ""
    assert "OS:" in preview
    assert "Kernel:" in preview
    assert "Architecture:" in preview
