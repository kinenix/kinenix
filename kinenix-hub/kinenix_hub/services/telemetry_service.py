import datetime
import json
import logging
import math
from typing import Any, Dict, List, Optional
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from ..models import Execution, Worker
from ..timeutils import parse_timestamp, utc_now
from .run_records import build_run_records, execution_run, run_status, store_run_records

logger = logging.getLogger("kinenix.hub.telemetry")


def record_heartbeat(
    db: Session,
    worker_id: str,
    name: str,
    ip_address: str,
    os_info: str,
    cpu_percent: float,
    ram_usage: str,
    current_task: str = None
) -> Worker:
    worker = db.query(Worker).filter(Worker.id == worker_id).first()
    if not worker:
        worker = Worker(id=worker_id, name=name)
        db.add(worker)

    worker.name = name
    worker.ip_address = ip_address
    worker.os_info = os_info
    worker.cpu_percent = cpu_percent
    worker.ram_usage = ram_usage
    worker.current_task = current_task
    worker.status = "busy" if current_task else "online"
    worker.last_heartbeat = utc_now()
    db.commit()
    db.refresh(worker)
    return worker


# Step fields safe to show in the dashboard and CLI. Step output and flow variables are left out
# because they can carry business data (form values, extracted documents, credentials in URLs).
# root_cause and suggested_fix are the worker's diagnosis of a failed step, item its loop item's label (#111).
STEP_FIELDS = ("step_id", "step_name", "action", "status", "start_time", "end_time",
               "duration_seconds", "error_type", "error_message", "root_cause", "suggested_fix", "item")


def _step_summary(step: Dict[str, Any]) -> Dict[str, Any]:
    failure = step.get("failure") if isinstance(step.get("failure"), dict) else {}
    loop = step.get("loop") if isinstance(step.get("loop"), dict) else {}
    derived = {"root_cause": failure.get("root_cause"), "suggested_fix": failure.get("suggested_fix"),
               "item": loop.get("item")}
    return {field: derived[field] if field in derived else step.get(field) for field in STEP_FIELDS}


def step_summaries(raw_log: Optional[str]) -> List[Dict[str, Any]]:
    """Per-step results from a stored execution log, reduced to STEP_FIELDS. Empty if unavailable."""
    if not raw_log:
        return []
    try:
        steps = json.loads(raw_log).get("step_results") or []
    except (ValueError, AttributeError):
        return []
    return [_step_summary(step) for step in steps if isinstance(step, dict)]


def _duration_seconds(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        logger.warning("Invalid total_duration_seconds in telemetry; storing 0.0")
        return 0.0
    if not math.isfinite(seconds) or seconds < 0.0:
        logger.warning("Invalid total_duration_seconds in telemetry; storing 0.0")
        return 0.0
    return seconds


def _run_id(payload: Dict[str, Any]) -> Optional[str]:
    """The id that makes a run unique for its worker; logs from older workers have none."""
    run_id = payload.get("run_id")
    return run_id if isinstance(run_id, str) and 0 < len(run_id) <= 64 else None


def _stored_run(db: Session, worker_id: str, run_id: Optional[str]) -> Optional[Execution]:
    if not run_id:
        return None
    return db.query(Execution).filter(Execution.worker_id == worker_id, Execution.run_id == run_id).first()


def ingest_execution_log(db: Session, payload: Dict[str, Any], worker_id: str = "local-worker") -> Execution:
    run_id = _run_id(payload)
    stored = _stored_run(db, worker_id, run_id)
    if stored:
        logger.info(f"Run {run_id} of {worker_id} is already stored; nothing changed")
        return stored
    # End the transaction of that check: the failure analysis below may wait seconds for the central
    # LLM, and a write session must not hold the database's write lock meanwhile (#201)
    db.rollback()

    flow_name = payload.get("flow_name", "Unknown Flow")
    has_error = bool(payload.get("has_error", False))
    failure_details = payload.get("failure_details") or {}
    raw_metrics = payload.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}

    start_time_str = payload.get("start_time")
    end_time_str = payload.get("end_time")

    duration = _duration_seconds(metrics.get("total_duration_seconds", 0.0))

    # Execution logs from kinenix-core carry start_time and a duration but no end_time
    start_time = parse_timestamp(start_time_str) or utc_now()
    end_time = parse_timestamp(end_time_str)
    if end_time is None:
        try:
            end_time = start_time + datetime.timedelta(seconds=duration)
        except OverflowError:
            logger.warning("total_duration_seconds exceeds the supported timestamp range; storing 0.0")
            duration = 0.0
            end_time = start_time

    execution = Execution(
        worker_id=worker_id,
        run_id=run_id,
        flow_name=flow_name,
        status=run_status(payload),
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration,
        has_error=has_error,
        raw_log=json.dumps(payload, ensure_ascii=False)
    )

    if has_error:
        execution.failed_step_id = failure_details.get("failed_step_id")
        execution.failed_step_name = failure_details.get("failed_step_name")
        execution.error_type = failure_details.get("error_type")
        execution.exception_class = failure_details.get("exception_class")
        execution.error_message = failure_details.get("error_message")
        # Workers send error_screenshot_path (schemas/execution_log.schema.json); screenshot_path is the older name
        execution.screenshot_path = failure_details.get("error_screenshot_path") or failure_details.get("screenshot_path")

    db.add(execution)
    try:
        db.flush()
    except IntegrityError:
        # The same run arrived at the same moment; the first one is the record
        db.rollback()
        stored = _stored_run(db, worker_id, run_id)
        if stored is None:
            raise
        return stored
    # Steps, failures, and the run report as queryable rows (docs/hub_data.md)
    store_run_records(db, execution.id, build_run_records(payload, execution_run(execution)))
    db.commit()
    db.refresh(execution)

    # Update worker's current task. The run is already stored, so a failure here must not answer
    # the worker with an error that makes it think the run was lost
    try:
        worker = db.query(Worker).filter(Worker.id == worker_id).first()
        if worker:
            worker.current_task = None
            worker.status = "online"
            db.commit()
    except OperationalError as e:
        db.rollback()
        logger.warning(f"Run {run_id} of {worker_id} is stored, but the worker's status was not updated: {e}")

    return execution

