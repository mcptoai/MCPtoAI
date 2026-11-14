"""Guard shared core imports after removing duplicated legacy fallbacks."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_both_agents_import_journal_pruner_directly():
    for directory, package in (("device-agent", "mcptoai_agent"), ("linux-agent", "mcptoai_linux")):
        tree = ast.parse((ROOT / directory / package / "event_journal.py").read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == "mcptoai_core.journal"
                   and any(a.name == "prune_expired" for a in n.names) for n in tree.body)


def test_both_agents_import_network_classifier_directly():
    for directory, package in (("device-agent", "mcptoai_agent"), ("linux-agent", "mcptoai_linux")):
        tree = ast.parse((ROOT / directory / package / "net.py").read_text())
        assert any(isinstance(n, ast.ImportFrom) and n.module == "mcptoai_core.network"
                   and any(a.name == "is_connection_reset" for a in n.names) for n in tree.body)
