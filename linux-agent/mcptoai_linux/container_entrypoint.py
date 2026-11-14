"""Docker volume migration before starting the CLI; never delete legacy state."""
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path

LEGACY = Path('/home/mcptoai/.config/mcptoai')
DATA = Path('/data')
MARKER = '.legacy-volume-copied'


def _mounted(path: Path) -> bool:
    # Docker mountpoints are distinct entries; no VOLUME instruction creates
    # anonymous mounts, so an explicit /data mount can be detected reliably.
    try:
        with open('/proc/self/mountinfo', encoding='utf-8') as stream:
            return any(line.split(' - ', 1)[0].split()[4].replace('\\040', ' ') == str(path)
                       for line in stream)
    except OSError:
        return False


def _copy_legacy(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError('Legacy profile must be a real directory')
    for root, dirs, files in os.walk(source, followlinks=False):
        relative = Path(root).relative_to(source)
        destination = target / relative
        destination.mkdir(parents=True, exist_ok=True)
        for name in dirs + files:
            src = Path(root) / name
            if src.is_symlink():
                raise RuntimeError('Refusing to migrate symlink in legacy profile')
            dst = destination / name
            if src.is_dir():
                dst.mkdir(exist_ok=True)
            elif src.is_file():
                shutil.copy2(src, dst, follow_symlinks=False)
            else:
                raise RuntimeError('Unsupported legacy profile entry')
        shutil.copystat(root, destination, follow_symlinks=False)


def prepare() -> None:
    if not _mounted(DATA):
        if LEGACY.is_dir() and any(LEGACY.iterdir()):
            os.environ['MCPTOAI_CONTAINER'] = '0'
            os.environ['XDG_CONFIG_HOME'] = str(LEGACY.parent)
            print('MCPtoAI WARNING: only legacy volume mounted; using legacy path. Mount /data for migration.', file=sys.stderr)
        else:
            print('MCPtoAI WARNING: /data is not mounted; state may not persist.', file=sys.stderr)
        return
    os.environ['MCPTOAI_CONTAINER'] = '1'
    os.environ['XDG_CONFIG_HOME'] = str(DATA)
    if (DATA / MARKER).exists():
        return
    if any(DATA.iterdir()):
        if LEGACY.is_dir() and any(LEGACY.iterdir()):
            raise RuntimeError('/data is nonempty without migration marker; refusing to mix with legacy state')
        return
    if not LEGACY.is_dir() or not any(LEGACY.iterdir()):
        return
    print('MCPtoAI: copying legacy profile to /data (legacy files retained)', file=sys.stderr)
    _copy_legacy(LEGACY, DATA)
    (DATA / MARKER).write_text('legacy profile copied; original retained\n', encoding='utf-8')
    os.chmod(DATA / MARKER, stat.S_IRUSR | stat.S_IWUSR)
    print('MCPtoAI: legacy profile copy complete', file=sys.stderr)


def main() -> None:
    try:
        prepare()
    except Exception as exc:
        print(f'MCPtoAI: legacy migration failed; refusing startup: {exc}', file=sys.stderr)
        raise SystemExit(1) from None
    os.execvp('mcptoai', ['mcptoai', *sys.argv[1:]])


if __name__ == '__main__':
    main()
