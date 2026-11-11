"""Linux CLI build identity (source checkout or packaged build metadata)."""
import json
import subprocess
from pathlib import Path


def build_info():
    package = Path(__file__).resolve().parent
    info_file = package / 'build-info.json'
    if info_file.exists():
        try:
            data = json.loads(info_file.read_text(encoding='utf-8'))
            if data.get('commit') != 'unknown':
                return {'commit': str(data['commit']), 'dirty': data['dirty'] if isinstance(data['dirty'], bool) else None}
        except (ValueError, KeyError, TypeError):
            pass
    root = package.parent.parent
    if not (root / '.git').exists():
        return {'commit': 'unknown', 'dirty': None}
    try:
        commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True,stderr=subprocess.DEVNULL).strip())
        return {'commit': commit, 'dirty': dirty}
    except (OSError, subprocess.CalledProcessError):
        return {'commit':'unknown','dirty':None}


def version_string(version):
    info = build_info()
    dirty = 'unknown' if info['dirty'] is None else str(info['dirty']).lower()
    return f'mcptoai {version} (commit={info["commit"]}, dirty={dirty})'
