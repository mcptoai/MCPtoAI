#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, re, subprocess, sys
from pathlib import Path

BACKUP_RE = re.compile(r'(?i)(?:\.bak(?:_|$)|\.old$|\.orig$|\.tmp$|~$)')
SENSITIVE_NAME_RE = re.compile(r'(?i)(?:^|/)(?:\.env(?:\.|$)|id_rsa$|id_ed25519$|.*\.(?:p12|pfx|key)$|credentials\.(?:json|ya?ml|toml|ini|txt)$|secrets?\.(?:json|ya?ml|toml|ini|txt)$)')
OWN_MAP_RE = re.compile(r'(?i)^/?src/.*\.map$')
PROPRIETARY_PY_RE = re.compile(r'(?i)(?:^|/)mcptoai_agent/.*\.py$')
SECRET_PATTERNS = {
    'OpenAI-style API key': re.compile(rb'\bsk-[A-Za-z0-9_-]{16,}\b'),
    'Anthropic API key': re.compile(rb'\bsk-ant-[A-Za-z0-9_-]{16,}\b'),
    'GitHub PAT': re.compile(rb'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    'GitHub token': re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    'AWS access key': re.compile(rb'\bAKIA[0-9A-Z]{16}\b'),
    'Private key PEM': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}
PATH_PATTERNS = {
    'developer macOS home path': re.compile(rb'/Users/[^/\x00\r\n ]+/Documents/Projects/MCPtoAI', re.I),
    'developer Windows project path': re.compile(rb'C:\\\\Users\\\\[^\\\x00\r\n]+\\\\Documents\\\\Projects\\\\MCPtoAI', re.I),
    'server home path': re.compile(rb'/home/[^/\x00\r\n ]+/mcptoai(?:-[a-z]+)?/', re.I),
}

def asar_list(asar: Path, desktop_dir: Path) -> list[str]:
    npx = 'npx.cmd' if os.name == 'nt' else 'npx'
    p = subprocess.run([npx,'--no-install','asar','list',str(asar)], cwd=desktop_dir, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f'asar list failed: {p.stderr.strip()}')
    return [x.strip().lstrip('\\/').replace('\\','/') for x in p.stdout.splitlines() if x.strip()]

def scan_bytes(label: str, path: Path, failures: list[str], warnings: list[str]) -> None:
    data = path.read_bytes()
    for name, rx in SECRET_PATTERNS.items():
        if rx.search(data): failures.append(f'{label}: possible {name}')
    for name, rx in PATH_PATTERNS.items():
        if rx.search(data): warnings.append(f'{label}: contains {name}')

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--resources', required=True, help='Electron Resources directory')
    ap.add_argument('--desktop-dir', default='desktop')
    args=ap.parse_args()
    resources=Path(args.resources).resolve(); desktop=Path(args.desktop_dir).resolve()
    failures=[]; warnings=[]
    if not resources.is_dir():
        print(f'FAIL: resources directory not found: {resources}'); return 2
    files=[p for p in resources.rglob('*') if p.is_file()]
    rels=[p.relative_to(resources).as_posix() for p in files]
    for rel in rels:
        if BACKUP_RE.search(rel): failures.append(f'backup/temp file packaged: {rel}')
        if SENSITIVE_NAME_RE.search(rel) and not rel.lower().endswith('certifi/cacert.pem'):
            failures.append(f'sensitive filename packaged: {rel}')
        if PROPRIETARY_PY_RE.search(rel): failures.append(f'proprietary Python source packaged: {rel}')
    asar=resources/'app.asar'
    if not asar.is_file(): failures.append('app.asar missing')
    else:
        try:
            names=asar_list(asar,desktop)
            maps=[n for n in names if n.lower().endswith('.map')]
            own_maps=[n for n in names if OWN_MAP_RE.search(n)]
            backups=[n for n in names if BACKUP_RE.search(n)]
            sensitive=[n for n in names if SENSITIVE_NAME_RE.search(n)]
            if backups: failures += [f'app.asar backup/temp: {n}' for n in backups]
            if own_maps: failures += [f'app.asar own source map: {n}' for n in own_maps]
            if sensitive: failures += [f'app.asar sensitive filename: {n}' for n in sensitive]
            if maps: warnings.append(f'app.asar contains {len(maps)} dependency source maps')
        except Exception as e: failures.append(str(e))
        scan_bytes('app.asar',asar,failures,warnings)
    # Windows packages keep the raw agent under Resources/agent. macOS packages
    # embed a signed MCPtoAI Device Agent.app and keep its runtime under that
    # bundle's Contents/Resources/agent directory.
    agent_dir=resources/'agent'
    agent_label='agent'
    if not agent_dir.is_dir():
        mac_agent=resources.parent/'Library'/'LoginItems'/'MCPtoAI Device Agent.app'/'Contents'/'Resources'/'agent'
        if mac_agent.is_dir():
            agent_dir=mac_agent; agent_label='Library/LoginItems/MCPtoAI Device Agent.app/Contents/Resources/agent'
        else:
            failures.append('bundled agent directory missing')
    if agent_dir.is_dir():
        # Scan executable/binary files only; third-party .py source is separately filename-checked.
        bins=[]
        for p in agent_dir.rglob('*'):
            if p.is_file() and (os.access(p,os.X_OK) or p.suffix.lower() in {'.exe','.dll','.so','.dylib'}): bins.append(p)
        for p in bins: scan_bytes(f'{agent_label}/{p.relative_to(agent_dir).as_posix()}',p,failures,warnings)
    print(f'Package security scan: {len(files)} resource files')
    for w in sorted(set(warnings)): print(f'WARN: {w}')
    for f in sorted(set(failures)): print(f'FAIL: {f}')
    if failures:
        print(f'RESULT: FAIL ({len(set(failures))} findings)'); return 1
    print('RESULT: PASS')
    return 0
if __name__=='__main__': raise SystemExit(main())
