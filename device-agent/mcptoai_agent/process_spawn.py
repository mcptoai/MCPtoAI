"""Single audited boundary for agent-created child processes.

Windows GUI-subsystem agents must never expose console windows when launching
CLI tools.  The helper preserves caller flags while enforcing CREATE_NO_WINDOW
and STARTF_USESHOWWINDOW/SW_HIDE for every subprocess path.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys


def _hidden_options(kwargs):
    options = dict(kwargs)
    if sys.platform == "win32":
        options["creationflags"] = options.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        startup = options.get("startupinfo")
        if startup is None:
            startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startup
    return options


def run(*args, **kwargs):
    return subprocess.run(*args, **_hidden_options(kwargs))


def popen(*args, **kwargs):
    return subprocess.Popen(*args, **_hidden_options(kwargs))


async def create_subprocess_exec(*args, **kwargs):
    return await asyncio.create_subprocess_exec(*args, **_hidden_options(kwargs))


async def create_subprocess_shell(*args, **kwargs):
    return await asyncio.create_subprocess_shell(*args, **_hidden_options(kwargs))
