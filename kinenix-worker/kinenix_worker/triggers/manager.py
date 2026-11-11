import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from kinenix.engine.stopping import clear_stop, install_signal_handlers, request_stop, stop_requested

from .watcher import FileWatcherTrigger
from .scheduler import CronSchedulerTrigger
from ..runner import WorkerRunner

logger = logging.getLogger("kinenix_worker.trigger.manager")

# How long a stopping daemon waits for running flows, Finally included; below systemd's 90 seconds before SIGKILL
STOP_WAIT_SECONDS = 60


def _flag(value: Any, name: str) -> bool:
    """A true/false setting of a trigger; the text "false" would otherwise count as true."""
    if isinstance(value, bool):
        return value
    raise ValueError(f"'{name}' in triggers.json must be true or false, not {json.dumps(value)}")


class TriggerManager:
    """
    Manages multiple concurrent triggers (file watchers, schedulers).
    Can be configured programmatically or loaded from a triggers configuration file.
    """

    def __init__(self, runner: Optional[WorkerRunner] = None):
        self.runner = runner or WorkerRunner()
        self.triggers: List[Any] = []
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

    def add_trigger(self, trigger: Any) -> None:
        self.triggers.append(trigger)

    def load_from_config(self, config_path: str) -> None:
        p = Path(config_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Triggers configuration file not found: {p}")

        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            trigger_list = data.get("triggers", [])
        elif isinstance(data, list):
            trigger_list = data
        else:
            raise ValueError("Triggers configuration must be a list or a dict with a 'triggers' array.")

        for item in trigger_list:
            t_type = item.get("type", "").lower()
            flow = item.get("flow") or item.get("flow_path")
            if not flow:
                logger.warning(f"Skipping trigger without flow: {item}")
                continue

            if t_type in ("file_watcher", "watcher", "file"):
                watch_dir = item.get("watch_dir") or item.get("directory", ".")
                pattern = item.get("pattern", "*.*")
                interval = float(item.get("interval", 2.0))
                self.add_trigger(
                    FileWatcherTrigger(
                        watch_dir=watch_dir,
                        flow_path=flow,
                        pattern=pattern,
                        poll_interval=interval,
                        runner=self.runner,
                        extra_vars=item.get("vars", {})
                    )
                )
            elif t_type in ("scheduler", "cron", "interval"):
                sec = float(item.get("interval_seconds") or item.get("interval", 60.0))
                self.add_trigger(
                    CronSchedulerTrigger(
                        flow_path=flow,
                        interval_seconds=sec,
                        runner=self.runner,
                        extra_vars=item.get("vars", {}),
                        cron=item.get("cron"),  # e.g. "0 8 1 * *"; an invalid expression stops the daemon at load
                        run_at_start=_flag(item.get("run_at_start", True), "run_at_start")
                    )
                )
            else:
                logger.warning(f"Unknown trigger type '{t_type}', skipping.")

    def start_all(self, blocking: bool = True) -> None:
        self._stop_event.clear()
        self._threads = []

        for trigger in self.triggers:
            t = threading.Thread(target=trigger.run_loop, args=(self._stop_event,), daemon=True)
            t.start()
            self._threads.append(t)

        logger.info(f"Started {len(self._threads)} triggers in background daemon.")

        if blocking:
            install_signal_handlers()
            try:
                while not self._stop_event.is_set() and not stop_requested():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            logger.info("Trigger manager received shutdown signal.")
            self.stop()

    def stop(self) -> None:
        """Starts no new run, and waits for the running flows to stop and run their Finally."""
        self._stop_event.set()
        request_stop()
        deadline = time.monotonic() + STOP_WAIT_SECONDS
        for t in self._threads:
            t.join(timeout=max(0.0, deadline - time.monotonic()))
        running = sum(t.is_alive() for t in self._threads)
        if running:
            logger.warning(f"{running} flow(s) still running after {STOP_WAIT_SECONDS} seconds; stopping without them.")
        clear_stop()
        logger.info("All triggers stopped.")
