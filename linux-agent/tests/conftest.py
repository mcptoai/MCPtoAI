"""Tüm testler için izolasyon: gerçek Keychain'e erişim engellenir, HOME geçici dizine taşınır."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from vault_backends import MemoryBackend, block_real_keyring  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path, monkeypatch):
    from mcptoai_linux import secret_store
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Linux config_dir prefers XDG_CONFIG_HOME when the environment provides it
    # (including some CI runners). Point it into this test's temporary home too.
    xdg = home / ".config"
    xdg.mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # Windows production config lives under %APPDATA%\MCPtoAI. Redirect it
    # into the per-test temporary home too, so tests never touch real user data.
    appdata = home / "AppData" / "Roaming"
    localappdata = home / "AppData" / "Local"
    appdata.mkdir(parents=True)
    localappdata.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    block_real_keyring(monkeypatch)
    backend = MemoryBackend()
    previous = secret_store.set_backend(backend)
    try:
        yield backend
    finally:
        secret_store.set_backend(previous)
