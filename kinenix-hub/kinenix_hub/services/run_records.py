"""Run records: the facts of one run as rows that people and AI can query (docs/hub_data.md).

A worker sends one execution log per run (schemas/execution_log.schema.json). The Hub keeps it whole in
`executions.raw_log` and stores its facts as rows:
- `executions.details`: run id, Kinenix version, work items, and a short Markdown run report
- `step_results`: one row per executed step, also inside loops, subflows, On Error, and Finally
- `failures`: one row per failure, also failures the flow continued after

Logs from workers older than 0.2.0b4 have fewer facts; what they lack stays empty. Their step outputs
are not stored, because those workers did not redact them.
"""
import datetime
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import insert, update

from ..models import Execution, Failure, StepResult
from ..timeutils import parse_timestamp

DETAILS_VERSION = 1
# Step outputs and errors are stored this short; the full log stays in executions.raw_log
OUTPUT_LIMIT = 500
REPORT_MESSAGE_LIMIT = 200
REPORT_FAILURES_LIMIT = 10

# The keys each details column may hold; docs/hub_data.md documents each one, and a test keeps them in line
EXECUTION_DETAILS_KEYS = ("v", "run_id", "kinenix_version", "items_total", "items_done", "items_failed",
                          "failure_count", "report_md")
STEP_DETAILS_KEYS = ("v", "line", "path", "subflow", "loop", "retries", "skipped_reason", "error", "output")
FAILURE_DETAILS_KEYS = ("v", "step_id", "section", "exception", "root_cause", "suggested_fix", "path", "subflow",
                        "line", "loop", "retries", "screenshot", "on_error")

HANDLED_WORDS = {"stopped": "run stopped", "continued": "continued", "fallback": "fallback ran",
                 "next_item": "went on with the next item", "ignored": "ignored"}
SECTION_TITLES = {"on_error": "On Error", "finally": "Finally"}


@dataclass
class RunRecords:
    details: Dict[str, Any]
    steps: List[Dict[str, Any]] = field(default_factory=list)
    # Each failure keeps the position of its step in `steps` (or None) until the step rows have ids
    failures: List[Dict[str, Any]] = field(default_factory=list)


def short_text(value: Any, limit: int = OUTPUT_LIMIT) -> Optional[str]:
    """A value as text of at most `limit` characters, ending with ... when it was cut."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def _compact(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _step_row(seq: int, step: Dict[str, Any], keep_output: bool) -> Dict[str, Any]:
    status = _text(step.get("status"))
    output = step.get("output")
    skipped_reason = output.get("skipped_reason") if status == "skipped" and isinstance(output, dict) else None
    details = _compact({
        "v": DETAILS_VERSION,
        "line": _int(step.get("line")),
        "path": _text(step.get("path")),
        "subflow": _text(step.get("subflow")),
        "loop": step.get("loop") if isinstance(step.get("loop"), dict) else None,
        "retries": _int(step.get("retries")),
        "skipped_reason": _text(skipped_reason),
        "error": short_text(step.get("error_message")) if status == "failed" else None,
        "output": short_text(output) if keep_output and status != "skipped" else None,
    })
    return {
        "seq": seq,
        "section": _text(step.get("section")) or "steps",
        "step_id": _text(step.get("step_id")),
        "step_name": _text(step.get("step_name")),
        "action": _text(step.get("action")),
        "status": status,
        "started_at": parse_timestamp(step.get("start_time")),
        "duration_seconds": _float(step.get("duration_seconds")),
        "details": details,
    }


def _section_results(steps: List[Dict[str, Any]], section: str) -> List[Dict[str, Any]]:
    return [{"step_name": s.get("step_name"), "action": s.get("action"), "status": s.get("status")}
            for s in steps if (s.get("section") or "steps") == section]


def _failure_row(step_index: Optional[int], step: Dict[str, Any], failure: Dict[str, Any], handled: Optional[str],
                 run: Dict[str, Any], on_error: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    failed_at = parse_timestamp(step.get("end_time")) or parse_timestamp(step.get("start_time")) or run["ended_at"]
    return {
        "step_index": step_index,
        "failed_at": failed_at,
        "flow_name": run["flow_name"],
        "worker_id": run["worker_id"],
        "step_name": _text(step.get("step_name")),
        "action": _text(step.get("action")),
        "error_type": _text(step.get("error_type")),
        "handled": handled,
        "message": _text(step.get("error_message")),
        "details": _compact({
            "v": DETAILS_VERSION,
            "step_id": _text(step.get("step_id")),
            "section": _text(step.get("section")) or "steps",
            "exception": _text(failure.get("exception")),
            "root_cause": _text(failure.get("root_cause")),
            "suggested_fix": _text(failure.get("suggested_fix")),
            "path": _text(step.get("path")),
            "subflow": _text(step.get("subflow")),
            "line": _int(step.get("line")),
            "loop": step.get("loop") if isinstance(step.get("loop"), dict) else None,
            "retries": _int(step.get("retries")),
            "screenshot": _text(failure.get("screenshot")) or None,
            "on_error": on_error,
        }),
    }


def _failures(steps: List[Dict[str, Any]], payload: Dict[str, Any], run: Dict[str, Any]) -> List[Dict[str, Any]]:
    on_error = _section_results(steps, "on_error") or None
    failure_details = payload.get("failure_details") if isinstance(payload.get("failure_details"), dict) else {}
    has_error = bool(payload.get("has_error"))
    rows: List[Dict[str, Any]] = []
    from_new_worker = any("failure" in s for s in steps)

    if from_new_worker:
        for index, step in enumerate(steps):
            failure = step.get("failure")
            # A flow.call step whose subflow failed: the failure is recorded on the subflow's step
            if step.get("status") != "failed" or not isinstance(failure, dict) or failure.get("from_subflow"):
                continue
            handled = _text(failure.get("handled"))
            rows.append(_failure_row(index, step, failure, handled, run, on_error if handled == "stopped" else None))
    else:
        # Workers older than 0.2.0b4: only the failure that stopped the run is known as such
        failed = [i for i, s in enumerate(steps) if s.get("status") == "failed"]
        stopping = None
        if has_error:
            matching = [i for i in failed if steps[i].get("step_id") == failure_details.get("failed_step_id")]
            stopping = matching[-1] if matching else None
        for index in failed:
            facts = failure_details if index == stopping else {}
            failure = {"exception": facts.get("exception_class"), "root_cause": facts.get("root_cause"),
                       "suggested_fix": facts.get("suggested_fix"), "screenshot": facts.get("error_screenshot_path")}
            rows.append(_failure_row(index, steps[index], failure, "stopped" if index == stopping else None, run, None))

    if has_error and failure_details and not any(r["handled"] == "stopped" for r in rows):
        # The run failed without a failed step to point at, for example a flow that needs a newer Kinenix
        step = {"step_id": failure_details.get("failed_step_id"), "step_name": failure_details.get("failed_step_name"),
                "action": failure_details.get("action"), "error_type": failure_details.get("error_type"),
                "error_message": failure_details.get("error_message"), "section": failure_details.get("section")}
        failure = {"exception": failure_details.get("exception_class"), "root_cause": failure_details.get("root_cause"),
                   "suggested_fix": failure_details.get("suggested_fix"),
                   "screenshot": failure_details.get("error_screenshot_path")}
        rows.append(_failure_row(None, step, failure, "stopped", run, on_error))
    return rows


def _local_start(payload_start: Any, utc_start: Optional[datetime.datetime]) -> str:
    """The start time as the worker saw it, with its UTC offset; UTC when the log has no offset."""
    text = str(payload_start or "").strip()
    try:
        started = datetime.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        if started.tzinfo is not None:
            offset = started.strftime("%z")
            return f"{started:%Y-%m-%d %H:%M} {offset[:3]}:{offset[3:5]}"
    except ValueError:
        pass
    return f"{utc_start:%Y-%m-%d %H:%M} UTC" if utc_start else "unknown time"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def _failure_line(row: Dict[str, Any]) -> str:
    details = row["details"]
    loop = details.get("loop") or {}
    where = []
    if details.get("subflow"):
        where.append(f"subflow {details['subflow']}")
    if details.get("section", "steps") != "steps":
        where.append(f"in {SECTION_TITLES.get(details['section'], details['section'])}")
    if details.get("line"):
        where.append(f"line {details['line']}")
    if details.get("retries"):
        where.append(f"after {details['retries']} retries")
    item = _one_line(loop.get("item"))
    text = f"{item} at " if item else ""
    text += f"\"{row['step_name'] or row['action'] or 'unknown step'}\""
    if where:
        text += f" ({', '.join(where)})"
    if row["handled"]:
        text += f", {HANDLED_WORDS.get(row['handled'], row['handled'])}"
    message = short_text(_one_line(row["message"]), REPORT_MESSAGE_LIMIT)
    return f"- Failed: {text}: {message}" if message else f"- Failed: {text}"


def _section_line(steps: List[Dict[str, Any]], section: str) -> Optional[str]:
    results = _section_results(steps, section)
    if not results:
        return None
    words = {"success": "succeeded", "failed": "failed", "skipped": "skipped"}
    parts = [f"{r['step_name'] or r['action']} {words.get(r['status'], r['status'])}" for r in results]
    return f"- {SECTION_TITLES[section]}: {', '.join(parts)}"


def run_report(payload: Dict[str, Any], run: Dict[str, Any], steps: List[Dict[str, Any]],
               failures: List[Dict[str, Any]]) -> str:
    """A short Markdown report of the run, for people, e-mail, and AI (docs/hub_data.md, Run report)."""
    lines = [f"# {run['flow_name']}, {_local_start(payload.get('start_time'), run['started_at'])} ({run['status']})"]
    worker = [f"Worker: {run['worker_id']}"]
    if payload.get("kinenix_version"):
        worker.append(f"Kinenix {payload['kinenix_version']}")
    worker.append(f"duration {format_duration(run['duration_seconds'])}")
    lines.append("- " + ", ".join(worker))

    items = payload.get("items") if isinstance(payload.get("items"), dict) else None
    if items and _int(items.get("total")):
        total, done, failed = _int(items.get("total")), _int(items.get("done")) or 0, _int(items.get("failed")) or 0
        lines.append(f"- Items: {done} of {total} done, {failed} failed, {max(total - done - failed, 0)} not reached")

    for row in failures[:REPORT_FAILURES_LIMIT]:
        lines.append(_failure_line(row))
    if len(failures) > REPORT_FAILURES_LIMIT:
        lines.append(f"- {len(failures) - REPORT_FAILURES_LIMIT} more failures (see failures)")
    if not failures:
        lines.append("- No failures")

    for section in ("on_error", "finally"):
        line = _section_line(steps, section)
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"


def build_run_records(payload: Dict[str, Any], run: Dict[str, Any]) -> RunRecords:
    """
    The rows for one run. `run` holds what the executions row already says:
    flow_name, worker_id, status, started_at, ended_at (naive UTC), and duration_seconds.
    """
    steps = [s for s in (payload.get("step_results") or []) if isinstance(s, dict)]
    keep_output = bool(payload.get("kinenix_version"))  # workers that redact (0.2.0b4 and newer) send it
    step_rows = [_step_row(seq, step, keep_output) for seq, step in enumerate(steps, start=1)]
    failure_rows = _failures(steps, payload, run)

    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    details = _compact({
        "v": DETAILS_VERSION,
        "run_id": _text(payload.get("run_id")),
        "kinenix_version": _text(payload.get("kinenix_version")),
        "items_total": _int(items.get("total")),
        "items_done": _int(items.get("done")),
        "items_failed": _int(items.get("failed")),
        "failure_count": len(failure_rows),
        "report_md": run_report(payload, run, steps, failure_rows),
    })
    return RunRecords(details=details, steps=step_rows, failures=failure_rows)


def run_status(payload: Dict[str, Any]) -> str:
    """
    failed: the run stopped. partial: it finished, but work items or steps failed on the way (handled by
    on_error: continue or next_item). success: nothing failed (#110); a step with on_error: ignore does not
    count (#197). interrupted: it was stopped on request, which is not a failure, whatever its Finally did (#166).
    """
    if payload.get("interrupted"):
        return "interrupted"
    if payload.get("has_error"):
        return "failed"
    items = payload.get("items") if isinstance(payload.get("items"), dict) else {}
    if (_int(items.get("failed")) or 0) > 0:
        return "partial"
    steps = payload.get("step_results") or []
    if any(isinstance(s, dict) and s.get("status") == "failed"
           and (s.get("failure") or {}).get("handled") != "ignored" for s in steps):
        return "partial"
    return "success"


def execution_run(execution: Any) -> Dict[str, Any]:
    """The `run` facts of build_run_records from an executions row (an Execution or a selected row)."""
    return {
        "flow_name": execution.flow_name,
        "worker_id": execution.worker_id,
        "status": execution.status,
        "started_at": execution.start_time,
        "ended_at": execution.end_time,
        "duration_seconds": execution.duration_seconds or 0.0,
    }


def store_run_records(conn: Any, execution_id: str, records: RunRecords) -> None:
    """
    Writes the step and failure rows and `executions.details`. `conn` is a Session or a Connection,
    so ingestion and the migration that fills in older runs share this code.
    """
    step_ids: List[int] = []
    for row in records.steps:
        result = conn.execute(insert(StepResult.__table__).values(
            execution_id=execution_id, **{**row, "details": json.dumps(row["details"], ensure_ascii=False)}))
        step_ids.append(result.inserted_primary_key[0])
    for row in records.failures:
        values = {k: v for k, v in row.items() if k != "step_index"}
        index = row["step_index"]
        conn.execute(insert(Failure.__table__).values(
            execution_id=execution_id,
            step_result_id=step_ids[index] if index is not None else None,
            **{**values, "details": json.dumps(values["details"], ensure_ascii=False)}))
    conn.execute(update(Execution.__table__).where(Execution.__table__.c.id == execution_id)
                 .values(details=json.dumps(records.details, ensure_ascii=False)))
