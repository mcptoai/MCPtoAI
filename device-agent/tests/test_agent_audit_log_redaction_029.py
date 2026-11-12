"""Canaries must never reach the legacy audit list or agent-error.log."""
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from mcptoai_agent.agent import AgentSession


@pytest.mark.parametrize("tool,args", [
    ("run_command", {"command": 'curl -H "Authorization: Bearer sk-FAKESECRET987654321" https://example.com'}),
    ("run_command", {"command": "API_KEY=sk-FAKESECRET987654321 git status"}),
    ("open_url", {"url": "https://user:sk-FAKESECRET987654321@example.com/private?token=sk-FAKESECRET987654321"}),
    ("mcp__Example__search", {"query": "sk-FAKESECRET987654321", "password": "sk-FAKESECRET987654321"}),
    ("write_file", {"path": "/tmp/sample.txt", "content": "sk-FAKESECRET987654321"}),
])
def test_agent_error_log_never_contains_raw_arguments(tmp_path, tool, args):
    log = tmp_path / "agent-error.log"
    handler = logging.FileHandler(log, encoding="utf-8")
    handler.setLevel(logging.INFO)
    logger = logging.getLogger("mcptoai_agent.agent")
    # _log uses the module logger, not the root logger.
    import mcptoai_agent.agent as module
    module.logger.addHandler(handler)
    old_level = module.logger.level
    module.logger.setLevel(logging.INFO)
    try:
        session = object.__new__(AgentSession)
        session.audit = []
        session._log(tool, args, "approved")
    finally:
        handler.flush()
        module.logger.removeHandler(handler)
        handler.close()
        module.logger.setLevel(old_level)
    text = log.read_text()
    assert "sk-FAKESECRET987654321" not in text
    assert "FAKESECRET987654321" not in text
    assert "password" not in text
    assert "Authorization: Bearer" not in text
    assert "sk-FAKESECRET987654321" not in str(session.audit)
    assert "args" not in session.audit[0]
