#!/usr/bin/env python3
"""Create a reproducible Device Agent packaging environment from the pinned lock."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / '.venv'
PYTHON = VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def run(*args):
    subprocess.run([str(PYTHON), *args], cwd=ROOT, check=True)


def main():
    if sys.version_info[:2] != (3, 14):
        raise SystemExit('Build requires Python 3.14 (use python3.14 or py -3.14).')
    if PYTHON.exists():
        detected = subprocess.check_output([str(PYTHON), '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'], text=True).strip()
        if detected != '3.14':
            raise SystemExit(f'Existing .venv uses Python {detected}; remove it explicitly before rebuilding with 3.14.')
    else:
        venv.EnvBuilder(with_pip=True).create(VENV)
    run('-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(ROOT / 'requirements-build.lock'))
    if os.name == 'nt':
        # pip-compile on macOS omits Windows-only platform dependencies.
        run('-m', 'pip', 'install', 'pywin32==311')
    run('-m', 'pip', 'check')
    run('-m', 'PyInstaller', '--version')
    print(f'Device Agent build environment ready: {PYTHON}')


if __name__ == '__main__':
    main()
