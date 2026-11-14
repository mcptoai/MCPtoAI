"""Verify public legacy journal import surfaces without importing platform dependencies."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_journal_import_surfaces():
    for path in (ROOT / 'device-agent/mcptoai_agent/event_journal.py',
                 ROOT / 'linux-agent/mcptoai_linux/event_journal.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        exported = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        constants = {n.targets[0].id for n in tree.body if isinstance(n, ast.Assign)
                     and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
        assert 'EventJournal' in exported, path
        assert any(isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.journal'
                   and any(a.name == 'prune_expired' for a in n.names) for n in tree.body), path
        assert 'JOURNAL_TTL_SECONDS' in constants or any(
            isinstance(n, ast.ImportFrom) and n.module == 'mcptoai_core.journal'
            and any(a.name == 'JOURNAL_TTL_SECONDS' for a in n.names)
            for n in ast.walk(tree)), path
