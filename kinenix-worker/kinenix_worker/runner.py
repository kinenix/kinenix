import json
import logging
import platform
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
from kinenix import exit_codes
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import load_flow, markdown_issues
from kinenix.engine.validation import validate_flow, validate_subflows

from .hub_client import HubClient

logger = logging.getLogger("kinenix_worker")


class WorkerRunner:
    """
    Execution engine for unattended worker nodes (e.g. Raspberry Pi, VMs).
    Handles bundle resolution, sandbox workspace isolation, and execution telemetry.
    """

    def __init__(self, client: Optional[HubClient] = None):
        self.client = client or HubClient()

    @staticmethod
    def get_system_info() -> Dict[str, Any]:
        vm = psutil.virtual_memory()
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "machine": platform.machine(),  # e.g., aarch64 on Raspberry Pi
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "cpu_count": psutil.cpu_count(logical=True),
            "memory_total_mb": round(vm.total / (1024 * 1024), 1),
            "memory_available_mb": round(vm.available / (1024 * 1024), 1),
            "memory_used_percent": vm.percent,
        }

    def execute_flow(
        self,
        flow_path_or_alias: str,
        extra_vars: Optional[Dict[str, Any]] = None,
        use_sandbox: bool = False,
        log_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        target_path = Path(flow_path_or_alias).resolve()
        if not target_path.exists():
            # A bare name such as "get_stock_data" is looked up like `kinenix run` does, including the flows folder
            from kinenix.cli import resolve_flow_path
            found = resolve_flow_path(str(flow_path_or_alias))
            if found:
                target_path = found
        if target_path.is_dir():
            for name in ("flow.md", "flow.json"):  # a lone flow.json is reported with how to convert it
                if (target_path / name).is_file():
                    target_path = target_path / name
                    break

        if not target_path.is_file():
            raise FileNotFoundError(f"Flow file not found at: {flow_path_or_alias}")

        flow_dir = target_path.parent
        work_dir = flow_dir
        # Logs stay with the original bundle, also when the run uses a --sandbox copy
        original_path = target_path
        job_id = f"job_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        if use_sandbox:
            sandbox_dir = Path.home() / ".kinenix" / "workspaces" / job_id
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(flow_dir, sandbox_dir, dirs_exist_ok=True)
            work_dir = sandbox_dir
            target_path = sandbox_dir / target_path.name

        flow_def = load_flow(target_path)
        hints = []
        issues = (markdown_issues(target_path.read_text(encoding="utf-8-sig"))
                  + validate_flow(flow_def, work_dir, hints) + validate_subflows(flow_def, work_dir, hints=hints))
        for issue in issues:
            logger.warning(issue)
        for hint in hints:
            logger.info(f"Hint: {hint}")

        # Auto-load config.json if present in the bundle directory
        config_file = work_dir / "config" / "config.json"
        if not config_file.is_file():
            config_file = work_dir / "config.json"
        if config_file.is_file():
            try:
                cfg_data = json.loads(config_file.read_text(encoding="utf-8-sig"))
                flow_def.variables.setdefault("config", {})
                if isinstance(flow_def.variables["config"], dict) and isinstance(cfg_data, dict):
                    flow_def.variables["config"].update(cfg_data)
            except Exception as e:
                logger.warning(f"Could not load bundle config file: {e}")

        # Inject runtime environment variables and worker system info
        system_info = self.get_system_info()
        flow_def.variables["__worker_info__"] = system_info
        flow_def.variables["__job_id__"] = job_id
        flow_def.variables["__flow_dir__"] = str(work_dir)

        if extra_vars:
            flow_def.variables.update(extra_vars)
        # Telemetry from kinenix-core uses the same identifier as this worker's heartbeats
        flow_def.variables.setdefault("worker_id", self.client.worker_id)

        actual_log_dir = Path(log_dir) if log_dir else None
        exec_logger = ExecutionLogger(log_dir=actual_log_dir, flow_path=original_path)

        interpreter = FlowInterpreter(logger=exec_logger)

        start_time = time.time()
        self.client.set_task(flow_def.name)
        try:
            ctx = interpreter.run_flow(flow_def, initial_vars={"__flow_dir__": str(work_dir)})
        finally:
            self.client.set_task(None)
            if use_sandbox:
                self._remove_secrets(work_dir)
        duration = round(time.time() - start_time, 2)

        result = {
            "job_id": job_id,
            "flow_name": flow_def.name,
            "status": ("interrupted" if ctx.interrupted else "failed" if ctx.has_error
                       else "partial" if ctx.is_partial else "success"),
            "duration_seconds": duration,
            "steps_total": len(flow_def.steps),
            # Top-level steps only, to match steps_total; loop iterations would otherwise give e.g. "40/20"
            "steps_executed": len({r.step_id for r in ctx.step_results} & {s.id for s in flow_def.steps}),
            "has_error": ctx.has_error,
            "exit_code": exit_codes.for_run(ctx),
            "run_id": (ctx.get_variable("run") or {}).get("id"),
            "error": self._error_summary(ctx),
            "worker_system": system_info
        }

        return result

    @staticmethod
    def _remove_secrets(copy_dir: Path) -> None:
        """
        Deletes the .env files of a --sandbox copy once its run is over, so passwords do not pile up in
        ~/.kinenix/workspaces (docs/design/threat-model.md, T12). The run read them at its start; the
        flow's outputs in the copy are kept.
        """
        for env_file in copy_dir.rglob(".env*"):
            name = env_file.name
            if env_file.is_file() and (name == ".env" or name.startswith(".env.")) and name != ".env.example":
                try:
                    env_file.unlink()
                except OSError as e:
                    logger.warning(f"The run's copy still has {env_file}, which could not be removed: {e}")

    @staticmethod
    def _error_summary(ctx: Any) -> Optional[str]:
        if not ctx.has_error:
            return None
        details = ctx.failure_details
        if details is None:
            return "Flow failed without failure details"
        return f"Step '{details.failed_step_name}' ({details.error_type}): {details.error_message}"
