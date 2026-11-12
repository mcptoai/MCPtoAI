"""Regression: local Activity commands must not shadow the login config singleton."""
import ast
from pathlib import Path


def test_activity_cli_does_not_shadow_login_settings():
    path = Path(__file__).resolve().parents[1] / 'mcptoai_agent' / '__main__.py'
    tree = ast.parse(path.read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    assigned = [node for node in ast.walk(main) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == 'settings']
    assert not assigned, 'Local settings assignment shadows the imported login config and crashes pairing'
