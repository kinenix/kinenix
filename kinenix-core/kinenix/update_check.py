"""Tell the person at the terminal when a newer Kinenix release is on PyPI.

The check asks https://pypi.org/pypi/kinenix/json at most once a day, in the background, and keeps the
answer in update_check.json next to the saved settings (~/.kinenix/ by default). The request carries
only the package name: no flow data, no machine id. It is skipped when stderr is not a terminal, in CI,
with --json or --format json, for `kinenix hub start`, and when KINENIX_NO_UPDATE_CHECK is set.
A worker running flows from its triggers never reaches this code (it calls the engine, not the CLI).
"""
import json
import os
import re
import sys
import threading
import time
from importlib import metadata
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from .workspace import settings_file

PYPI_URL = "https://pypi.org/pypi/kinenix/json"
CHANGELOG_URL = "https://github.com/kinenix/kinenix/blob/main/CHANGELOG.md"
TIMEOUT = 2.0
CHECK_INTERVAL = 24 * 3600
OPT_OUT_VARIABLE = "KINENIX_NO_UPDATE_CHECK"

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+))?$")
_PRE_ORDER = {"a": 0, "b": 1, "rc": 2}


def parse_version(text: str) -> Optional[Tuple[int, int, int, int, int]]:
    """Sort key for X.Y.Z and X.Y.ZaN / bN / rcN; None for anything else (dev and local builds)."""
    match = _VERSION.match(text.strip())
    if not match:
        return None
    major, minor, patch, pre, pre_number = match.groups()
    # A final release sorts after its pre-releases
    pre_rank = _PRE_ORDER[pre] if pre else 3
    return int(major), int(minor), int(patch), pre_rank, int(pre_number or 0)


def is_prerelease(text: str) -> bool:
    key = parse_version(text)
    return key is not None and key[3] < 3


def latest_from_pypi(data: dict, include_prereleases: bool) -> Optional[str]:
    """Newest release in a PyPI JSON answer; pre-releases only when asked; yanked releases never."""
    best, best_key = None, None
    for version, files in (data.get("releases") or {}).items():
        key = parse_version(version)
        if key is None or (key[3] < 3 and not include_prereleases):
            continue
        if files and all(f.get("yanked") for f in files):
            continue
        if best_key is None or key > best_key:
            best, best_key = version, key
    return best


def newer_version(current: str, latest: Optional[str]) -> Optional[str]:
    """`latest` when it is newer than `current`, otherwise None."""
    if not latest:
        return None
    current_key, latest_key = parse_version(current), parse_version(latest)
    if current_key is None or latest_key is None or latest_key <= current_key:
        return None
    return latest


def cache_file() -> Path:
    return settings_file().parent / "update_check.json"


def read_cache() -> dict:
    try:
        data = json.loads(cache_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_cache(latest: str, include_prereleases: bool) -> None:
    path = cache_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": time.time(), "latest": latest,
                                    "prereleases": include_prereleases}), encoding="utf-8")
    except OSError:
        pass


def fetch_latest(include_prereleases: bool, timeout: float = TIMEOUT) -> Optional[str]:
    """Ask PyPI; None when it cannot be reached or answers something unexpected."""
    try:
        response = requests.get(PYPI_URL, timeout=timeout, headers={"Accept": "application/json"})
        response.raise_for_status()
        latest = latest_from_pypi(response.json(), include_prereleases)
    except (requests.RequestException, ValueError):
        return None
    if latest:
        write_cache(latest, include_prereleases)
    return latest


def cache_is_fresh(cache: dict, include_prereleases: bool, now: Optional[float] = None) -> bool:
    checked_at = cache.get("checked_at")
    if not isinstance(checked_at, (int, float)) or cache.get("prereleases") != include_prereleases:
        return False
    age = (now if now is not None else time.time()) - checked_at
    return 0 <= age < CHECK_INTERVAL


def should_check(argv: List[str], stream=None) -> bool:
    """Whether this command may check: a person at a terminal, not CI, not machine output, not opted out."""
    if os.environ.get(OPT_OUT_VARIABLE, "").strip().lower() not in ("", "0", "false", "no"):
        return False
    if os.environ.get("CI"):
        return False
    stream = stream if stream is not None else sys.stderr
    try:
        if stream is None or not stream.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if "--json" in argv or "--format=json" in argv:
        return False
    for i, arg in enumerate(argv[:-1]):
        if arg == "--format" and argv[i + 1] == "json":
            return False
    # `kinenix hub` and `kinenix hub start` run the server until stopped
    commands = [a for a in argv if not a.startswith("-")]
    if commands[:1] in (["hub"], ["orchestrator"]) and (len(commands) == 1 or commands[1] == "start"):
        return False
    return True


def upgrade_command() -> str:
    """The pip command that upgrades every Kinenix package installed here."""
    extras = []
    for extra, distribution in (("hub", "kinenix-hub"), ("worker", "kinenix-worker")):
        try:
            metadata.version(distribution)
            extras.append(extra)
        except metadata.PackageNotFoundError:
            pass
    target = f"kinenix[{','.join(extras)}]" if extras else "kinenix"
    return f'pip install --upgrade "{target}"'


def notice(current: str, latest: str) -> str:
    return (f"A new Kinenix release is available: {current} -> {latest}\n"
            f"Upgrade: {upgrade_command()}\n"
            f"Changes: {CHANGELOG_URL}\n"
            f"(Turn this message off with {OPT_OUT_VARIABLE}=1)")


class UpdateCheck:
    """Started before a command runs and finished after it, so the command never waits for PyPI longer
    than TIMEOUT, and only on the one run a day that asks."""

    def __init__(self, current: str):
        self.current = current
        self.include_prereleases = is_prerelease(current)
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if cache_is_fresh(read_cache(), self.include_prereleases):
            return
        self._thread = threading.Thread(target=fetch_latest, args=(self.include_prereleases,), daemon=True)
        self._thread.start()

    def finish(self, stream=None) -> None:
        if self._thread is not None:
            self._thread.join(TIMEOUT + 0.5)
        cache = read_cache()
        if cache.get("prereleases") != self.include_prereleases:
            return
        latest = newer_version(self.current, cache.get("latest"))
        if latest:
            stream = stream if stream is not None else sys.stderr
            try:
                print("\n" + notice(self.current, latest), file=stream)
            except (OSError, ValueError):
                pass
