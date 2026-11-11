"""SIGTERM is a deliberate user/launchd Stop; crashes retain nonzero status."""
import signal


def install_connect_sigterm_handler():
    # Convert SIGTERM to the same clean shutdown path as Ctrl-C (exit 0).
    # SIGKILL cannot be caught and is reported to launchd as abnormal.
    def _stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)
