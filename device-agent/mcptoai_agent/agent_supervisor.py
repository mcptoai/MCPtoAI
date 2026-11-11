"""Windows user-session agent supervisor; never bypasses connect's singleton lock."""
import logging
import signal
import subprocess
import sys
import threading

log = logging.getLogger(__name__)


def supervise(command, *, popen=subprocess.Popen, wait=None, pause=None):
    """Restart crashes; exit cleanly after a child exits 0 or supervisor Stop."""
    from .windows_job import create_kill_on_close_job
    job = create_kill_on_close_job()
    stop = threading.Event()
    child = None
    def on_stop(_sig, _frame):
        stop.set()
        if child is not None and child.poll() is None:
            child.terminate()
    old = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            old[sig] = signal.signal(sig, on_stop)
        except ValueError:
            pass
    delay = 1
    try:
        while not stop.is_set():
            # Keep the supervised connect process invisible on Windows.
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            child = popen(command, creationflags=flags)
            if job is not None:
                try: job.assign(child.pid)
                except Exception:
                    child.terminate()
                    child.wait()
                    raise
            code = child.wait()
            child = None
            if stop.is_set() or code == 0:
                return 0
            log.error('Agent exited unexpectedly with status %s; restarting in %ss', code, delay)
            if (pause or stop.wait)(delay):
                return 0
            delay = min(delay * 2, 30)
        return 0
    finally:
        if job is not None: job.close()
        for sig, handler in old.items():
            signal.signal(sig, handler)


def run():
    from .credential_lock import CredentialLock, CredentialLockTimeout
    from .paths import config_dir
    lock = CredentialLock(lambda: config_dir() / "supervisor.lock", timeout=0)
    try:
        with lock.hold(timeout=0):
            return supervise([sys.executable, 'connect'])
    except CredentialLockTimeout:
        log.info("Supervisor already running")
        return 0
