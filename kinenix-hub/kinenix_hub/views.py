"""Views over the run records, so people and AI query one flat table instead of JSON (docs/hub_data.md).

Views hold no data, so the Hub drops and creates them at every start instead of changing them through
migrations. Kinenix view names start with `v_`; user views start with `custom_` and come from .sql files
in the user views folder (apply_user_views), so an upgrade never overwrites them.
The views read JSON with SQLite's json_extract; on another database they are not created.
"""
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("kinenix.hub")


def _json(column: str, path: str, name: str) -> str:
    return f"json_extract({column}, '$.{path}') AS {name}"


VIEWS: Dict[str, str] = {
    "v_runs": f"""
SELECT
    e.id AS execution_id,
    {_json("e.details", "run_id", "run_id")},
    e.flow_name,
    e.worker_id,
    e.status,
    e.start_time AS started_at,
    e.end_time AS ended_at,
    e.duration_seconds,
    {_json("e.details", "kinenix_version", "kinenix_version")},
    {_json("e.details", "items_total", "items_total")},
    {_json("e.details", "items_done", "items_done")},
    {_json("e.details", "items_failed", "items_failed")},
    (SELECT COUNT(*) FROM step_results s WHERE s.execution_id = e.id) AS step_count,
    (SELECT COUNT(*) FROM failures f WHERE f.execution_id = e.id) AS failure_count,
    e.failed_step_name,
    e.error_type,
    e.error_message,
    {_json("e.details", "report_md", "report_md")}
FROM executions e
""",  # nosec B608: fixed SQL; _json() takes only the constant names written here
    "v_failures": f"""
SELECT
    f.id AS failure_id,
    f.execution_id,
    {_json("e.details", "run_id", "run_id")},
    f.failed_at,
    f.flow_name,
    f.worker_id,
    {_json("f.details", "section", "section")},
    f.step_name,
    f.action,
    {_json("f.details", "path", "step_path")},
    {_json("f.details", "subflow", "subflow")},
    {_json("f.details", "line", "line")},
    {_json("f.details", "loop.item", "loop_item")},
    {_json("f.details", "loop.index", "loop_index")},
    {_json("f.details", "loop.of", "loop_of")},
    {_json("f.details", "retries", "retries")},
    f.handled,
    f.error_type,
    {_json("f.details", "exception", "exception")},
    f.message,
    {_json("f.details", "root_cause", "root_cause")},
    {_json("f.details", "suggested_fix", "suggested_fix")},
    {_json("f.details", "screenshot", "screenshot")},
    e.status AS run_status
FROM failures f
LEFT JOIN executions e ON e.id = f.execution_id
""",  # nosec B608: fixed SQL
    "v_steps": f"""
SELECT
    s.id AS step_result_id,
    s.execution_id,
    {_json("e.details", "run_id", "run_id")},
    e.flow_name,
    e.worker_id,
    s.seq,
    s.section,
    s.step_id,
    s.step_name,
    s.action,
    s.status,
    s.started_at,
    s.duration_seconds,
    {_json("s.details", "path", "step_path")},
    {_json("s.details", "subflow", "subflow")},
    {_json("s.details", "line", "line")},
    {_json("s.details", "loop.item", "loop_item")},
    {_json("s.details", "loop.index", "loop_index")},
    {_json("s.details", "loop.of", "loop_of")},
    {_json("s.details", "retries", "retries")},
    {_json("s.details", "skipped_reason", "skipped_reason")},
    {_json("s.details", "error", "error")},
    {_json("s.details", "output", "output")}
FROM step_results s
LEFT JOIN executions e ON e.id = s.execution_id
""",  # nosec B608: fixed SQL
    # One row per flow the Hub has a run of. The "last_" columns come from the newest run of the flow.
    "v_flows": """
SELECT
    e.flow_name,
    COUNT(*) AS run_count,
    SUM(CASE WHEN e.status = 'success' THEN 1 ELSE 0 END) AS success_count,
    SUM(CASE WHEN e.status = 'partial' THEN 1 ELSE 0 END) AS partial_count,
    SUM(CASE WHEN e.status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
    SUM(CASE WHEN e.status = 'interrupted' THEN 1 ELSE 0 END) AS interrupted_count,
    COUNT(DISTINCT e.worker_id) AS worker_count,
    MIN(e.start_time) AS first_run_at,
    MAX(e.start_time) AS last_run_at,
    (SELECT l.status FROM executions l WHERE l.flow_name = e.flow_name
     ORDER BY l.start_time DESC, l.created_at DESC LIMIT 1) AS last_status,
    (SELECT l.worker_id FROM executions l WHERE l.flow_name = e.flow_name
     ORDER BY l.start_time DESC, l.created_at DESC LIMIT 1) AS last_worker_id,
    (SELECT l.id FROM executions l WHERE l.flow_name = e.flow_name
     ORDER BY l.start_time DESC, l.created_at DESC LIMIT 1) AS last_execution_id
FROM executions e
GROUP BY e.flow_name
""",  # nosec B608: fixed SQL
}


def create_views(engine: Engine) -> None:
    """Drops and creates the Kinenix views, so they always match this Hub version."""
    if engine.dialect.name != "sqlite":
        logger.warning("Hub views (v_runs, v_failures, v_steps, v_flows) are only created on SQLite.")
        return
    with engine.begin() as conn:
        for name, select in VIEWS.items():
            conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
            conn.execute(text(f"CREATE VIEW {name} AS {select.strip()}"))


USER_VIEW_PREFIX = "custom_"
_USER_VIEW_NAME = re.compile(r"^custom_\w+$")


def apply_user_views(engine: Engine, folder: Optional[Path]) -> List[Tuple[str, str]]:
    """
    Creates a view for each custom_*.sql file in `folder` (the file holds one SELECT; the view takes the
    file's name) and drops custom_ views whose file is gone. A view that fails is logged with its file
    name and skipped; the Hub keeps starting. Returns (file name, error) for each failure.
    """
    if engine.dialect.name != "sqlite":
        return []
    files = {}
    failures: List[Tuple[str, str]] = []
    if folder and folder.is_dir():
        for path in sorted(folder.glob("*.sql")):
            if _USER_VIEW_NAME.match(path.stem):
                files[path.stem] = path
            else:
                failures.append((path.name, f"user view names must start with {USER_VIEW_PREFIX} (letters, digits, _)"))

    with engine.begin() as conn:
        existing = [row[0] for row in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'view' AND name GLOB 'custom_*'"))]
        for name in existing:
            if name not in files:
                conn.execute(text(f'DROP VIEW "{name}"'))

    # A view may read another user view, so views that fail are tried again while others still succeed
    pending = dict(files)
    errors: Dict[str, str] = {}
    while pending:
        created = []
        for name, path in pending.items():
            select = path.read_text(encoding="utf-8-sig").strip().rstrip(";").strip()
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'DROP VIEW IF EXISTS "{name}"'))
                    conn.exec_driver_sql(f'CREATE VIEW "{name}" AS {select}')
                    conn.exec_driver_sql(f'SELECT * FROM "{name}" LIMIT 0')  # nosec B608: name matches custom_\w+
                created.append(name)
            except Exception as e:  # any SQL error in a user's file
                errors[name] = str(getattr(e, "orig", None) or e).splitlines()[0]
        for name in created:
            pending.pop(name)
            errors.pop(name, None)
        if not created:
            break

    failures += [(files[name].name, errors[name]) for name in pending]
    for file_name, error in failures:
        logger.warning(f"User view {file_name} was not created: {error}")
    return failures
