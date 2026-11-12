"""Fail-closed preflight for destructive Activity QA; not a production clear API."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from .activity_store import DEFAULT_FILENAME
from .paths import config_dir


def assert_isolated_activity_db(test_root: str | Path) -> Path:
    root = Path(test_root).resolve(strict=True)
    target = (config_dir() / DEFAULT_FILENAME).resolve(strict=False)
    print(f"ACTIVITY_TEST_DB_RESOLVED={target}", flush=True)
    print(f"ACTIVITY_TEST_ROOT_RESOLVED={root}", flush=True)
    if not root.is_dir() or root.is_symlink() or not (root / '.mcptoai-activity-test-only').is_file():
        raise RuntimeError('Refusing destructive Activity test: isolated root marker missing or invalid')
    if target == root or not target.is_relative_to(root):
        raise RuntimeError('Refusing destructive Activity test: database is outside isolated test root')
    if target.name != DEFAULT_FILENAME:
        raise RuntimeError('Refusing destructive Activity test: unexpected database name')
    return target


def main() -> int:
    if len(sys.argv) != 2:
        print('Usage: python -m mcptoai_agent.activity_test_guard TEST_ROOT', file=sys.stderr)
        return 2
    try:
        assert_isolated_activity_db(sys.argv[1])
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'ABORT: {exc}', file=sys.stderr)
        return 3
    print('ACTIVITY_TEST_DB_ISOLATION=PASS', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
