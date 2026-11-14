#!/usr/bin/env python3
"""Linux release version gate; never dispatches publication."""
import argparse
import ast
from importlib.metadata import distribution
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='0.3.0')
    parser.add_argument('--installed', action='store_true')
    args = parser.parse_args()
    assert re.fullmatch(r'\d+\.\d+\.\d+', args.version), 'Invalid version'
    declared = tomllib.loads((ROOT / 'linux-agent/pyproject.toml').read_text())['project']['version']
    assert declared == args.version, f'Linux source version {declared} != {args.version}'
    init = ast.parse((ROOT / 'linux-agent/mcptoai_linux/__init__.py').read_text())
    assert any(isinstance(node, ast.ImportFrom) and node.module == 'importlib.metadata' for node in ast.walk(init)), 'Linux __version__ must use installed metadata'
    if args.installed:
        assert distribution('mcptoai').version == args.version, 'Installed metadata mismatch'
        from mcptoai_linux import __version__
        assert __version__ == args.version, f'Linux runtime version {__version__} != {args.version}'
    print('LINUX_RELEASE_VERSION_GATE_PASS', args.version)


if __name__ == '__main__':
    main()
