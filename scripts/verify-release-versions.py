#!/usr/bin/env python3
"""Fail closed on source, frozen agent, and build-info version drift."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--agent', type=Path, help='Packaged agent executable (mandatory for release)')
    ap.add_argument('--build-info', type=Path, help='Packaged build-info.json')
    ap.add_argument('--release', action='store_true')
    args = ap.parse_args()
    pkg = tomllib.loads((ROOT/'device-agent/pyproject.toml').read_text())['project']['version']
    desktop = json.loads((ROOT/'desktop/package.json').read_text())['version']
    lock = json.loads((ROOT/'desktop/package-lock.json').read_text())['version']
    source = subprocess.check_output([sys.executable,'-c','import mcptoai_agent;print(mcptoai_agent.__version__)'],text=True).strip()
    assert pkg == desktop == lock == source, f'Version drift: pyproject={pkg} desktop={desktop} lock={lock} import={source}'
    if args.release:
        assert args.agent and args.build_info, 'Release requires --agent and --build-info'
    if args.agent:
        out=subprocess.check_output([str(args.agent),'--version'],text=True).strip()
        match=re.search(r'\bmcptoai-agent\s+(\d+\.\d+\.\d+)\b',out)
        assert match and match.group(1)==pkg, f'Frozen agent version mismatch: {out!r} expected {pkg}'
    if args.build_info:
        info=json.loads(args.build_info.read_text())
        assert info.get('version')==pkg, 'Packaged build-info version differs'
        assert info.get('dirty') is False, 'Release build-info must be clean'
        expected=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        assert info.get('commit')==expected, 'Packaged build-info commit differs from HEAD'
    print('RELEASE_VERSION_GATE_PASS',pkg,'frozen' if args.agent else 'source')

if __name__=='__main__':main()
