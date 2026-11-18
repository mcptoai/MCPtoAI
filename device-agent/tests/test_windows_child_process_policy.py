"""Windows GUI agent must launch child commands only through process_spawn."""
import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from mcptoai_agent import process_spawn

ROOT = Path(__file__).resolve().parents[1] / 'mcptoai_agent'
DIRECT = {
    'subprocess': {'Popen', 'run', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'},
    'asyncio': {'create_subprocess_exec', 'create_subprocess_shell'},
}


def test_no_direct_subprocess_calls_outside_shared_helper():
    violations = []
    for filename in ROOT.rglob('*.py'):
        if filename.name == 'process_spawn.py':
            continue
        tree = ast.parse(filename.read_text(encoding='utf-8'), filename=str(filename))
        imported_functions = set()
        imported_modules = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in DIRECT:
                        imported_modules[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module in DIRECT:
                for alias in node.names:
                    if alias.name in DIRECT[node.module]:
                        imported_functions.add(alias.asname or alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in imported_functions:
                violations.append(f'{filename.relative_to(ROOT)}:{node.lineno}:{f.id}')
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                module = imported_modules.get(f.value.id)
                if module and f.attr in DIRECT[module]:
                    violations.append(f'{filename.relative_to(ROOT)}:{node.lineno}:{f.value.id}.{f.attr}')
    assert not violations, 'Child process calls must pass through process_spawn:\n' + '\n'.join(violations)


def test_windows_spawn_options_preserve_existing_flags(monkeypatch):
    import subprocess
    # Portable simulation: on Linux/macOS these constants are not exported.
    monkeypatch.setattr(process_spawn.sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, raising=False)
    monkeypatch.setattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, 'STARTF_USESHOWWINDOW', 1, raising=False)
    monkeypatch.setattr(subprocess, 'SW_HIDE', 0, raising=False)
    monkeypatch.setattr(subprocess, 'STARTUPINFO', lambda: SimpleNamespace(dwFlags=0, wShowWindow=1), raising=False)
    fake = Mock()
    monkeypatch.setattr(subprocess, 'run', fake)
    process_spawn.run(['cmd.exe', '/c', 'echo hello'], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    opts = fake.call_args.kwargs
    assert opts['creationflags'] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert opts['creationflags'] & subprocess.CREATE_NO_WINDOW
    assert opts['startupinfo'].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert opts['startupinfo'].wShowWindow == subprocess.SW_HIDE


def test_nonwindows_spawn_keeps_original_options(monkeypatch):
    import subprocess
    monkeypatch.setattr(process_spawn.sys, 'platform', 'linux')
    fake = Mock()
    monkeypatch.setattr(subprocess, 'run', fake)
    process_spawn.run(['true'], start_new_session=True)
    assert fake.call_args.kwargs == {'start_new_session': True}
