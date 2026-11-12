# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, copy_metadata
import os
import sys

datas = copy_metadata("mcptoai-agent")
if os.path.isfile('mcptoai_agent/build-info.json'):
    datas.append(('mcptoai_agent/build-info.json', 'mcptoai_agent'))
binaries = []
hiddenimports = ['keyring.backends.Windows' if sys.platform == 'win32' else 'keyring.backends.macOS'] if sys.platform in ('win32','darwin') else []
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('fastmcp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# MCP SDK 2.x: mcp.cli isteğe bağlı 'typer' yoksa içe aktarılırken sys.exit(1) çağırır; agent CLI'ı kullanmaz.
tmp_ret = collect_all('mcp', filter_submodules=lambda name: not (name == 'mcp.cli' or name.startswith('mcp.cli.')))
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('burner_redis')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('docket')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['pyinstaller_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mcptoai-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=(os.getenv("MCPTOAI_PYINSTALLER_CODESIGN_IDENTITY", "Developer ID Application: AHMET BAKTIAYA (WCUHC7RX92)") or None) if sys.platform == "darwin" else None,
    entitlements_file=None,
)
# Windows scheduled supervisor must use a GUI-subsystem bootloader: a
# console-subsystem executable creates a visible black window even when
# Electron's spawn uses windowsHide or Task Scheduler launches it.
quiet_exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='mcptoai-agent-background', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False,
) if sys.platform == 'win32' else None
coll = COLLECT(
    exe,
    *([quiet_exe] if quiet_exe is not None else []),
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='mcptoai-agent',
)
