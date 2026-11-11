"""Connection from a worker to the Kinenix Hub: heartbeats and connection checks.

Configuration comes from the same environment variables kinenix-core uses for telemetry:
    KINENIX_HUB_URL             Hub base URL; heartbeats are disabled when unset
    KINENIX_HUB_API_KEY         sent as X-API-Key
    KINENIX_WORKER_ID           worker identifier; defaults to the host name
    KINENIX_HEARTBEAT_INTERVAL  seconds between heartbeats while a worker command runs (default 30)

The pre-rename names KINENIX_ORCHESTRATOR_URL and KINENIX_ORCHESTRATOR_API_KEY still work, with a warning.

Network failures never stop the worker; they are logged once and again when the connection recovers.
"""
import logging
import os
import platform
import socket
import threading
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import psutil
import requests
from kinenix.engine import outbox
from kinenix.env import get_env

logger = logging.getLogger("kinenix_worker.hub")

DEFAULT_HEARTBEAT_INTERVAL = 30.0
REQUEST_TIMEOUT = 5.0


def resolve_worker_id() -> str:
    return os.environ.get("KINENIX_WORKER_ID") or socket.gethostname()


def _local_ip(target_url: str) -> str:
    """IP address of the interface used to reach the Hub (no packets are sent)."""
    host = urlparse(target_url).hostname or "8.8.8.8"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((host, 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class HubClient:
    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        raw_url = url if url is not None else get_env("KINENIX_HUB_URL")
        self.url = raw_url.rstrip("/")
        self.api_key = api_key if api_key is not None else get_env("KINENIX_HUB_API_KEY")
        self.worker_id = worker_id or resolve_worker_id()
        self.current_task: Optional[str] = None
        self._lock = threading.Lock()
        self._last_ok: Optional[bool] = None
        self._ip_address: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    @property
    def ip_address(self) -> str:
        # Resolved once: the lookup may hit DNS, and the interface rarely changes
        if self._ip_address is None:
            self._ip_address = _local_ip(self.url)
        return self._ip_address

    def heartbeat_payload(self) -> Dict[str, Any]:
        vm = psutil.virtual_memory()
        return {
            "worker_id": self.worker_id,
            "name": socket.gethostname(),
            "ip_address": self.ip_address,
            "os_info": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_usage": f"{vm.used / 1024 ** 3:.1f} / {vm.total / 1024 ** 3:.1f} GB",
            "current_task": self.current_task,
        }

    def send_heartbeat(self) -> bool:
        """Send one heartbeat. Returns True on success; never raises."""
        if not self.enabled:
            return False
        with self._lock:
            try:
                res = requests.post(
                    f"{self.url}/api/v1/heartbeat",
                    json=self.heartbeat_payload(),
                    headers=self._headers(),
                    timeout=REQUEST_TIMEOUT,
                )
                ok = res.status_code == 200
                problem = None if ok else f"HTTP {res.status_code}"
                if res.status_code in (401, 403):
                    problem += " (check KINENIX_HUB_API_KEY)"
            except requests.RequestException as e:
                ok, problem = False, str(e)

            # Log only on state changes so an unreachable Hub does not flood the log
            if not ok and self._last_ok is not False:
                logger.warning(f"Heartbeat to Hub {self.url} failed: {problem}")
            elif ok and self._last_ok is False:
                logger.info(f"Heartbeat to Hub {self.url} recovered")
            self._last_ok = ok
        if ok:
            # Runs that could not reach the Hub go now, without waiting for the next run (#173)
            outbox.send_pending(self.url, self._headers(), timeout=REQUEST_TIMEOUT)
        return ok

    def set_task(self, task: Optional[str]) -> None:
        """Record the running flow (None when idle) and report it immediately."""
        self.current_task = task
        self.send_heartbeat()

    def ping(self) -> Dict[str, Any]:
        """Check reachability and the API key. Returns {"reachable", "authorized", "detail"}."""
        if not self.enabled:
            return {"reachable": False, "authorized": False, "detail": "KINENIX_HUB_URL is not set"}
        try:
            health = requests.get(f"{self.url}/api/v1/healthz", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            return {"reachable": False, "authorized": False, "detail": f"Cannot reach {self.url}: {e}"}
        if health.status_code != 200:
            return {"reachable": False, "authorized": False, "detail": f"Health check returned HTTP {health.status_code}"}

        try:
            res = requests.post(
                f"{self.url}/api/v1/heartbeat",
                json=self.heartbeat_payload(),
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as e:
            return {"reachable": True, "authorized": False, "detail": f"Heartbeat failed: {e}"}
        if res.status_code == 200:
            return {"reachable": True, "authorized": True, "detail": "Heartbeat accepted"}
        if res.status_code in (401, 403):
            return {"reachable": True, "authorized": False,
                    "detail": f"HTTP {res.status_code}: KINENIX_HUB_API_KEY on this worker does not match the Hub's key"}
        return {"reachable": True, "authorized": False, "detail": f"Heartbeat returned HTTP {res.status_code}"}


class HeartbeatThread(threading.Thread):
    """Sends a heartbeat at a fixed interval until stopped."""

    def __init__(self, client: HubClient, interval: Optional[float] = None):
        super().__init__(name="kinenix-heartbeat", daemon=True)
        self.client = client
        self.interval = interval or float(os.environ.get("KINENIX_HEARTBEAT_INTERVAL", DEFAULT_HEARTBEAT_INTERVAL))
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.client.send_heartbeat()
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()
