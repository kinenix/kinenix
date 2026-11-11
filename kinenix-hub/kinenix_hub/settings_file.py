"""Saved Hub settings in the user's home directory, written by `kinenix hub setup`.

The file lives outside the repository (default ~/.kinenix/hub.env, override with
KINENIX_HUB_SETTINGS_FILE) and holds plain KEY=VALUE lines. Environment variables always take
precedence over it. The dashboard password is stored only as a salted PBKDF2 hash.
"""
import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Dict

from kinenix.envfile import read_env_file

PBKDF2_ITERATIONS = 300_000


# The Hub was called the Orchestrator before the rename; its ORCHESTRATOR_* names are still read
LEGACY_PREFIX = "ORCHESTRATOR_"
CURRENT_PREFIX = "KINENIX_HUB_"
LEGACY_SETTINGS_FILE = Path.home() / ".kinenix" / "orchestrator.env"
# Pre-rename names that were read (old name -> new name), reported once by config.log_legacy_names()
LEGACY_USED: Dict[str, str] = {}


def legacy_name(name: str) -> str:
    """KINENIX_HUB_API_KEY -> ORCHESTRATOR_API_KEY."""
    return LEGACY_PREFIX + name[len(CURRENT_PREFIX):] if name.startswith(CURRENT_PREFIX) else name


def settings_path() -> Path:
    """Where `kinenix hub setup` writes; also the first file read."""
    override = os.environ.get("KINENIX_HUB_SETTINGS_FILE")
    if not override and os.environ.get("ORCHESTRATOR_SETTINGS_FILE"):
        override = os.environ["ORCHESTRATOR_SETTINGS_FILE"]
        LEGACY_USED["ORCHESTRATOR_SETTINGS_FILE"] = "KINENIX_HUB_SETTINGS_FILE"
    return Path(override).expanduser() if override else DEFAULT_SETTINGS_FILE


def read_settings(path: Path) -> Dict[str, str]:
    """KEY=VALUE pairs; legacy ORCHESTRATOR_* keys are returned under their KINENIX_HUB_* names."""
    values = {}
    # Written by `kinenix hub setup` without quotes, so no inline comments here, as for kinenix.env
    for key, value in read_env_file(path, inline_comments=False).items():
        if key.startswith(LEGACY_PREFIX):
            key = CURRENT_PREFIX + key[len(LEGACY_PREFIX):]
        values[key] = value
    return values


DEFAULT_SETTINGS_FILE = Path.home() / ".kinenix" / "hub.env"


def read_saved_settings(path: Path) -> Dict[str, str]:
    """Settings from `path`. When the default hub.env does not exist yet, the pre-rename
    ~/.kinenix/orchestrator.env is read instead; an explicitly chosen file never falls back."""
    if path.is_file():
        return read_settings(path)
    if path == DEFAULT_SETTINGS_FILE and LEGACY_SETTINGS_FILE.is_file():
        LEGACY_USED[str(LEGACY_SETTINGS_FILE)] = str(DEFAULT_SETTINGS_FILE)
        return read_settings(LEGACY_SETTINGS_FILE)
    return {}


def write_settings(path: Path, values: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Kinenix Hub settings, written by `kinenix hub setup`.",
             "# Environment variables with the same names take precedence. Do not commit this file."]
    lines += [f"{key}={value}" for key, value in values.items() if value != ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # owner-only on Linux and macOS; Windows keeps the home directory's ACL
    except OSError:
        pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    encode = lambda b: base64.b64encode(b).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${encode(salt)}${encode(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, base64.b64decode(expected))
