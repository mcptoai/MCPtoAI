import asyncio
from pathlib import Path

from mcptoai_agent.history import LocalHistoryProvider


def run(coro):
    return asyncio.run(coro)


def test_local_history_roundtrip(tmp_path: Path):
    provider = LocalHistoryProvider(tmp_path / "history.sqlite3")
    chat = run(provider.create_chat(title="Test", provider="openai", model="gpt-test"))
    assert chat["title"] == "Test"
    assert chat["provider"] == "openai"

    run(provider.add_message(chat["id"], role="user", content="hello", model="gpt-test"))
    run(provider.add_message(chat["id"], role="assistant", content="hi", model="gpt-test", tool_data={"ok": True}))

    items = run(provider.list_chats())
    assert len(items) == 1
    assert items[0]["message_count"] == 2

    loaded = run(provider.get_chat(chat["id"]))
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant"]
    assert loaded["messages"][1]["tool_data"] == {"ok": True}

    updated = run(provider.update_chat(chat["id"], title="Renamed", is_pinned=True, is_archived=True))
    assert updated["title"] == "Renamed"
    assert updated["is_pinned"] is True
    assert updated["is_archived"] is True
    assert run(provider.list_chats()) == []
    assert run(provider.list_chats(archived=True))[0]["id"] == chat["id"]

    run(provider.delete_chat(chat["id"]))
    assert run(provider.list_chats(archived=True)) == []


def test_local_history_rejects_invalid_chat_id(tmp_path: Path):
    provider = LocalHistoryProvider(tmp_path / "history.sqlite3")
    result = None
    try:
        run(provider.get_chat("not-a-uuid"))
    except ValueError as exc:
        result = str(exc)
    assert result == "invalid chat id"


def test_selected_provider_reads_live_settings_without_process_restart(tmp_path, monkeypatch):
    import json
    import mcptoai_agent.history as h
    from mcptoai_agent.config import Settings

    monkeypatch.delenv("MCPTOAI_HISTORY_PROVIDER", raising=False)
    monkeypatch.setattr(h, "config_dir", lambda: tmp_path)
    cfg = Settings(user_settings={"history_provider": "mcptoai"})

    assert h.selected_history_provider_name(cfg) == "mcptoai"
    (tmp_path / "settings.json").write_text(json.dumps({"history_provider": "local"}))
    assert h.selected_history_provider_name(cfg) == "local"
    (tmp_path / "settings.json").write_text(json.dumps({"history_provider": "mcptoai"}))
    assert h.selected_history_provider_name(cfg) == "mcptoai"
