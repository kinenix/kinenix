"""Runs that could not reach the Hub, kept on this machine and sent later (#173).

A run whose telemetry fails because the Hub cannot be reached, is restarting, or refuses the key is
written to the outbox (`~/.kinenix/outbox`, next to the saved settings) instead of being dropped. The
next run that reaches the Hub, or the worker's next heartbeat, sends what is waiting, oldest first.
The Hub stores one record per `run_id` of a worker (#165), so a run sent twice is still stored once.

Each file holds the same redacted body the Hub receives, readable only by its owner where the file
system supports it. Runs the Hub answers with another error (a malformed body, for example) would
fail again, so they go to `outbox/rejected` and stay there for a person to look at.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger("kinenix")

# Most runs kept; with three flows every 30 minutes this holds about two weeks without a Hub
LIMIT = 2000
# Runs sent in one go, so a long-waiting outbox does not hold up a run or a heartbeat for long
BATCH = 100
# Answers worth trying again later: the key may be fixed, the Hub may come back or calm down
RETRY_STATUS = {401, 403, 408, 425, 429}


def outbox_dir() -> Path:
    """`outbox/` next to the saved settings file, so KINENIX_SETTINGS_FILE moves both (and tests stay away from ~)."""
    from ..workspace import settings_file
    return settings_file().parent / "outbox"


def worth_retrying(status_code: int) -> bool:
    return status_code in RETRY_STATUS or status_code >= 500


def pending() -> List[Path]:
    """Waiting runs, oldest first (file names start with the time they were kept)."""
    folder = outbox_dir()
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.json") if p.is_file())


def keep(body: Mapping[str, Any]) -> Optional[Path]:
    """Write one telemetry body to the outbox. Returns its path, or None when it could not be written."""
    folder = outbox_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        run_id = str((body.get("payload") or {}).get("run_id") or uuid.uuid4().hex)
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_id)[:80]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = folder / f"{stamp}-{safe_id}.json"
        temporary = folder / f".{target.name}.tmp"
        # Owner-only where the file system supports it: the body holds the run's (redacted) variables
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False, default=str)
        os.replace(temporary, target)  # a reader never sees half a file
    except OSError as err:
        logger.warning(f"The run could not be kept for a later send to the Hub: {err}")
        return None
    _trim(LIMIT)
    return target


def _trim(limit: int) -> None:
    waiting = pending()
    extra = len(waiting) - limit
    if extra > 0:
        for path in waiting[:extra]:
            path.unlink(missing_ok=True)
        logger.warning(f"The outbox for the Hub holds more than {limit} runs; the {extra} oldest were dropped. "
                       f"Their logs are still on this machine.")


def send_pending(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 10.0,
                 batch: int = BATCH) -> Tuple[int, int]:
    """
    Send waiting runs to the Hub at `url`, oldest first, and stop at the first one that fails.
    Returns (sent, still waiting). Never raises.
    """
    waiting = pending()
    if not waiting:
        return 0, 0
    try:
        import requests
    except ImportError:
        return 0, len(waiting)
    endpoint = f"{url.rstrip('/')}/api/v1/telemetry"
    sent = 0
    for path in waiting[:batch]:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue  # another process sent it meanwhile
        except (OSError, ValueError) as err:
            _set_aside(path, f"it cannot be read ({err})")
            continue
        try:
            res = requests.post(endpoint, json=body, headers=headers or {}, timeout=timeout)
        except requests.RequestException:
            break
        if res.status_code == 200:
            path.unlink(missing_ok=True)
            sent += 1
        elif worth_retrying(res.status_code):
            break
        else:
            _set_aside(path, f"the Hub answered HTTP {res.status_code}")
    left = len(pending())
    if sent:
        logger.info(f"Sent {sent} earlier run(s) that had not reached the Hub"
                    + (f"; {left} still waiting." if left else "."))
    return sent, left


def _set_aside(path: Path, reason: str) -> None:
    rejected = path.parent / "rejected"
    try:
        rejected.mkdir(exist_ok=True)
        os.replace(path, rejected / path.name)
        logger.warning(f"A run kept for the Hub was set aside in {rejected}, because {reason}.")
    except FileNotFoundError:
        pass
    except OSError as err:
        logger.warning(f"A run kept for the Hub could not be set aside: {err}")
