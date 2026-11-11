"""kinenix hub query: read-only queries on this machine and over HTTP, user views, and output formats."""
import datetime
import json
import os
from argparse import Namespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rich.console import Console
from sqlalchemy import create_engine, text

from kinenix_hub import config as hub_config
from kinenix_hub import models  # noqa: F401  (registers the tables on Base)
from kinenix_hub import query as hub_query
from kinenix_hub import query_console
from kinenix_hub.app import app
from kinenix_hub.database import Base
from kinenix_hub.migrations import run_migrations
from kinenix_hub.views import apply_user_views, create_views

client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
remote_client = TestClient(app, client=("192.168.1.77", 50000))

RUN = {
    "flow_name": "Query Demo", "run_id": "20261012T020000-qdem", "kinenix_version": "0.2.0b4",
    "start_time": "2026-10-12 02:00:00+07:00", "has_error": False, "variables": {"customer": "private value"},
    "step_results": [
        {"step_id": "step_1", "step_name": "Pick Item", "action": "web.click", "status": "failed", "section": "steps",
         "start_time": "2026-10-12 02:00:01+07:00", "end_time": "2026-10-12 02:00:02+07:00", "duration_seconds": 1.0,
         "error_message": "Timeout", "error_type": "Technical", "loop": {"index": 7, "of": 12, "item": "R007"},
         "retries": 2, "failure": {"exception": "TimeoutError", "handled": "continued", "from_subflow": False}},
        {"step_id": "step_2", "step_name": "Save", "action": "excel.write", "status": "success", "section": "steps",
         "start_time": "2026-10-12 02:00:03+07:00", "end_time": "2026-10-12 02:00:04+07:00", "duration_seconds": 1.0},
    ],
}


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD_HASH", "")


@pytest.fixture(scope="module")
def conn():
    res = client.post("/api/v1/telemetry", json={"worker_id": "query-worker", "payload": RUN})
    assert res.status_code == 200
    connection = hub_query.connect(hub_query.database_path(os.environ["DATABASE_URL"]))
    yield connection
    connection.close()


def test_a_view_with_filters(conn):
    result = hub_query.run(conn, "v_failures", flow="Query Demo", filters={"loop_index": "7", "handled": "continued"},
                           since="2026-10-01")
    assert result.columns[0] == "failure_id"
    rows = [dict(zip(result.columns, r)) for r in result.rows]
    assert [(r["step_name"], r["loop_item"], r["retries"]) for r in rows] == [("Pick Item", "R007", 2)]
    assert "?" in result.sql and "Query Demo" not in result.sql  # values are parameters, never SQL text
    assert hub_query.run(conn, "v_failures", flow="Query Demo", since="2026-10-13").rows == []


def test_sql_and_row_limit(conn):
    result = hub_query.run(conn, "SELECT step_name FROM v_steps WHERE flow_name = 'Query Demo' ORDER BY seq;", limit=1)
    assert result.rows == [["Pick Item"]] and result.truncated
    assert not hub_query.run(conn, "SELECT 1", limit=5).truncated


@pytest.mark.parametrize("sql", [
    "DELETE FROM executions",
    "UPDATE workers SET name = 'x'",
    "DROP VIEW v_runs",
    "PRAGMA table_info(executions)",
    "ATTACH DATABASE 'other.db' AS other",
    "CREATE TABLE t (a)",
])
def test_queries_can_only_read(conn, sql):
    with pytest.raises(hub_query.QueryError, match="can only read"):
        hub_query.run(conn, sql)


def test_one_statement_and_clear_errors(conn):
    with pytest.raises(hub_query.QueryError, match="one SQL statement"):
        hub_query.run(conn, "SELECT 1; SELECT 2")
    with pytest.raises(hub_query.QueryError, match="not a table or view"):
        hub_query.run(conn, "v_nothing")
    with pytest.raises(hub_query.QueryError, match="has no column 'status' for --status"):
        hub_query.run(conn, "v_failures", status="failed")
    with pytest.raises(hub_query.QueryError, match="work with a view or table name"):
        hub_query.run(conn, "SELECT 1", flow="x")
    with pytest.raises(hub_query.QueryError, match="between 1 and"):
        hub_query.run(conn, "SELECT 1", limit=0)


def test_slow_queries_are_stopped(tmp_path):
    path = tmp_path / "slow.db"
    create_engine(f"sqlite:///{path.as_posix()}").connect().close()
    slow = hub_query.connect(path, time_limit=0.2)
    endless = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n"
    with pytest.raises(hub_query.QueryError, match="longer than"):
        hub_query.run(slow, endless)
    slow.close()


def test_missing_database_says_what_to_do(tmp_path):
    with pytest.raises(hub_query.QueryError, match="Start the Hub once"):
        hub_query.connect(tmp_path / "none.db")
    with pytest.raises(hub_query.QueryError, match="SQLite"):
        hub_query.database_path("postgresql://user@host/db")


def test_parse_since():
    now = datetime.datetime(2026, 10, 12, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=7)))
    assert hub_query.parse_since("today", now) == "2026-10-11 17:00:00"
    assert hub_query.parse_since("yesterday", now) == "2026-10-10 17:00:00"
    assert hub_query.parse_since("12h", now) == "2026-10-11 14:30:00"
    assert hub_query.parse_since("2w", now) == "2026-09-28 02:30:00"
    assert hub_query.parse_since("2026-10-01T08:00:00+00:00", now) == "2026-10-01 08:00:00"
    with pytest.raises(hub_query.QueryError, match="not understood"):
        hub_query.parse_since("last week", now)


def test_catalog_and_describe_use_the_data_dictionary(conn):
    catalog = {item["name"]: item for item in hub_query.catalog(conn)}
    assert catalog["v_failures"]["type"] == "view" and catalog["v_failures"]["about"].startswith("One row per failure")
    assert catalog["failures"]["rows"] >= 1
    described = hub_query.describe(conn, "v_failures")
    columns = {c["name"]: c for c in described["columns"]}
    assert columns["handled"]["meaning"] == "stopped, continued, fallback, next_item, or ignored"
    assert columns["loop_item"]["example"] == "R007 HONDA HR-V"
    assert {k["name"] for k in hub_query.describe(conn, "failures")["details_keys"]} >= {"exception", "on_error"}


def test_query_over_http_hides_the_raw_log():
    client.post("/api/v1/telemetry", json={"worker_id": "query-worker", "payload": {**RUN, "run_id": "20261012T020500-qde2"}})
    res = client.post("/api/v1/query", json={"source": "SELECT raw_log, flow_name FROM executions WHERE flow_name = 'Query Demo'"})
    assert res.status_code == 200
    assert {tuple(r) for r in res.json()["rows"]} == {(None, "Query Demo")}
    res = client.post("/api/v1/query", json={"source": "v_failures", "flow": "Query Demo", "limit": 1})
    assert res.json()["columns"][0] == "failure_id" and len(res.json()["rows"]) == 1
    assert "private value" not in client.post("/api/v1/query", json={"source": "executions"}).text


def test_query_endpoints_errors_and_auth():
    res = client.post("/api/v1/query", json={"source": "DELETE FROM executions"})
    assert res.status_code == 400 and "can only read" in res.json()["detail"]
    assert client.get("/api/v1/query/describe/v_nothing").status_code == 400
    assert client.get("/api/v1/query/catalog").status_code == 200
    assert remote_client.post("/api/v1/query", json={"source": "v_runs"}).status_code == 403
    assert remote_client.get("/api/v1/query/catalog").status_code == 403


def _hub_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'hub.db').as_posix()}")
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    create_views(engine)
    return engine


def _views(engine):
    with engine.connect() as c:
        return {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type = 'view' AND name GLOB 'custom_*'"))}


def test_user_views_from_a_folder(tmp_path):
    engine = _hub_db(tmp_path)
    folder = tmp_path / "hub_views"
    folder.mkdir()
    # custom_a reads custom_b, which is created later in name order, so it succeeds on the second pass
    (folder / "custom_a.sql").write_text("SELECT flow_name FROM custom_b;\n", encoding="utf-8")
    (folder / "custom_b.sql").write_text("SELECT flow_name, COUNT(*) AS n FROM v_failures GROUP BY flow_name", encoding="utf-8")
    (folder / "custom_broken.sql").write_text("SELEC nothing", encoding="utf-8")
    (folder / "custom_two.sql").write_text("SELECT 1; DROP TABLE executions", encoding="utf-8")
    (folder / "daily.sql").write_text("SELECT 1", encoding="utf-8")

    failures = dict(apply_user_views(engine, folder))
    assert _views(engine) == {"custom_a", "custom_b"}
    assert set(failures) == {"custom_broken.sql", "custom_two.sql", "daily.sql"}
    assert "custom_" in failures["daily.sql"]
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM executions")).scalar() == 0  # the table is still there

    (folder / "custom_a.sql").unlink()
    apply_user_views(engine, folder)
    assert _views(engine) == {"custom_b"}
    assert apply_user_views(engine, tmp_path / "missing") == [] and _views(engine) == set()


def test_user_view_docs_in_list_and_describe(tmp_path):
    engine = _hub_db(tmp_path)
    folder = tmp_path / "hub_views"
    folder.mkdir()
    (folder / "custom_per_flow.sql").write_text("SELECT flow_name, COUNT(*) AS runs FROM v_runs GROUP BY flow_name", encoding="utf-8")
    (folder / "custom_per_flow.md").write_text("# Runs per flow\n\nHow many runs each flow had.\n", encoding="utf-8")
    apply_user_views(engine, folder)
    conn = hub_query.connect(tmp_path / "hub.db")
    catalog = {item["name"]: item for item in hub_query.catalog(conn, folder)}
    assert catalog["custom_per_flow"]["about"] == "How many runs each flow had."
    described = hub_query.describe(conn, "custom_per_flow", folder)
    assert [c["name"] for c in described["columns"]] == ["flow_name", "runs"] and "Runs per flow" in described["doc"]
    conn.close()


RESULT = {"columns": ["step_name", "details"], "rows": [["Pick | Item", '{"line": 42}'], ["Save", None]], "truncated": False}


def test_output_formats():
    assert json.loads(query_console.format_result(RESULT, "json")) == [
        {"step_name": "Pick | Item", "details": '{"line": 42}'}, {"step_name": "Save", "details": None}]
    assert json.loads(query_console.format_result(RESULT, "json", expand=True))[0]["details"] == {"line": 42}
    assert query_console.format_result(RESULT, "csv") == 'step_name,details\nPick | Item,"{""line"": 42}"\nSave,\n'
    assert query_console.format_result(RESULT, "md").splitlines()[2] == '| Pick \\| Item | {"line": 42} |'


def _args(**values):
    defaults = dict(list=False, describe=None, target=None, since=None, flow=None, worker=None, status=None,
                    filter=None, format="table", output=None, expand=False, limit=None, url=None)
    return Namespace(**{**defaults, **values})


def _run_cli(args, width=200):
    console = Console(record=True, width=width, color_system=None)
    errors = Console(record=True, width=width, color_system=None)
    code = query_console.main(console, errors, args, hub_config, interactive=False)
    return code, console.export_text(), errors.export_text()


def test_command_on_this_machine(conn, tmp_path):
    code, out, _ = _run_cli(_args(list=True))
    assert code == 0 and "v_failures" in out and "One row per failure" in out
    code, out, _ = _run_cli(_args(target="v_failures", flow="Query Demo", filter=["handled=continued"]), width=80)
    assert code == 0 and "Row 1" in out and "R007" in out  # wide views print one block per row
    code, out, _ = _run_cli(_args(target="SELECT flow_name FROM v_runs WHERE flow_name = 'Query Demo'", limit=1))
    assert code == 0 and "Query Demo" in out and "more exist" in out
    target = tmp_path / "rows.json"
    code, _, _ = _run_cli(_args(target="v_steps", flow="Query Demo", output=str(target)))
    assert code == 0 and json.loads(target.read_text(encoding="utf-8"))[0]["flow_name"] == "Query Demo"


def test_command_errors():
    code, _, err = _run_cli(_args(target="DELETE FROM executions"))
    assert code == 2 and "can only read" in err
    code, _, err = _run_cli(_args(target="v_runs", filter=["no-equals-sign"]))
    assert code == 2 and "column=value" in err
    code, _, err = _run_cli(_args())
    assert code == 2 and "--list" in err


def test_package_copy_of_the_data_dictionary_is_current():
    docs = Path(__file__).resolve().parents[2] / "docs" / "hub_data.md"
    packaged = Path(query_console.__file__).resolve().parent / "hub_data.md"
    assert packaged.read_bytes() == docs.read_bytes(), "Copy docs/hub_data.md to kinenix-hub/kinenix_hub/hub_data.md"


def test_the_target_may_follow_options(tmp_path):
    """`kinenix hub query --limit 5 "SELECT 1"`: argparse leaves the SQL over, and the CLI takes it as the target."""
    import subprocess
    import sys
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'none.db').as_posix()}"}
    res = subprocess.run([sys.executable, "-m", "kinenix.cli", "hub", "query", "--limit", "5", "SELECT 1"],
                         capture_output=True, text=True, timeout=60, env=env)
    assert res.returncode == 7  # not found
    assert "No Hub database" in res.stdout + res.stderr and "unrecognized" not in res.stderr
    res = subprocess.run([sys.executable, "-m", "kinenix.cli", "hub", "query", "a", "b"],
                         capture_output=True, text=True, timeout=60, env=env)
    assert res.returncode == 2 and "unrecognized arguments: b" in res.stderr


def _report_run(flow_name, start, failed=False):
    payload = {**RUN, "flow_name": flow_name, "start_time": start, "has_error": failed, "run_id": None}
    res = client.post("/api/v1/telemetry", json={"worker_id": "report-worker", "payload": payload})
    assert res.status_code == 200
    return res.json()["execution_id"]


@pytest.fixture(scope="module")
def report_runs():
    """Two runs of one flow and one of a flow whose name shares a word with it."""
    return {
        "old": _report_run("Monthly Invoice Export", "2026-09-01 08:00:00+07:00"),
        "new": _report_run("Monthly Invoice Export", "2026-09-02 08:00:00+07:00", failed=True),
        "other": _report_run("Monthly Payroll", "2026-09-03 08:00:00+07:00"),
    }


def test_latest_runs_by_flow_name(conn, report_runs):
    runs = hub_query.latest_runs(conn, flow="monthly invoice export")
    assert [r["execution_id"] for r in runs] == [report_runs["new"]]
    assert runs[0]["report_md"].startswith("# Monthly Invoice Export, 2026-09-02 08:00 +07:00 (failed)")
    assert [r["execution_id"] for r in hub_query.latest_runs(conn, flow="invoice", limit=5)] == [
        report_runs["new"], report_runs["old"]]
    with pytest.raises(hub_query.QueryError, match="matches 2 flows: Monthly Invoice Export, Monthly Payroll"):
        hub_query.latest_runs(conn, flow="monthly")
    with pytest.raises(hub_query.QueryError, match="No runs of a flow named 'nothing'. Flows with runs:"):
        hub_query.latest_runs(conn, flow="nothing")


def test_latest_runs_by_id(conn, report_runs):
    prefix = report_runs["old"][:8]
    assert hub_query.latest_runs(conn, run=prefix)[0]["execution_id"] == report_runs["old"]
    with pytest.raises(hub_query.QueryError, match="No run ID starts with"):
        hub_query.latest_runs(conn, run="zzzz")
    with pytest.raises(hub_query.QueryError, match="between 1 and"):
        hub_query.latest_runs(conn, limit=0)


def test_runs_endpoint(report_runs):
    res = client.get("/api/v1/query/runs", params={"flow": "payroll"})
    assert res.status_code == 200 and res.json()["runs"][0]["execution_id"] == report_runs["other"]
    assert client.get("/api/v1/query/runs", params={"flow": "monthly"}).status_code == 400
    assert remote_client.get("/api/v1/query/runs").status_code == 403


def test_report_command(report_runs):
    console = Console(record=True, width=60, color_system=None)
    errors = Console(record=True, width=60, color_system=None)
    args = _args(flow="invoice", limit=2)
    assert query_console.main(console, errors, args, hub_config, False, query_console.report_command) == 0
    out = console.export_text()
    assert out.index("2026-09-02") < out.index("2026-09-01")  # newest first
    assert f"Steps: kinenix hub logs {report_runs['new'][:8]}" in out
    # A long line is not broken into two, so it copies whole
    assert any(len(line) > 60 and line.startswith("- Failed: R007") for line in out.splitlines())
    assert query_console.main(console, errors, _args(flow="monthly"), hub_config, False, query_console.report_command) == 2
    assert "Type more of the name" in errors.export_text()


def test_logs_for_the_latest_run_of_a_flow():
    from unittest.mock import MagicMock, patch
    from kinenix_hub import console as hub_console

    runs = MagicMock(status_code=200)
    runs.json.return_value = {"runs": [{"execution_id": "abc12345-run"}]}
    steps = MagicMock(status_code=200)
    steps.json.return_value = {"execution": {"id": "abc12345-run"}, "steps": []}
    with patch("kinenix_hub.console.requests.get", side_effect=[runs, steps]) as get:
        assert hub_console.fetch_execution_log("http://hub:8080", None, None, flow="invoice")["execution"]["id"] == "abc12345-run"
    assert get.call_args_list[0].kwargs["params"] == {"flow": "invoice"}
    assert get.call_args_list[1].args[0] == "http://hub:8080/api/v1/executions/abc12345-run/steps"

    ambiguous = MagicMock(status_code=400)
    ambiguous.json.return_value = {"detail": "'monthly' matches 2 flows"}
    with patch("kinenix_hub.console.requests.get", return_value=ambiguous):
        with pytest.raises(LookupError, match="matches 2 flows"):
            hub_console.fetch_execution_log("http://hub:8080", None, None, flow="monthly")
