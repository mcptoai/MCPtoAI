"""Runs the actual compiled login item launcher against real child processes."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def test_crash_restarts_and_stop_does_not():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        counter = root/'count'
        fixture = root/'agent'
        fixture.write_text('#!/bin/sh\necho run >> "$A8_COUNT"\nif [ "$(wc -l < "$A8_COUNT")" -eq 1 ]; then exit 7; fi\nexec sleep 60\n')
        fixture.chmod(0o755)
        launcher = root/'launcher'
        subprocess.run(['xcrun','clang','-Wall','-Wextra','-Werror',f'-DMCPTOAI_TEST_AGENT_PATH="{fixture}"',str(ROOT/'AgentLauncher.c'),'-o',str(launcher)],check=True)
        env = {**os.environ,'A8_COUNT':str(counter)}
        proc = subprocess.Popen([str(launcher)],env=env,start_new_session=True)
        try:
            deadline=time.monotonic()+8
            while time.monotonic()<deadline and (not counter.exists() or len(counter.read_text().splitlines())<2):
                time.sleep(.1)
            assert counter.exists() and len(counter.read_text().splitlines())==2
            os.kill(proc.pid,signal.SIGTERM)
            assert proc.wait(timeout=5)==0
            time.sleep(1.3)
            assert len(counter.read_text().splitlines())==2
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGKILL)
                proc.wait()
