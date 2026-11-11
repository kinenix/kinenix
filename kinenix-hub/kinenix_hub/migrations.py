"""Schema changes for an existing Hub database, applied in order when the Hub starts.

`Base.metadata.create_all` creates tables that do not exist yet, but it never changes a table that
already exists (for example adding a column to `executions` in a hub.db created by an older Hub).
Those changes are migrations: numbered steps, applied once each and recorded in `schema_version`.

Rules for writing a migration:
- Append to MIGRATIONS with the next number; never renumber or edit a released migration.
- Make each step safe to run on a database that already has the change (use the helpers below),
  because a new database gets every table and column from create_all before the migrations run.
- Keep the SQL portable between SQLite and PostgreSQL where possible.
No third-party migration tool is used, so the Hub has no extra dependency.
"""
import json
import logging
import weakref
from datetime import datetime, timezone
from typing import Callable, List, NamedTuple

from sqlalchemy import event, inspect, select, text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger("kinenix.hub")

_transactional_engines: "weakref.WeakSet[Engine]" = weakref.WeakSet()

# Execution option of the engine behind write sessions (database.WriteSessionLocal)
WRITE_OPTION = "kinenix_write"


def make_sqlite_transactional(engine: Engine) -> None:
    """
    Python's sqlite3 module commits ALTER TABLE and other DDL at once, outside the transaction, so a
    migration that fails halfway would leave half its changes behind. SQLAlchemy's documented fix:
    let SQLAlchemy emit BEGIN itself. Safe to call more than once.
    """
    if engine.dialect.name != "sqlite" or engine in _transactional_engines:
        return

    @event.listens_for(engine, "connect")
    def _no_driver_transactions(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn):
        # A session that will write takes the write lock at its first statement (#201). With a plain
        # BEGIN, a transaction that reads and then writes fails at once with "database is locked" when
        # another connection wrote in between: SQLite cannot wait for it, so busy_timeout does not help.
        conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.get_execution_options().get(WRITE_OPTION) else "BEGIN")

    _transactional_engines.add(engine)
    engine.dispose()  # pooled connections were opened before the listeners existed


class Migration(NamedTuple):
    number: int
    name: str
    apply: Callable[[Connection], None]


def add_column_if_missing(conn: Connection, table: str, column: str, ddl_type: str) -> None:
    """ALTER TABLE ... ADD COLUMN, skipped when the column exists (for example from create_all)."""
    existing = {c["name"] for c in inspect(conn).get_columns(table)}
    if column not in existing:
        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'))


def create_index_if_missing(conn: Connection, name: str, table: str, columns: str) -> None:
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))


def _baseline(conn: Connection) -> None:
    """The schema of Hub 0.2.0b3 (workers, executions); create_all has already made it."""


def _legacy_payload(row) -> dict:
    """An execution log for a run whose raw_log is missing or unreadable, from the executions columns."""
    if not row.has_error:
        return {"has_error": False}
    return {"has_error": True, "failure_details": {
        "failed_step_id": row.failed_step_id, "failed_step_name": row.failed_step_name,
        "error_type": row.error_type, "exception_class": row.exception_class,
        "error_message": row.error_message, "error_screenshot_path": row.screenshot_path}}


def _run_records(conn: Connection) -> None:
    """executions.details, step_results, and failures, filled in for the runs already stored."""
    # Imported here: models imports database, which imports this module
    from .models import Execution, Failure, StepResult
    from .services.run_records import build_run_records, execution_run, store_run_records

    add_column_if_missing(conn, "executions", "details", "TEXT")
    StepResult.__table__.create(conn, checkfirst=True)
    Failure.__table__.create(conn, checkfirst=True)

    table = Execution.__table__
    ids = [row[0] for row in conn.execute(select(table.c.id).where(table.c.details.is_(None)))]
    for execution_id in ids:
        row = conn.execute(select(table).where(table.c.id == execution_id)).one()
        try:
            payload = json.loads(row.raw_log) if row.raw_log else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            payload = _legacy_payload(row)
        store_run_records(conn, execution_id, build_run_records(payload, execution_run(row)))


def _partial_status(conn: Connection) -> None:
    """Runs that finished with failures on the way are partial, not success (#110)."""
    conn.execute(text(
        "UPDATE executions SET status = 'partial' WHERE status = 'success' "
        "AND EXISTS (SELECT 1 FROM failures f WHERE f.execution_id = executions.id)"))


def _run_id_column(conn: Connection) -> None:
    """
    executions.run_id with a unique index, so a run sent twice is stored once (#165). It is filled in from
    details; when rows already share a run id, the first keeps it and the others stay as they are, with none.
    """
    add_column_if_missing(conn, "executions", "run_id", "VARCHAR(64)")
    rows = conn.execute(text(
        "SELECT id, worker_id, details FROM executions WHERE run_id IS NULL ORDER BY created_at, id")).fetchall()
    seen = set()
    for row in rows:
        try:
            details = json.loads(row.details) if row.details else None
        except ValueError:
            details = None
        run_id = details.get("run_id") if isinstance(details, dict) else None
        if not run_id or (row.worker_id, run_id) in seen:
            continue
        seen.add((row.worker_id, run_id))
        conn.execute(text("UPDATE executions SET run_id = :run_id WHERE id = :id"), {"run_id": run_id, "id": row.id})
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_executions_worker_run ON executions (worker_id, run_id)"))


MIGRATIONS: List[Migration] = [
    Migration(1, "baseline: workers and executions", _baseline),
    Migration(2, "run records: executions.details, step_results, failures", _run_records),
    Migration(3, "status partial for runs that finished with failures", _partial_status),
    Migration(4, "executions.run_id, unique per worker", _run_id_column),
]


def _ensure_version_table(conn: Connection) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY,"
        " name VARCHAR(200) NOT NULL,"
        " applied_at VARCHAR(40) NOT NULL)"
    ))


def applied_versions(engine: Engine) -> List[int]:
    with engine.connect() as conn:
        if not inspect(conn).has_table("schema_version"):
            return []
        return [row[0] for row in conn.execute(text("SELECT version FROM schema_version ORDER BY version"))]


def current_version(engine: Engine) -> int:
    versions = applied_versions(engine)
    return versions[-1] if versions else 0


def run_migrations(engine: Engine, migrations: List[Migration] = MIGRATIONS) -> List[int]:
    """Applies the migrations not recorded yet, each in its own transaction. Returns the numbers applied."""
    make_sqlite_transactional(engine)
    with engine.begin() as conn:
        _ensure_version_table(conn)
    done = set(applied_versions(engine))
    applied: List[int] = []
    for migration in sorted(migrations, key=lambda m: m.number):
        if migration.number in done:
            continue
        # One transaction per migration: a failing step leaves the database as it was before that step
        with engine.begin() as conn:
            migration.apply(conn)
            conn.execute(
                text("INSERT INTO schema_version (version, name, applied_at) VALUES (:v, :n, :t)"),
                {"v": migration.number, "n": migration.name,
                 "t": datetime.now(timezone.utc).isoformat(timespec="seconds")},
            )
        applied.append(migration.number)
        logger.info(f"Database migration {migration.number} applied: {migration.name}")
    return applied
