import pytest
from mcptoai_agent import activity_test_guard as guard


def test_accepts_only_marked_isolated_root(tmp_path, monkeypatch, capsys):
    root=tmp_path/'isolated'; root.mkdir()
    (root/'.mcptoai-activity-test-only').touch()
    monkeypatch.setattr(guard, 'config_dir', lambda: root/'MCPtoAI')
    assert guard.assert_isolated_activity_db(root)==(root/'MCPtoAI'/'activity-v1.sqlite3').resolve()
    assert 'ACTIVITY_TEST_DB_RESOLVED=' in capsys.readouterr().out


def test_rejects_real_profile_even_when_marker_exists(tmp_path, monkeypatch, capsys):
    root=tmp_path/'isolated';root.mkdir();(root/'.mcptoai-activity-test-only').touch()
    monkeypatch.setattr(guard, 'config_dir', lambda: tmp_path/'real-profile')
    with pytest.raises(RuntimeError,match='outside isolated'):
        guard.assert_isolated_activity_db(root)
    assert 'ACTIVITY_TEST_DB_RESOLVED=' in capsys.readouterr().out


def test_rejects_unmarked_root(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, 'config_dir', lambda: tmp_path/'MCPtoAI')
    with pytest.raises(RuntimeError,match='marker'):
        guard.assert_isolated_activity_db(tmp_path)


def test_rejects_symlink_escape(tmp_path, monkeypatch):
    root=tmp_path/'isolated';root.mkdir();(root/'.mcptoai-activity-test-only').touch()
    real=tmp_path/'real';real.mkdir();(root/'MCPtoAI').symlink_to(real,target_is_directory=True)
    monkeypatch.setattr(guard, 'config_dir', lambda: root/'MCPtoAI')
    with pytest.raises(RuntimeError,match='outside isolated'):
        guard.assert_isolated_activity_db(root)
