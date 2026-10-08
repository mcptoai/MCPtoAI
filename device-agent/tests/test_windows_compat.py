from pathlib import Path
import os
from mcptoai_agent import paths


def test_windows_config_dir(monkeypatch):
    monkeypatch.setattr(paths.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", r"C:\\Users\\Alice\\AppData\\Roaming")
    assert str(paths.config_dir()).endswith("MCPtoAI")
    assert "AppData" in str(paths.config_dir())


def test_non_windows_config_dir(monkeypatch):
    monkeypatch.setattr(paths.platform, "system", lambda: "Darwin")
    assert paths.config_dir().parts[-2:] == (".config", "mcptoai")


def test_missing_configured_workspace_fails_closed(monkeypatch, tmp_path):
    import mcptoai_agent.config as config
    missing = tmp_path / "missing-workspace"
    monkeypatch.delenv("MCP_ALLOWED_ROOTS", raising=False)
    monkeypatch.setitem(config.USER_SETTINGS, "workspace_root", str(missing))
    assert config._roots() == []
