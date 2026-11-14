"""Removes secrets and personal data from what leaves a run: log files, console errors, and Hub telemetry.

Redaction works on copies; the values a flow uses while it runs are never changed. It is best effort:
patterns can miss a value or hide one that is not secret, so flows should also record only what they need.
"""
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

MASK = "****"

# Key names whose values are secret, in parameters, config, variables, and outputs
# (anywhere in the name, or the whole name for words that also appear in harmless names such as cookie_banner;
# pin and otp only as a word of the name, since they are also inside shipping, spinner, and footprint)
SECRET_KEY = re.compile(
    r"password|passwd|passcode|secret|token|api[_-]?key|authorization|private[_-]?key"
    r"|(?:^|[_\-. ])(?:pin|otp)(?:$|[_\-. ])"
    r"|^(?:pwd|cookies?|set-cookie|credentials?)$", re.I)

# `password=...`, `token: ...`, `Authorization: Bearer ...` inside text such as URLs and error messages
SECRET_PAIR = re.compile(
    r"(?P<key>\b[\w-]*(?:password|passwd|passcode|pwd|secret|token|api[_-]?key|authorization)[\w-]*\b[\"']?\s*[=:]\s*[\"']?)"
    r"(?P<value>(?:bearer\s+|basic\s+)?[^\s&\"',;]+)", re.I)

# Kinenix settings that are not secret, so their values stay readable when they come from .env
NOT_SECRET_ENV = {
    "KINENIX_HUB_URL", "KINENIX_WORKER_ID", "KINENIX_FLOWS_DIR", "KINENIX_HEARTBEAT_INTERVAL", "KINENIX_LOG_DIR",
    "KINENIX_HUB_HOST", "KINENIX_HUB_PORT", "KINENIX_HUB_DASHBOARD_USER", "KINENIX_HUB_SETTINGS_FILE",
    "KINENIX_HUB_WORKER_OFFLINE_SECONDS",
    # Set by Linux and macOS shells to the current and previous working directory; "pwd" here is not a password
    "PWD", "OLDPWD",
}

# More names that mean a secret in a .env file, as a word of the name (DB_PASS, ACCESS_KEY, SESSION_ID)
SECRET_ENV_WORD = re.compile(r"(?:^|[_\-.])(?:pass|pwd|key|auth|creds?|credentials?|session|cookies?)(?:$|[_\-.])", re.I)

# Ids Kinenix creates hold no secrets, and the Hub matches records by them, so they are never changed
KEPT_AS_IS = {"run_id", "flow_name"}

# Every use of an environment variable in a flow: ${env.NAME}, and env.NAME inside an expression
ENV_REFERENCE = re.compile(r"\benv\.([A-Za-z_][A-Za-z0-9_]*)")

# Shorter values are not replaced inside text, or a value such as "1" would be hidden everywhere
MIN_SECRET_LENGTH = 4

# 13 to 19 digits, optionally grouped with spaces or dashes; not part of a longer number or a decimal
DIGITS = re.compile(r"(?<![\d.])\d(?:[ -]?\d){12,18}(?!\.?\d)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# Thai mobile (06, 08, 09) and landline (02-07) numbers, with or without +66, spaces, or dashes
PHONE = re.compile(r"(?<![\d+])(?:\+66[ -]?|0)(?:[689]\d|[2-7])[ -]?\d{3}[ -]?\d{3,4}(?![\d])")


def is_thai_id(digits: str) -> bool:
    if len(digits) != 13:
        return False
    total = sum(int(d) * (13 - i) for i, d in enumerate(digits[:12]))
    return (11 - total % 11) % 10 == int(digits[12])


def passes_luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _digit_marker(match: "re.Match[str]") -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if is_thai_id(digits):
        return "[thai-id]"
    if passes_luhn(digits):
        return "[card]"
    return match.group(0)


class Redactor:
    """The secrets and settings of one run, shared by the main flow, its subflows, and their actions."""

    def __init__(self, environment: Optional[Mapping[str, str]] = None) -> None:
        """`environment` defaults to os.environ and the saved settings; secret-looking variables are hidden."""
        self._secrets: Set[str] = set()
        self._env_read: Set[str] = set()
        self.fields: Set[str] = set()
        self.contacts = True
        if environment is None:
            # The Hub key may be saved in ~/.kinenix/kinenix.env (kinenix connect) instead of the environment
            from ..workspace import saved_settings
            environment = {**saved_settings(), **os.environ}
        for name, value in environment.items():
            if SECRET_KEY.search(name) and name not in NOT_SECRET_ENV:
                self.add_secret(value)

    def add_secret(self, value: Any) -> None:
        """Hides this value wherever it appears in text (values shorter than 4 characters are only hidden by key)."""
        if value is None or isinstance(value, (dict, list, bool)):
            return
        text = str(value).strip()
        if len(text) >= MIN_SECRET_LENGTH:
            self._secrets.add(text)

    def add_env(self, names: Iterable[str]) -> None:
        for name in names:
            if name in NOT_SECRET_ENV:
                continue
            self._env_read.add(name)
            if os.environ.get(name):
                self.add_secret(os.environ[name])

    def add_env_references(self, text: str) -> None:
        """Hides the values of every environment variable that a flow reads."""
        self.add_env(ENV_REFERENCE.findall(text))

    def add_env_file_value(self, name: str, value: str) -> None:
        """
        Hides a value from a .env file when its name looks secret or a flow of this run reads it. Other values
        never reach the records, and hiding them everywhere changed flow names and text such as `sales` (#170).
        """
        if name in NOT_SECRET_ENV:
            return
        if SECRET_KEY.search(name) or SECRET_ENV_WORD.search(name) or name in self._env_read:
            self.add_secret(value)
            self.add_secret(os.environ.get(name))

    def configure(self, config: Any) -> None:
        """Reads `redact` (more field names to hide) and `redact_contacts` (false keeps phones and e-mails) from config."""
        if not isinstance(config, dict):
            return
        fields = config.get("redact")
        if isinstance(fields, str):
            fields = [fields]
        if isinstance(fields, list):
            self.fields.update(str(f).strip().lower() for f in fields if str(f).strip())
        if "redact_contacts" in config:
            self.contacts = str(config["redact_contacts"]).strip().lower() not in ("false", "no", "0", "off")

    def is_secret_key(self, key: Any) -> bool:
        name = str(key)
        return bool(SECRET_KEY.search(name)) or name.strip().lower() in self.fields

    def redact(self, data: Any) -> Any:
        """A redacted copy of data (dicts, lists, text, numbers)."""
        values = set(self._secrets)
        self._collect(data, values)
        ordered = sorted(values, key=len, reverse=True)
        return self._walk(data, ordered)

    def redact_text(self, text: Any) -> Any:
        if not isinstance(text, str):
            return text
        return self._text(text, sorted(self._secrets, key=len, reverse=True))

    def _hides(self, key: Any, value: Any) -> bool:
        return self.is_secret_key(key) and value not in (None, "") and not isinstance(value, bool)

    def _collect(self, data: Any, values: Set[str]) -> None:
        """Values under secret keys, so the same value is also hidden where it appears in other text."""
        if isinstance(data, dict):
            for key, value in data.items():
                if self.is_secret_key(key) and not isinstance(value, (dict, list)):
                    if value is not None and len(str(value).strip()) >= MIN_SECRET_LENGTH:
                        values.add(str(value).strip())
                else:
                    self._collect(value, values)
        elif isinstance(data, list):
            for item in data:
                self._collect(item, values)

    def _walk(self, data: Any, secrets: List[str]) -> Any:
        if isinstance(data, dict):
            return {key: (value if key in KEPT_AS_IS else MASK if self._hides(key, value)
                          else self._walk(value, secrets))
                    for key, value in data.items()}
        if isinstance(data, (list, tuple)):
            return [self._walk(item, secrets) for item in data]
        if isinstance(data, str):
            return self._text(data, secrets)
        if isinstance(data, int) and not isinstance(data, bool):
            # A Thai ID or card number read from a spreadsheet arrives as a number
            text = str(data)
            redacted = self._text(text, secrets)
            return data if redacted == text else redacted
        return data

    def _text(self, text: str, secrets: List[str]) -> str:
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, MASK)
        text = SECRET_PAIR.sub(lambda m: m.group("key") + MASK, text)
        text = DIGITS.sub(_digit_marker, text)
        if self.contacts:
            text = EMAIL.sub("[email]", text)
            text = PHONE.sub("[phone]", text)
        return text


def get_redactor(context: Any) -> Optional[Redactor]:
    """The run's Redactor, which the interpreter stores in the context."""
    try:
        redactor = context.get_variable("__redactor__")
    except AttributeError:
        return None
    return redactor if isinstance(redactor, Redactor) else None


def add_secret(context: Any, value: Any) -> None:
    """For actions: hide a value they handled (such as text typed into a password field) in everything recorded."""
    redactor = get_redactor(context)
    if redactor is not None:
        redactor.add_secret(value)
