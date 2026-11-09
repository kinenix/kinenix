import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from kinenix.engine.stopping import stop_requested

from ..runner import WorkerRunner

logger = logging.getLogger("kinenix_worker.trigger.watcher")


class FileWatcherTrigger:
    """
    Watches a target directory for new or modified files matching a pattern.
    When a file appears, it waits for file stabilization (size stability)
    and dispatches a flow bundle via WorkerRunner.
    """

    def __init__(
        self,
        watch_dir: str,
        flow_path: str,
        pattern: str = "*.*",
        poll_interval: float = 2.0,
        stabilization_wait: float = 0.5,
        use_sandbox: bool = False,
        extra_vars: Optional[Dict[str, Any]] = None,
        runner: Optional[WorkerRunner] = None,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.watch_dir = Path(watch_dir).resolve()
        self.flow_path = flow_path
        self.pattern = pattern
        self.poll_interval = poll_interval
        self.stabilization_wait = stabilization_wait
        self.use_sandbox = use_sandbox
        self.extra_vars = extra_vars or {}
        self.runner = runner or WorkerRunner()
        self.callback = callback

        # Track processed files: path -> (mtime, size)
        self._processed_files: Dict[Path, float] = {}

    def _is_file_stable(self, file_path: Path) -> bool:
        """
        Checks if file writing is complete by observing size changes.
        """
        try:
            initial_size = file_path.stat().st_size
            if self.stabilization_wait > 0:
                time.sleep(self.stabilization_wait)
                current_size = file_path.stat().st_size
                return initial_size == current_size
            return True
        except Exception:
            return False

    def scan_once(self) -> List[Dict[str, Any]]:
        """
        Performs a single scan pass over the watch directory.
        Returns a list of execution results for any newly triggered files.
        """
        if not self.watch_dir.is_dir():
            self.watch_dir.mkdir(parents=True, exist_ok=True)

        results = []
        matching_files = sorted(self.watch_dir.glob(self.pattern))

        for file_path in matching_files:
            if not file_path.is_file():
                continue

            mtime = file_path.stat().st_mtime
            prev_mtime = self._processed_files.get(file_path)

            # Skip if already processed and unmodified
            if prev_mtime is not None and prev_mtime >= mtime:
                continue

            # Check stabilization
            if not self._is_file_stable(file_path):
                continue

            logger.info(f"File watcher detected new file: {file_path}. Triggering flow: {self.flow_path}")

            if stop_requested():
                break  # The files left are found again at the next start

            injected_vars = dict(self.extra_vars)
            injected_vars["trigger_file_path"] = str(file_path.resolve())
            injected_vars["trigger_file_name"] = file_path.name
            injected_vars["trigger_timestamp"] = datetime.now().isoformat()

            try:
                res = self.runner.execute_flow(
                    flow_path_or_alias=self.flow_path,
                    extra_vars=injected_vars,
                    use_sandbox=self.use_sandbox
                )
                self._processed_files[file_path] = mtime
                results.append(res)
                if self.callback:
                    self.callback(res)
            except Exception as e:
                logger.error(f"Execution failed for triggered file '{file_path}': {e}")
                self._processed_files[file_path] = mtime
                results.append({"status": "failed", "error": str(e), "file": str(file_path)})

        return results

    def run_loop(self, stop_event: Optional[Any] = None) -> None:
        """
        Runs the watcher continuously until stop_event is set or KeyboardInterrupt.
        """
        logger.info(f"Starting file watcher on: {self.watch_dir} (pattern: {self.pattern})")
        while True:
            if stop_event and getattr(stop_event, "is_set", lambda: False)():
                logger.info("File watcher received stop event. Terminating loop.")
                break
            try:
                self.scan_once()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("File watcher stopped by user.")
                break
            except Exception as e:
                logger.error(f"Unexpected error in file watcher scan: {e}")
                time.sleep(self.poll_interval)
