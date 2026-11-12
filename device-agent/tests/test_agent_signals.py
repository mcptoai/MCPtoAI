"""Real child process fixtures verify launchd-visible termination codes."""
import os
import signal
import subprocess
import sys
import time


def test_sigterm_clean_exit():
    code = """from mcptoai_agent.agent_signals import install_connect_sigterm_handler
import time
try:
    install_connect_sigterm_handler()
    print('READY', flush=True)
    time.sleep(30)
except KeyboardInterrupt:
    pass
"""
    proc=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,env=os.environ.copy())
    try:
        assert proc.stdout.readline().strip()==b'READY'
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=5)==0
    finally:
        if proc.poll() is None: proc.kill();proc.wait()


def test_sigkill_abnormal_exit():
    proc=subprocess.Popen([sys.executable,'-c','import time; print("READY",flush=True); time.sleep(30)'],stdout=subprocess.PIPE)
    try:
        assert proc.stdout.readline().strip()==b'READY'
        proc.kill()
        assert proc.wait(timeout=5)!=0
    finally:
        if proc.poll() is None: proc.kill();proc.wait()
