"""Read-only queries over the Hub database, for `kinenix hub query` and the /api/v1/query endpoints.

The same code answers on the Hub machine (reading hub.db directly) and over HTTP, and will back the MCP tools.
Guards: the database is opened read-only, an authorizer allows reading only (no PRAGMA, ATTACH, or writes),
one statement per call, a time limit, and a row limit. Over HTTP, `executions.raw_log` reads as empty,
because the whole log can hold flow variables and step outputs that the API does not show.
"""
import datetime
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.engine import make_url

from . import dictionary

DEFAULT_LIMIT = 50
MAX_LIMIT = 10000
TIME_LIMIT_SECONDS = 10.0
HIDDEN_OVER_HTTP = {("executions", "raw_log")}
# The column --since filters on, in order of preference
TIME_COLUMNS = ("failed_at", "started_at", "start_time", "last_run_at", "last_heartbeat", "created_at", "applied_at")
USER_VIEW_PREFIX = "custom_"

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                    getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_DURATION = re.compile(r"^(\d+)\s*(m|h|d|w)$")


class _Connection(sqlite3.Connection):
    """A connection that knows its time limit; the progress handler stops a query after its deadline."""
    time_limit = TIME_LIMIT_SECONDS
    deadline = 0.0

    def start_clock(self) -> None:
        self.deadline = time.monotonic() + self.time_limit


class QueryError(Exception):
    """A question the Hub database cannot answer; exit_code tells wrong use (2) from not found (7)."""

    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code



@dataclass
class QueryResult:
    columns: List[str]
    rows: List[List[Any]]
    truncated: bool
    sql: str
    params: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"columns": self.columns, "rows": self.rows, "truncated": self.truncated, "sql": self.sql}


def database_path(database_url: str) -> Path:
    """The SQLite file of a DATABASE_URL; other databases are not supported by queries."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise QueryError(f"Queries read a SQLite database file; DATABASE_URL is {url.get_backend_name()}.")
    return Path(url.database)


def connect(path: Path, hide_raw_log: bool = False, time_limit: float = TIME_LIMIT_SECONDS) -> _Connection:
    """A read-only connection that can only read, and stops a query after `time_limit` seconds."""
    if not path.is_file():
        raise QueryError(f"No Hub database at {path}. Start the Hub once, or query a Hub on another machine with --url.", exit_code=7)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False, factory=_Connection)

    def authorize(action, arg1, arg2, database, source):
        if action not in _ALLOWED_ACTIONS:
            return sqlite3.SQLITE_DENY
        if hide_raw_log and action == sqlite3.SQLITE_READ and (arg1, arg2) in HIDDEN_OVER_HTTP:
            return sqlite3.SQLITE_IGNORE  # reads as NULL
        return sqlite3.SQLITE_OK

    conn.set_authorizer(authorize)
    conn.time_limit = time_limit
    conn.set_progress_handler(lambda: 1 if time.monotonic() > conn.deadline else 0, 10000)
    conn.start_clock()
    return conn


def _execute(conn: _Connection, sql: str, params: List[Any], limit: int) -> QueryResult:
    conn.start_clock()
    try:
        cursor = conn.execute(sql, params)
        rows = cursor.fetchmany(limit + 1)
    except (sqlite3.Warning, sqlite3.ProgrammingError) as e:
        raise QueryError(f"Only one SQL statement can run at a time ({e}).")
    except sqlite3.DatabaseError as e:
        message = str(e)
        if "interrupted" in message:
            raise QueryError(f"The query took longer than {conn.time_limit:.0f} seconds and was stopped.")
        if "not authorized" in message:
            raise QueryError("Queries can only read (SELECT); this statement would change or inspect the database.")
        if "no such table" in message:
            raise QueryError(f"{message}. Start the new Hub once to create its tables and views; --list shows what exists.")
        raise QueryError(message)
    columns = [d[0] for d in cursor.description or []]
    return QueryResult(columns, [list(r) for r in rows[:limit]], len(rows) > limit, sql, params)


def _check_limit(limit: Optional[int]) -> int:
    limit = DEFAULT_LIMIT if limit is None else limit
    if not 1 <= limit <= MAX_LIMIT:
        raise QueryError(f"--limit must be between 1 and {MAX_LIMIT}.")
    return limit


def objects(conn: _Connection) -> Dict[str, str]:
    """{name: "table" or "view"} for what can be queried."""
    conn.start_clock()
    rows = conn.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name").fetchall()
    return {name: kind for name, kind in rows}


def known_name(conn: _Connection, name: str) -> str:
    """The table or view called `name`, spelled as the database returns it, so SQL is built only from names
    the database itself gave (CodeQL py/sql-injection); QueryError (not found) for any other text."""
    for known in objects(conn):
        if known == name:
            return known
    raise QueryError(f"'{name}' is not a table or view. Run kinenix hub query --list to see them.", exit_code=7)


def columns_of(conn: _Connection, name: str) -> List[str]:
    """Columns of `name`, a name from objects() or known_name()."""
    return [d[0] for d in conn.execute(f'SELECT * FROM "{name}" LIMIT 0').description]  # nosec B608: name comes from the database


def parse_since(value: str, now: Optional[datetime.datetime] = None) -> str:
    """--since as stored UTC text: today, yesterday, 30m, 12h, 7d, 2w, a date (2026-10-12), or a date and time.

    Days and dates mean local midnight on the machine that runs the query.
    """
    now = now or datetime.datetime.now().astimezone()
    text = value.strip().lower()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if text == "today":
        start = midnight
    elif text == "yesterday":
        start = midnight - datetime.timedelta(days=1)
    elif _DURATION.match(text):
        amount, unit = _DURATION.match(text).groups()
        start = now - datetime.timedelta(**{{"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[unit]: int(amount)})
    else:
        try:
            start = datetime.datetime.fromisoformat(value.strip())
        except ValueError:
            raise QueryError(f"--since '{value}' is not understood; use today, yesterday, 30m, 12h, 7d, 2w, or a date such as 2026-10-12.")
        if start.tzinfo is None:
            start = start.astimezone()  # local time on this machine
    return start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _number_or_text(value: str) -> Any:
    for kind in (int, float):
        try:
            return kind(value)
        except ValueError:
            pass
    return value


def build_select(conn: _Connection, name: str, since: Optional[str] = None, flow: Optional[str] = None,
                 worker: Optional[str] = None, status: Optional[str] = None,
                 filters: Optional[Dict[str, str]] = None, limit: int = DEFAULT_LIMIT) -> Tuple[str, List[Any]]:
    """SELECT for a table or view with the --since, --flow, --worker, --status, and --filter conditions."""
    name = known_name(conn, name)
    columns = columns_of(conn, name)
    conditions: List[str] = []
    params: List[Any] = []

    def require(column: str, option: str) -> None:
        if column not in columns:
            raise QueryError(f"{name} has no column '{column}' for {option}; its columns: {', '.join(columns)}.")

    time_column = next((c for c in TIME_COLUMNS if c in columns), None)
    if since:
        if not time_column:
            raise QueryError(f"{name} has no time column for --since.")
        conditions.append(f'"{time_column}" >= ?')
        params.append(parse_since(since))
    for column, option, value in (("flow_name", "--flow", flow), ("worker_id", "--worker", worker),
                                  ("status", "--status", status)):
        if value:
            require(column, option)
            conditions.append(f'"{column}" = ?')
            params.append(value)
    for column, value in (filters or {}).items():
        if not _IDENTIFIER.match(column):
            raise QueryError(f"--filter needs column=value; '{column}' is not a column name.")
        require(column, "--filter")
        conditions.append(f'"{column}" = ?')
        params.append(_number_or_text(value))

    sql = f'SELECT * FROM "{name}"'  # nosec B608: name and columns are checked against the database; values are ? parameters
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    if time_column:
        sql += f' ORDER BY "{time_column}" DESC'
    sql += f" LIMIT {limit + 1}"  # one more row than shown tells whether there are more
    return sql, params


def run(conn: _Connection, source: str, since: Optional[str] = None, flow: Optional[str] = None,
        worker: Optional[str] = None, status: Optional[str] = None, filters: Optional[Dict[str, str]] = None,
        limit: Optional[int] = None) -> QueryResult:
    """`source` is a table or view name (with filters) or one SQL SELECT statement (without filters)."""
    limit = _check_limit(limit)
    source = source.strip()
    if _IDENTIFIER.match(source):
        sql, params = build_select(conn, source, since, flow, worker, status, filters, limit)
        return _execute(conn, sql, params, limit)
    if since or flow or worker or status or filters:
        raise QueryError("--since, --flow, --worker, --status, and --filter work with a view or table name, "
                         "not with SQL; write the conditions in the WHERE clause instead.")
    return _execute(conn, source.rstrip().rstrip(";"), [], limit)


def user_view_doc(views_dir: Optional[Path], name: str) -> str:
    """The .md file that documents a user view, or an empty string."""
    if not views_dir or not name.startswith(USER_VIEW_PREFIX):
        return ""
    doc = views_dir / f"{name}.md"
    return doc.read_text(encoding="utf-8").strip() if doc.is_file() else ""


def _first_paragraph(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.strip():
            if lines:
                break
            continue
        if not line.startswith("#"):
            lines.append(line.strip())
    return " ".join(lines)


def catalog(conn: _Connection, views_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every table and view with its row count and what it answers (--list)."""
    entries = dictionary.load()
    result = []
    for name, kind in objects(conn).items():
        conn.start_clock()
        try:
            rows = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]  # nosec B608: name comes from objects()
        except sqlite3.DatabaseError:
            rows = None  # a user view that no longer works
        entry = entries.get(name)
        about = entry.description if entry else _first_paragraph(user_view_doc(views_dir, name))
        result.append({"name": name, "type": kind, "rows": rows, "about": about})
    return result


def describe(conn: _Connection, name: str, views_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Columns of a table or view with their meaning and example, from the data dictionary (--describe)."""
    name = known_name(conn, name)
    entries = dictionary.load()
    entry = entries.get(name)
    columns = []
    for column in columns_of(conn, name):
        meaning, example = entry.columns.get(column, ("", "")) if entry else ("", "")
        columns.append({"name": column, "meaning": meaning, "example": example})
    details = entries.get(f"{name}.details")
    return {
        "name": name,
        "type": objects(conn)[name],
        "about": entry.description if entry else "",
        "doc": "" if entry else user_view_doc(views_dir, name),
        "columns": columns,
        "details_keys": [{"name": k, "meaning": m, "example": e} for k, (m, e) in details.columns.items()] if details else [],
    }


RUN_COLUMNS = ("execution_id", "run_id", "flow_name", "worker_id", "status", "started_at", "duration_seconds",
               "failure_count", "report_md")
MAX_RUNS = 100


def match_flow(conn: _Connection, text: str) -> str:
    """
    The flow name that `text` means: an exact name (any case), else the only name that contains it.
    Several or no matches raise QueryError naming the flows, so the person can type more of the name.
    """
    conn.start_clock()
    names = sorted(r[0] for r in conn.execute("SELECT DISTINCT flow_name FROM executions WHERE flow_name IS NOT NULL"))
    wanted = text.strip().lower()
    exact = [n for n in names if n.lower() == wanted]
    if exact:
        return exact[0]
    partial = [n for n in names if wanted in n.lower()]
    if len(partial) == 1:
        return partial[0]
    if partial:
        raise QueryError(f"'{text}' matches {len(partial)} flows: {', '.join(partial)}. Type more of the name.")
    known = f" Flows with runs: {', '.join(names[:20])}." if names else " No runs are recorded yet."
    raise QueryError(f"No runs of a flow named '{text}'.{known}")


def latest_runs(conn: _Connection, flow: Optional[str] = None, run: Optional[str] = None,
                limit: int = 1) -> List[Dict[str, Any]]:
    """
    The newest runs, of one flow when `flow` is given (matched as in match_flow), or the run whose
    execution id or run id starts with `run`. For `kinenix hub report` and `kinenix hub logs --flow`.
    """
    if not 1 <= limit <= MAX_RUNS:
        raise QueryError(f"--limit must be between 1 and {MAX_RUNS}.")
    conditions: List[str] = []
    params: List[Any] = []
    if flow:
        conditions.append("flow_name = ?")
        params.append(match_flow(conn, flow))
    if run:
        conditions.append("(execution_id LIKE ? OR run_id LIKE ?)")
        params += [f"{run.strip()}%", f"{run.strip()}%"]
    sql = f"SELECT {', '.join(RUN_COLUMNS)} FROM v_runs"  # nosec B608: fixed column names; values are ? parameters
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY started_at DESC LIMIT ?"
    result = _execute(conn, sql, params + [MAX_RUNS if run else limit], MAX_RUNS)
    runs = [dict(zip(result.columns, row)) for row in result.rows]
    if run:
        if not runs:
            raise QueryError(f"No run ID starts with '{run}'.")
        if len({r["execution_id"] for r in runs}) > 1:
            raise QueryError(f"'{run}' matches {len(runs)} runs; type more characters of the ID.")
    elif not runs:
        raise QueryError("No runs are recorded yet.")
    return runs[:limit]
