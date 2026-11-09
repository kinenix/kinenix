"""A request to stop a run: Ctrl+C, SIGTERM from `systemctl stop`, or a worker that shuts down.

A signal reaches only the main thread, and kinenix-worker daemon runs its flows in other threads, so the request
is a flag that the interpreter reads before each step. The current step ends, the remaining steps are skipped, and
## Finally runs. A second signal stops the process at once: Finally is cut short and no final log is written.
"""
import os
import signal
import sys
import threading

from .. import exit_codes

_requested = threading.Event()


class RunStopped(BaseException):
    """Ends the steps of a run. Not an Exception, so retries and on_error do not treat it as a failure."""


def request_stop() -> None:
    _requested.set()


def clear_stop() -> None:
    _requested.clear()


def stop_requested() -> bool:
    return _requested.is_set()


def wait(seconds: float) -> bool:
    """Sleeps, and wakes as soon as a stop is requested."""
    return _requested.wait(seconds)


def _on_signal(signum, frame) -> None:
    if _requested.is_set():
        os._exit(exit_codes.INTERRUPTED)
    _requested.set()
    print("\nStopping after the current step. Press Ctrl+C again to stop at once.", file=sys.stderr, flush=True)


def install_signal_handlers() -> None:
    """Called by the commands that run flows. Only the main thread can set them; elsewhere nothing changes."""
    clear_stop()
    if threading.current_thread() is not threading.main_thread():
        return
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
