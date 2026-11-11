import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from ..env import get_env
from ..models.context import ExecutionContext, StepResult
from .markdown import SECTION_HEADINGS
from .redaction import Redactor
from . import outbox


def resolve_log_dir(log_dir: Optional[Union[str, Path]] = None, flow_path: Optional[Path] = None) -> Path:
    """
    Where run logs go: `log_dir` or KINENIX_LOG_DIR when set; else `logs/` at the root of the git repository
    (or Kinenix checkout) that holds the flow, else `logs/` in the flow's own folder. Without a flow, the same
    search starts from the current folder, so `kinenix run demo` from the home folder does not write ~/logs.
    """
    if log_dir and str(log_dir).strip() not in ["", "logs"]:
        return Path(log_dir).resolve()

    if os.getenv("KINENIX_LOG_DIR"):
        return Path(os.environ["KINENIX_LOG_DIR"]).resolve()

    start = Path(flow_path).resolve() if flow_path else Path.cwd().resolve()
    if flow_path and not start.is_dir():
        start = start.parent
    for p in [start] + list(start.parents):
        if (p / ".git").exists() or (p / "kinenix-core").is_dir():
            return p / "logs"
    return start / "logs"


def _in_section(section: str) -> str:
    """' in On Error' or ' in Finally', so failures outside ## Steps are easy to tell apart in the log."""
    return f" in {SECTION_HEADINGS[section]}" if section in SECTION_HEADINGS and section != "steps" else ""


class ExecutionLogger:
    """
    Structured logger for recording flow execution steps and metrics.
    Prints to console and outputs structured JSON logs.
    """

    def __init__(self, log_dir: Optional[Union[str, Path]] = None, flow_path: Optional[Path] = None):
        self.logger = logging.getLogger("kinenix")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        if not log_dir and "PYTEST_CURRENT_TEST" in os.environ:
            self.log_dir = Path(tempfile.gettempdir()) / "kinenix_test_logs"
        else:
            self.log_dir = resolve_log_dir(log_dir, flow_path=flow_path)

        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

        # Replaced by the interpreter at the start of each top-level run; subflows share it
        self.redactor = Redactor()
        # The run's live log: one JSON line per step, written while the flow runs (${run.log_path})
        self.live_log_path: Optional[Path] = None

    def _run_dir(self, context: ExecutionContext) -> Path:
        flow_slug = re.sub(r"[^\w\-]+", "_", context.flow_name.lower().strip()).strip("_")
        return self.log_dir / flow_slug / context.start_time.strftime("%Y-%m-%d")

    def start_run(self, context: ExecutionContext, run_id: str) -> Optional[Path]:
        """Starts the live log of a top-level run; returns its path, or None without a log folder."""
        self.live_log_path = None
        if not self.log_dir:
            return None
        try:
            target_dir = self._run_dir(context)
            target_dir.mkdir(parents=True, exist_ok=True)
            self.live_log_path = target_dir / f"{context.start_time.strftime('%H%M%S')}_{run_id}.jsonl"
            self.live_log_path.write_text("", encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Failed to start the live log: {e}")
            self.live_log_path = None
        return self.live_log_path

    def _write_live(self, result: StepResult) -> None:
        if not self.live_log_path:
            return
        try:
            line = json.dumps(self.redactor.redact(result.model_dump(mode="json")), ensure_ascii=False, default=str)
            with self.live_log_path.open("a", encoding="utf-8") as live:
                live.write(line + "\n")
        except Exception as e:
            self.logger.error(f"Failed to write the live log: {e}")


    def log_step_start(self, step_id: str, step_name: str, action: str) -> None:
        self.logger.info(f"Starting Step [{step_id}] '{step_name}' (Action: {action})")

    def log_step_result(self, result: StepResult) -> None:
        self._write_live(result)
        if result.status == "success":
            self.logger.info(
                f"Completed Step [{result.step_id}] '{result.step_name}' in {result.duration_seconds:.3f}s"
            )
        elif result.status == "failed":
            self.logger.error(
                f"Failed Step [{result.step_id}] '{result.step_name}'{_in_section(result.section)} - [{result.error_type} Error]: "
                f"{self.redactor.redact_text(result.error_message)}"
            )
        else:
            # A skip is expected behavior (its condition was not met), not a problem to warn about
            reason = (result.output or {}).get("skipped_reason") if isinstance(result.output, dict) else None
            reason = self.redactor.redact_text(reason)
            self.logger.info(f"Skipped Step [{result.step_id}] '{result.step_name}'" + (f": {reason}" if reason else ""))

    def log_execution_summary(self, context: ExecutionContext) -> None:
        m = context.metrics
        self.logger.info("=== Flow Execution Summary ===")
        self.logger.info(f"Flow Name: {context.flow_name}")
        self.logger.info(f"Total Steps: {m.total_steps} (Success: {m.successful_steps}, Failed: {m.failed_steps}, Skipped: {m.skipped_steps})")
        self.logger.info(f"Total Duration: {m.total_duration_seconds:.2f}s")
        details = context.failure_details
        if context.interrupted:
            self.logger.info("Result: INTERRUPTED, stopped on request")
        elif context.has_error and details:
            self.logger.info(f"Result: FAILED at step [{details.failed_step_id}] '{details.failed_step_name}'"
                             f"{_in_section(details.section)}")
        elif context.is_partial:
            items = context.items or {}
            failed = f"{items['failed']} of {items.get('total', 0)} items" if items.get("failed") else f"{m.failed_steps} steps"
            self.logger.info(f"Result: PARTIAL, finished with {failed} failed")

        raw_data = context.model_dump(mode="python")
        raw_data = {"$schema": "../../../schemas/execution_log.schema.json", **raw_data}

        # Filter out internal private runtime variables (e.g. __playwright_*)
        if "variables" in raw_data and isinstance(raw_data["variables"], dict):
            raw_data["variables"] = {
                k: v for k, v in raw_data["variables"].items() if not str(k).startswith("__")
            }

        # Secrets and personal data are removed before anything is written or sent (docs/logging.md, Redaction)
        raw_data = self.redactor.redact(raw_data)

        if self.log_dir:
            try:
                time_str = context.start_time.strftime("%H%M%S")
                status_str = ("interrupted" if context.interrupted else "failed" if context.has_error
                              else "partial" if context.is_partial else "success")

                target_dir = self._run_dir(context)
                target_dir.mkdir(parents=True, exist_ok=True)

                log_file = target_dir / f"{time_str}_{status_str}.json"
                log_file.write_text(json.dumps(raw_data, default=str, indent=2, ensure_ascii=False), encoding="utf-8")
                self.logger.info(f"Saved JSON log to: {log_file}")
            except Exception as e:
                self.logger.error(f"Failed to save JSON execution log: {e}")

        # Send telemetry to the Hub if configured, whether or not a log file is written
        hub_url = (
            context.get_variable("hub_url")
            or context.get_variable("orchestrator_url")  # flow variable name before the rename to Hub
            or context.get_variable("telemetry_url")
            or get_env("KINENIX_HUB_URL")
        )
        if hub_url:
            self._send_telemetry(hub_url, raw_data, context)
        else:
            self.logger.info("Hub: not connected, so this run stays on this machine (kinenix connect URL to report runs).")

    def _send_telemetry(self, hub_url: str, raw_data: dict, context: ExecutionContext) -> None:
        try:
            import requests
            worker_id = (
                context.get_variable("worker_id")
                or os.environ.get("KINENIX_WORKER_ID")
                or "local-worker"
            )
            clean_url = str(hub_url).rstrip("/")
            target_endpoint = f"{clean_url}/api/v1/telemetry"
            # Round-trip through JSON with the same datetime handling as the log file,
            # since requests' json= encoder cannot serialize datetime values
            payload = {
                "worker_id": worker_id,
                "payload": json.loads(json.dumps(raw_data, default=str))
            }
            headers = {}
            api_key = get_env("KINENIX_HUB_API_KEY")
            if api_key:
                headers["X-API-Key"] = api_key
            from ..connect import TIMEOUT
            res = requests.post(target_endpoint, json=payload, headers=headers, timeout=TIMEOUT)
            if res.status_code == 200:
                self.logger.info(f"Transmitted telemetry to Hub: {clean_url}")
                # The Hub answers again: send the runs that could not reach it before (#173)
                outbox.send_pending(clean_url, headers, timeout=TIMEOUT)
                return
            # One warning per failed send; when the run is kept for later, the same warning says so
            later = self._keep_for_later(payload) if outbox.worth_retrying(res.status_code) else ""
            if res.status_code in (401, 403):
                self.logger.warning(
                    f"Hub rejected telemetry (HTTP {res.status_code}). "
                    f"Check that KINENIX_HUB_API_KEY on this worker has the same value as on the Hub.{later}"
                )
            else:
                self.logger.warning(f"Hub returned HTTP {res.status_code}: {res.text}{later}")
        except requests.RequestException as err:
            # Say why in plain words (name not found, Hub not running, firewall), as kinenix connect does
            from ..connect import describe_unreachable
            later = self._keep_for_later(payload) or " The log is kept on this machine."
            self.logger.warning(f"The run was not sent to the Hub. {describe_unreachable(clean_url, err)}{later}")
        except Exception as err:
            self.logger.warning(f"Telemetry transmission to Hub failed: {err}")

    @staticmethod
    def _keep_for_later(payload: dict) -> str:
        """Put the run in the outbox (#173); the text to add to the warning, or "" when it could not be kept."""
        return " The run is kept on this machine and sent when the Hub can be reached again." if outbox.keep(payload) else ""

