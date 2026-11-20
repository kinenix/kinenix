"""Which flow folders have a run going on: ~/.kinenix/running/<flow>-<id>/<pid>-<n>.json (#235).

`kinenix install` waits until a flow's runs have ended before it swaps the folder, so a run never sees half of
one version and half of another (docs/design/flow-deploy.md, section 7). Each top-level run writes one file
with its process id and removes it when it ends; a file whose process no longer exists does not count, so a
run killed without cleaning up never blocks an install. Two runs of one flow each have their own file.
"""
import hashlib
import itertools
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List

from ..workspace import settings_file

_counter = itertools.count(1)
_lock = threading.Lock()


def running_dir() -> Path:
    return settings_file().parent / "running"


def flow_key(flow_dir: Path) -> str:
    """The folder's name and a short hash of its full path: readable, and two folders never share a key."""
    resolved = Path(flow_dir).resolve()
    name = re.sub(r"[^\w.-]+", "_", resolved.name)[:60] or "flow"
    digest = hashlib.sha1(os.path.normcase(str(resolved)).encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"{name}-{digest}"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, under another user
    return True


def running_pids(flow_dir: Path) -> List[int]:
    """Process ids of the runs going on in this flow folder; files of ended processes are removed."""
    folder = running_dir() / flow_key(flow_dir)
    pids: List[int] = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            pid = int(json.loads(path.read_text(encoding="utf-8")).get("pid", 0))
        except (OSError, ValueError, AttributeError):
            pid = 0
        if pid_alive(pid):
            pids.append(pid)
        else:
            try:
                path.unlink()
            except OSError:
                pass
    return pids


@contextmanager
def hold(flow_dir: Path) -> Iterator[None]:
    """Marks a run of this flow folder for as long as the block runs. A lock that cannot be written (a
    read-only home folder) does not stop the run; install then cannot see it."""
    folder = running_dir() / flow_key(flow_dir)
    with _lock:
        path = folder / f"{os.getpid()}-{next(_counter)}.json"
    written = False
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": os.getpid(), "flow_dir": str(Path(flow_dir).resolve()),
                                    "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}),
                        encoding="utf-8")
        written = True
    except OSError:
        pass
    try:
        yield
    finally:
        if written:
            try:
                path.unlink()
            except OSError:
                pass
