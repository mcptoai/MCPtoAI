"""Resolve Windows user shell folders via SHGetKnownFolderPath, not profile guesses.

KnownFolder GUIDs refer to *current user* and respect OneDrive Known Folder Move.
No registry expansion, shell or environment-variable redirect is trusted as a root.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import uuid

KNOWN_FOLDER_IDS = {
    'Desktop': 'B4BFCC3A-DB2C-424C-B029-7FE99A87C641',
    'Documents': 'FDD39AD0-238F-46AF-ADB4-6C85480369C7',
    'Downloads': '374DE290-123F-4565-9164-39C4925E467B',
}


def get_known_folder(name: str) -> Path:
    """Fail closed on HRESULT failure; do not silently choose USERPROFILE."""
    if name not in KNOWN_FOLDER_IDS:
        raise ValueError('known_folder_unknown')
    if not hasattr(ctypes, 'windll'):
        raise OSError('known_folder_windows_only')
    guid=uuid.UUID(KNOWN_FOLDER_IDS[name]).bytes_le
    guid_arg=(ctypes.c_ubyte*16).from_buffer_copy(guid)
    pointer=ctypes.c_void_p()
    shell=ctypes.windll.shell32
    shell.SHGetKnownFolderPath.argtypes=[ctypes.c_void_p,wintypes.DWORD,wintypes.HANDLE,ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetKnownFolderPath.restype=ctypes.c_long
    ctypes.windll.ole32.CoTaskMemFree.argtypes=[ctypes.c_void_p]
    rc=shell.SHGetKnownFolderPath(ctypes.byref(guid_arg),0,None,ctypes.byref(pointer))
    if rc != 0 or not pointer.value:
        raise OSError('known_folder_unavailable:'+name+':'+hex(rc&0xffffffff))
    try:
        value=ctypes.wstring_at(pointer.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)
    root=Path(value)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise PermissionError('known_folder_invalid:'+name)
    return root.resolve(strict=True)


def default_windows_roots() -> list[Path]:
    """A missing or inaccessible known folder is not replaced by a broader root."""
    roots=[]
    for name in ('Desktop','Documents','Downloads'):
        try:
            root=get_known_folder(name)
        except (OSError,ValueError,PermissionError):
            continue
        if root not in roots:
            roots.append(root)
    return roots
