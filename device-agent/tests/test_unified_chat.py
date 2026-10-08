from pathlib import Path


def test_local_ipc_delegates_to_history_provider():
    bridge = Path('mcptoai_agent/cloud_chat.py').read_text()
    history = Path('mcptoai_agent/history.py').read_text()
    assert 'handle_history_request' in bridge
    assert '"cloud_chat_create"' in history
    assert '"cloud_chat_add_message"' in history
    assert 'MCPtoAIHistoryProvider' in history
    assert 'LocalHistoryProvider' in history


def test_unified_chat_delete_is_supported():
    history = (Path(__file__).parents[1] / "mcptoai_agent" / "history.py").read_text()
    assert '"cloud_chat_delete"' in history
    assert 'delete_chat' in history
