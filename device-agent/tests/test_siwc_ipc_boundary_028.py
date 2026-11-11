"""Regression checks for Desktop IPC SIWC boundary wiring.

These source checks do not establish OS-level caller identity.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_desktop_chat_uses_local_agent_subprocess_not_relay():
    source = (ROOT / 'desktop/src/main.js').read_text()
    assert "'desktop-chat-jsonl'" in source
    assert "ipcMain.handle('chat:local'" in source
    assert "'siwc-preview','status'" in source
    assert "if(!enabled)return resolve" in source


def test_agent_only_marks_local_chat_entrypoint_as_user_initiated():
    source = (ROOT / 'device-agent/mcptoai_agent/__main__.py').read_text()
    assert 'elif args.cmd == "desktop-chat-jsonl":' in source
    assert 'siwc_origin="desktop-local", siwc_user_initiated=True' in source
    assert 'make_provider(settings)' in source  # Other CLI path defaults to unknown origin.


def test_relay_provider_factory_defaults_fail_closed():
    source = (ROOT / 'device-agent/mcptoai_agent/providers/__init__.py').read_text()
    assert 'siwc_origin="unknown", siwc_user_initiated=False' in source
    assert 'origin=siwc_origin, user_initiated=siwc_user_initiated' in source
