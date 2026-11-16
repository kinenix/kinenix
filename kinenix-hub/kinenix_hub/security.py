import hashlib
import ipaddress
import logging
import secrets
import socket
from typing import Dict, Optional, Set

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials

from . import config
from .settings_file import verify_password

logger = logging.getLogger("kinenix.hub.security")

API_KEY_HEADER_NAME = "X-API-Key"
DASHBOARD_REALM = "Kinenix Hub"

_api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)
_basic_auth = HTTPBasic(auto_error=False, realm=DASHBOARD_REALM)


def _is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _secret_equals(provided: Optional[str], expected: str) -> bool:
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


# Fingerprint of the last password that matched the saved hash. The dashboard polls the API, and
# running PBKDF2 on every request would make it slow; the plaintext password is never kept.
_verified_password: Dict[str, bytes] = {}


def _dashboard_password_matches(provided: Optional[str]) -> bool:
    if config.DASHBOARD_PASSWORD:
        return _secret_equals(provided, config.DASHBOARD_PASSWORD)
    if provided is None:
        return False
    stored_hash = config.DASHBOARD_PASSWORD_HASH
    fingerprint = hashlib.sha256(f"{stored_hash}:{provided}".encode("utf-8")).digest()
    cached = _verified_password.get(stored_hash)
    if cached is not None and secrets.compare_digest(cached, fingerprint):
        return True
    if verify_password(provided, stored_hash):
        _verified_password.clear()
        _verified_password[stored_hash] = fingerprint
        return True
    return False


def _local_names() -> Set[str]:
    """Host names a browser or worker on this machine uses for a Hub that needs no key or password."""
    names = {"localhost", "127.0.0.1", "::1"}
    hostname = socket.gethostname().lower()
    names |= {hostname, f"{hostname}.local", socket.getfqdn().lower()}
    return names


def _request_host(request: Request) -> str:
    """The Host header without its port: `[::1]:8080` -> `::1`, `localhost:8080` -> `localhost`."""
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host.rstrip(".")  # "localhost." is the same name


def _allow_loopback_only(request: Request, setting_name: str) -> None:
    client_host = request.client.host if request.client else None
    if _is_loopback(client_host):
        # A web page whose own name was made to resolve to this machine (DNS rebinding) also connects from
        # localhost, but its requests carry its own name as Host: it must not read or send runs without the
        # key or password (docs/design/threat-model.md, T4)
        host = _request_host(request)
        if host in _local_names():
            return
        logger.warning(f"Rejected request for Host '{host}' from this machine: {setting_name} is not configured.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Open the Hub as http://localhost or http://127.0.0.1, or set {setting_name} on the Hub.",
        )
    logger.warning(f"Rejected request from {client_host}: {setting_name} is not configured.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Remote access is disabled. Set {setting_name} on the Hub to allow remote access.",
    )


def require_worker_api_key(
    request: Request,
    api_key: Optional[str] = Security(_api_key_header),
) -> None:
    """
    Guards worker-facing write endpoints (heartbeat, telemetry).

    - KINENIX_HUB_API_KEY set: every request must send a matching X-API-Key header.
    - KINENIX_HUB_API_KEY unset (local dev mode): only loopback clients are accepted,
      so an unconfigured server bound to the network (e.g. 0.0.0.0) is never writable remotely.
    """
    expected_key = config.API_KEY

    if not expected_key:
        _allow_loopback_only(request, "KINENIX_HUB_API_KEY")
        return

    if not _secret_equals(api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def require_dashboard_auth(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Security(_basic_auth),
) -> None:
    """
    Guards the dashboard page and its read endpoints with HTTP Basic Auth.

    - KINENIX_HUB_DASHBOARD_PASSWORD set: every request must send matching Basic credentials.
      Browsers show a login prompt and reuse the credentials for the dashboard's API calls.
    - KINENIX_HUB_DASHBOARD_PASSWORD unset (local dev mode): only loopback clients are accepted.
    """
    if not config.dashboard_password_required():
        _allow_loopback_only(request, "KINENIX_HUB_DASHBOARD_PASSWORD")
        return

    # Evaluate both comparisons so the response time does not reveal which one failed
    user_ok = _secret_equals(credentials.username if credentials else None, config.DASHBOARD_USER)
    password_ok = _dashboard_password_matches(credentials.password if credentials else None)
    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing dashboard credentials.",
            headers={"WWW-Authenticate": f'Basic realm="{DASHBOARD_REALM}"'},
        )


def log_auth_mode() -> None:
    config.log_legacy_names()
    if config.API_KEY:
        logger.info(f"Worker API key authentication enabled ({API_KEY_HEADER_NAME} header required).")
    else:
        logger.warning(
            "KINENIX_HUB_API_KEY is not set: worker endpoints accept requests from localhost only. "
            "Set KINENIX_HUB_API_KEY to allow remote workers."
        )

    if config.dashboard_password_required():
        logger.info(f"Dashboard authentication enabled (user '{config.DASHBOARD_USER}').")
    else:
        logger.warning(
            "KINENIX_HUB_DASHBOARD_PASSWORD is not set: the dashboard is available from localhost only. "
            "Set KINENIX_HUB_DASHBOARD_PASSWORD to allow remote viewers."
        )
