"""Decode Windows GUI-Agent shell pipes with the OEM code page actually in use.

CREATE_NO_WINDOW means cmd.exe has no console: `chcp 65001` cannot change its
output code page. cmd's built-ins therefore write OEM (not Python ANSI/UTF-8).
Do not add a console window or alter user commands to fix display encoding.
"""
from __future__ import annotations

import ctypes
import locale
import os


def shell_command_and_encoding(command: str, *, windows: bool | None = None) -> tuple[str, str | None]:
    if windows is None:
        windows = os.name == 'nt'
    if not windows:
        return command, None
    try:
        kernel32 = ctypes.windll.kernel32
        codepage = kernel32.GetOEMCP()  # CREATE_NO_WINDOW has no console; inherited CP is irrelevant
        if codepage > 0:
            return command, f'cp{codepage}'
    except (AttributeError, OSError):
        pass
    return command, locale.getpreferredencoding(False)
