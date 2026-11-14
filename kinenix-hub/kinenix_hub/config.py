import logging
import os
from pathlib import Path

from . import settings_file
from .settings_file import legacy_name, read_saved_settings, settings_path

logger = logging.getLogger("kinenix.hub.config")

# Base Directory
BASE_DIR = Path(__file__).resolve().parent

# Values saved by `kinenix hub setup`; environment variables take precedence over them
SETTINGS_FILE = settings_path()
_saved = read_saved_settings(SETTINGS_FILE)

# Pre-rename ORCHESTRATOR_* environment variables that were used, reported once by log_legacy_names()
LEGACY_NAMES_USED = []


def _env(name: str) -> str:
    """KINENIX_HUB_* from the environment, falling back to the pre-rename ORCHESTRATOR_* name."""
    value = os.environ.get(name)
    if value:
        return value
    old = legacy_name(name)
    value = os.environ.get(old) if old != name else None
    if value:
        LEGACY_NAMES_USED.append(old)
    return value or ""


def _setting(name: str, default: str) -> str:
    return _env(name) or _saved.get(name) or default


def settings_exist() -> bool:
    """True when saved settings were found (hub.env, or orchestrator.env from before the rename)."""
    return bool(_saved)


def log_legacy_names() -> None:
    if LEGACY_NAMES_USED:
        logger.warning(
            "Deprecated environment variable(s) %s, removed in Kinenix 2.0: rename them to %s.",
            ", ".join(sorted(set(LEGACY_NAMES_USED))),
            ", ".join(sorted({n.replace("ORCHESTRATOR_", "KINENIX_HUB_", 1) for n in LEGACY_NAMES_USED})),
        )
    for old, new in settings_file.LEGACY_USED.items():
        logger.warning("Deprecated: %s is read in place of %s; Kinenix 2.0 will not read it. Rename it to %s.",
                       old, new, new)


# Database: SQLite in the user's ~/.kinenix folder by default, so data survives reinstalls and stays out of
# the source tree. Set DATABASE_URL for another location or engine (e.g. PostgreSQL).
DEFAULT_DATABASE_PATH = Path.home() / ".kinenix" / "hub.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}")
if "DATABASE_URL" not in os.environ:
    DEFAULT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

# User views: custom_*.sql files applied at every start (views.py, docs/hub.md)
VIEWS_DIR = Path(_setting("KINENIX_HUB_VIEWS_DIR", str(Path.home() / ".kinenix" / "hub_views"))).expanduser()

# Server binding: localhost by default; set KINENIX_HUB_HOST=0.0.0.0 to accept remote workers and viewers
HOST = _setting("KINENIX_HUB_HOST", "127.0.0.1")
PORT = int(_setting("KINENIX_HUB_PORT", "8080"))

# Shared secret that workers must send in the X-API-Key header; when unset, only localhost clients may write
API_KEY = _setting("KINENIX_HUB_API_KEY", "")

# HTTP Basic Auth for the dashboard page and read endpoints; when no password is set, only localhost may view.
# The settings file stores only a hash; KINENIX_HUB_DASHBOARD_PASSWORD from the environment takes precedence.
DASHBOARD_USER = _setting("KINENIX_HUB_DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = _env("KINENIX_HUB_DASHBOARD_PASSWORD")
DASHBOARD_PASSWORD_HASH = "" if DASHBOARD_PASSWORD else _saved.get("KINENIX_HUB_DASHBOARD_PASSWORD_HASH", "")

# A worker with no heartbeat for this many seconds is reported as offline
WORKER_OFFLINE_SECONDS = int(_env("KINENIX_HUB_WORKER_OFFLINE_SECONDS") or "90")

# Static and artifacts directory
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def dashboard_password_required() -> bool:
    return bool(DASHBOARD_PASSWORD or DASHBOARD_PASSWORD_HASH)
