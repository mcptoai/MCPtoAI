"""Linux 0.3.1 regression coverage for Docker live-test findings."""
from dataclasses import replace
from pathlib import Path
import asyncio
import os
import stat
from unittest.mock import patch

import pytest
from mcptoai_linux import config
from mcptoai_linux.agent import AgentSession
from mcptoai_linux.cli import cmd_login
from mcptoai_linux.relay_client import RelayClient


def test_container_roots_missing_mount_fail_closed(monkeypatch):
    monkeypatch.setenv('MCPTOAI_CONTAINER', '1')
    monkeypatch.delenv('MCP_ALLOWED_ROOTS', raising=False)
    with patch('mcptoai_linux.config.Path.is_dir', return_value=False):
        assert config._roots() == []


def test_container_roots_use_workspace(monkeypatch):
    monkeypatch.setenv('MCPTOAI_CONTAINER', '1')
    monkeypatch.delenv('MCP_ALLOWED_ROOTS', raising=False)
    with patch('mcptoai_linux.config.Path.is_dir', return_value=True):
        assert config._roots() == [Path('/workspace')]


def test_container_explicit_roots_win(monkeypatch, tmp_path):
    monkeypatch.setenv('MCPTOAI_CONTAINER', '1')
    monkeypatch.setenv('MCP_ALLOWED_ROOTS', str(tmp_path))
    assert config._roots() == [tmp_path.resolve()]


def test_docker_login_hides_account_id_and_systemd(monkeypatch, capsys):
    monkeypatch.setenv('MCPTOAI_CONTAINER', '1')
    async def login(_cfg): return 'auth0|sensitive-account-id'
    monkeypatch.setattr('mcptoai_linux.auth.device_login', login)
    cmd_login(None)
    output=capsys.readouterr().out
    assert 'Device paired:' in output
    assert 'sensitive-account-id' not in output
    assert 'service install' not in output
    assert 'restart policy' in output


def test_discovery_snapshot_private_after_replace(tmp_path, monkeypatch):
    import mcptoai_linux.relay_client as relay_module
    monkeypatch.setattr(relay_module, 'config_dir', lambda: tmp_path)
    monkeypatch.setattr(relay_module, 'custom_servers', lambda: [])
    existing=tmp_path/'mcp-discovery.json'
    existing.write_text('stale')
    existing.chmod(0o644)
    stub=type('DiscoveryStub', (), {'_stdio_runtimes': {}, '_remote_tool_map': {}, '_remote_tool_specs': {}})()
    old_umask=os.umask(0o022)
    try:
        assert asyncio.run(RelayClient._discover_mcp_tools(stub)) == {}
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(existing.stat().st_mode) == 0o600
    assert not list(tmp_path.glob('.mcp-discovery-*'))


def test_provider_fallback_only_when_single_key(monkeypatch):
    from mcptoai_linux.config import Settings
    from mcptoai_linux import secret_store
    monkeypatch.delenv('MCPTOAI_PROVIDER', raising=False)
    monkeypatch.setattr(secret_store, 'get_secret', lambda name: 'configured' if name == secret_store.api_key_name('openai') else None)
    obj=type('RelayStub', (), {'cfg': replace(Settings(), provider='anthropic', user_settings={})})()
    result=RelayClient._chat_provider_cfg(obj)
    assert result.provider == 'openai'


def test_provider_no_fallback_when_explicit(monkeypatch):
    from mcptoai_linux.config import Settings
    from mcptoai_linux import secret_store
    monkeypatch.setenv('MCPTOAI_PROVIDER','anthropic')
    monkeypatch.setattr(secret_store, 'get_secret', lambda name: 'configured' if name == secret_store.api_key_name('openai') else None)
    obj=type('RelayStub', (), {'cfg': replace(Settings(), provider='anthropic', user_settings={})})()
    with pytest.raises(RuntimeError, match='not configured'):
        RelayClient._chat_provider_cfg(obj)


def test_provider_no_fallback_when_multiple_keys(monkeypatch):
    from mcptoai_linux.config import Settings
    from mcptoai_linux import secret_store
    monkeypatch.delenv('MCPTOAI_PROVIDER', raising=False)
    monkeypatch.setattr(secret_store, 'get_secret', lambda name: 'configured' if name in (secret_store.api_key_name('openai'), secret_store.api_key_name('groq')) else None)
    obj=type('RelayStub', (), {'cfg': replace(Settings(), provider='anthropic', user_settings={})})()
    with pytest.raises(RuntimeError, match='not configured'):
        RelayClient._chat_provider_cfg(obj)
