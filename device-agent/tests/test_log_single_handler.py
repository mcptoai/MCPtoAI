"""stderr redirected to agent-error.log by launchd must not be double-written."""
import io
import logging
from pathlib import Path
from mcptoai_agent.__main__ import _attach_file_log_if_needed


def test_launchd_stderr_to_same_file_is_not_double_logged(tmp_path):
    target = tmp_path / 'agent-error.log'
    root = logging.Logger('isolated')
    with target.open('a+', encoding='utf-8') as redirect:
        stream = logging.StreamHandler(redirect)
        root.addHandler(stream)
        assert _attach_file_log_if_needed(target, root=root, stderr=redirect) is False
        assert len(root.handlers) == 1
        root.info('EXACTLY_ONE_LOG_LINE')
        stream.flush()
    assert target.read_text().count('EXACTLY_ONE_LOG_LINE') == 1


def test_unredirected_stderr_adds_one_rotating_handler_only(tmp_path):
    target = tmp_path / 'agent-error.log'
    root = logging.Logger('isolated')
    with (tmp_path / 'other').open('a+', encoding='utf-8') as other:
        assert _attach_file_log_if_needed(target, root=root, stderr=other)
        assert not _attach_file_log_if_needed(target, root=root, stderr=other)
    assert len(root.handlers) == 1
    for handler in root.handlers: handler.close()
