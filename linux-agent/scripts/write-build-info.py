#!/usr/bin/env python3
"""Run before Linux wheel/sdist packaging to embed source identity."""
import json
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[2]
def git(*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
# Read provenance before writing generated metadata. The target is gitignored.
info={'commit':git('rev-parse','HEAD'),'dirty':bool(git('status','--porcelain'))}
target=root/'linux-agent/mcptoai_linux/build-info.json'
target.write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
print(f'Wrote {target.name}: {info["commit"][:12]} dirty={info["dirty"]}')
