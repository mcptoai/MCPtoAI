"""macOS-only native Login Item launcher: test actual bundle-relative execv."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_execs_bundled_agent_and_forwards_arguments():
    with tempfile.TemporaryDirectory() as tmp:
        contents = Path(tmp) / 'MCPtoAI Device Agent.app' / 'Contents'
        macos = contents / 'MacOS'
        agent = contents / 'Resources' / 'agent'
        macos.mkdir(parents=True)
        agent.mkdir(parents=True)
        launcher = macos / 'mcptoai-device-agent'
        subprocess.run(['xcrun', 'clang', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'AgentLauncher.c'), '-o', str(launcher)], check=True)
        target = agent / 'mcptoai-agent'
        target.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        target.chmod(0o755)
        default = subprocess.run([str(launcher)], capture_output=True, text=True, check=True)
        assert default.stdout.strip() == 'connect'
        args = subprocess.run([str(launcher), 'doctor', '--help'],
                              capture_output=True, text=True, check=True)
        assert args.stdout.splitlines() == ['doctor', '--help']
