"""Run records: steps, failures, and the run report are stored as rows and read through the views."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from kinenix_hub import config as hub_config
from kinenix_hub.app import app
from kinenix_hub.database import engine
from kinenix_hub.services.run_records import (
    EXECUTION_DETAILS_KEYS,
    FAILURE_DETAILS_KEYS,
    OUTPUT_LIMIT,
    STEP_DETAILS_KEYS,
    format_duration,
    short_text,
)

client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))


def _step(step_id, name, action, status, **extra):
    base = {"step_id": step_id, "step_name": name, "action": action, "status": status, "section": "steps",
            "start_time": "2026-10-12 02:00:01+07:00", "end_time": "2026-10-12 02:00:02+07:00",
            "duration_seconds": 1.0, "output": None, "error_message": None, "error_type": None, "line": None,
            "path": None, "subflow": None, "loop": None, "retries": 0, "failure": None}
    return {**base, **extra}


def _failure(handled, from_subflow=False, exception="TimeoutError"):
    return {"exception": exception, "root_cause": "Option did not appear", "suggested_fix": "Check the selector",
            "screenshot": "./errors/shot.png", "handled": handled, "from_subflow": from_subflow}


R007 = {"index": 7, "of": 12, "item": "R007 HONDA HR-V"}

# A run from a 0.2.0b4 worker: a subflow step fails inside a loop and the flow continues, then a step stops it
NEW_WORKER_RUN = {
    "flow_name": "TIPH Quotes",
    "run_id": "20261012T020000-abcd",
    "kinenix_version": "0.2.0b4",
    "items": {"total": 12, "done": 6, "failed": 1},
    "start_time": "2026-10-12 02:00:00+07:00",
    "has_error": True,
    "metrics": {"total_duration_seconds": 840.0},
    "failure_details": {"failed_step_id": "step_3", "failed_step_name": "Save Quotes", "action": "excel.write",
                        "error_type": "Technical", "exception_class": "PermissionError",
                        "error_message": "File is open in Excel", "root_cause": "Locked", "suggested_fix": "Close it",
                        "section": "steps"},
    "step_results": [
        _step("step_1", "Open Site", "web.open", "success", output={"url": "https://example.com"}, line=5,
              path="TIPH Quotes > Open Site"),
        _step("step_1", "Choose Brand", "web.click", "failed", section="steps", line=42, subflow="process_one",
              path="TIPH Quotes > Each Request > process_one > Choose Brand", loop=R007, retries=2,
              error_message="Timeout 30000ms exceeded\nwaiting for option HONDA", error_type="Technical",
              failure=_failure("continued")),
        _step("sub_step_2_1", "Process One", "flow.call", "failed", line=12, loop=R007,
              error_message="Subflow 'process_one' failed", error_type="Technical",
              failure=_failure("continued", from_subflow=True, exception="SubflowExecutionError")),
        _step("step_2", "Skip Holiday", "logic.delay", "skipped", output={"skipped_reason": "Condition not met"}),
        _step("step_3", "Save Quotes", "excel.write", "failed", line=60, error_message="File is open in Excel",
              error_type="Technical", failure=_failure("stopped", exception="PermissionError")),
        _step("on_error_1", "Capture Screen", "web.screenshot", "success", section="on_error"),
        _step("on_error_2", "Email Error", "email.send", "failed", section="on_error",
              error_message="SMTP refused", failure=_failure("continued", exception="SMTPException")),
        _step("finally_1", "Close Browser", "web.close", "success", section="finally"),
    ],
}


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD_HASH", "")


def _ingest(payload, worker_id="rpi4") -> str:
    res = client.post("/api/v1/telemetry", json={"worker_id": worker_id, "payload": payload})
    assert res.status_code == 200
    return res.json()["execution_id"]


def _rows(sql, execution_id):
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), {"id": execution_id})]


def test_every_step_is_a_row_in_order():
    execution_id = _ingest(NEW_WORKER_RUN)
    steps = _rows("SELECT * FROM v_steps WHERE execution_id = :id ORDER BY seq", execution_id)
    assert [s["seq"] for s in steps] == list(range(1, 9))
    assert [s["section"] for s in steps][-3:] == ["on_error", "on_error", "finally"]
    choose = steps[1]
    assert (choose["flow_name"], choose["worker_id"], choose["run_id"]) == ("TIPH Quotes", "rpi4", "20261012T020000-abcd")
    assert (choose["subflow"], choose["line"], choose["retries"]) == ("process_one", 42, 2)
    assert (choose["loop_item"], choose["loop_index"], choose["loop_of"]) == ("R007 HONDA HR-V", 7, 12)
    assert choose["error"].startswith("Timeout 30000ms")
    assert steps[0]["output"] == '{"url": "https://example.com"}'
    assert steps[3]["skipped_reason"] == "Condition not met" and steps[3]["output"] is None


def test_failures_include_continued_ones_but_not_the_subflow_call_twice():
    execution_id = _ingest(NEW_WORKER_RUN)
    failures = _rows("SELECT * FROM v_failures WHERE execution_id = :id ORDER BY failure_id", execution_id)
    assert [(f["step_name"], f["handled"]) for f in failures] == [
        ("Choose Brand", "continued"), ("Save Quotes", "stopped"), ("Email Error", "continued")]
    choose, save, email = failures
    assert choose["loop_item"] == "R007 HONDA HR-V" and choose["step_path"].endswith("process_one > Choose Brand")
    assert (choose["exception"], choose["screenshot"], choose["run_status"]) == ("TimeoutError", "./errors/shot.png", "failed")
    assert choose["failed_at"].startswith("2026-10-11 19:00:02")  # stored in UTC
    assert email["section"] == "on_error"

    raw = _rows("SELECT details, step_result_id FROM failures WHERE execution_id = :id ORDER BY id", execution_id)
    assert json.loads(raw[1]["details"])["on_error"] == [
        {"step_name": "Capture Screen", "action": "web.screenshot", "status": "success"},
        {"step_name": "Email Error", "action": "email.send", "status": "failed"}]
    assert "on_error" not in json.loads(raw[0]["details"])
    linked = _rows("SELECT step_name FROM step_results WHERE id = :id", raw[0]["step_result_id"])
    assert linked == [{"step_name": "Choose Brand"}]


def test_run_view_and_report():
    execution_id = _ingest(NEW_WORKER_RUN)
    run = _rows("SELECT * FROM v_runs WHERE execution_id = :id", execution_id)[0]
    assert (run["kinenix_version"], run["items_total"], run["items_done"], run["items_failed"]) == ("0.2.0b4", 12, 6, 1)
    assert (run["step_count"], run["failure_count"], run["status"]) == (8, 3, "failed")
    assert run["report_md"] == (
        "# TIPH Quotes, 2026-10-12 02:00 +07:00 (failed)\n"
        "- Worker: rpi4, Kinenix 0.2.0b4, duration 14 min\n"
        "- Items: 6 of 12 done, 1 failed, 5 not reached\n"
        "- Failed: R007 HONDA HR-V at \"Choose Brand\" (subflow process_one, line 42, after 2 retries), continued: "
        "Timeout 30000ms exceeded waiting for option HONDA\n"
        "- Failed: \"Save Quotes\" (line 60), run stopped: File is open in Excel\n"
        "- Failed: \"Email Error\" (in On Error), continued: SMTP refused\n"
        "- On Error: Capture Screen succeeded, Email Error failed\n"
        "- Finally: Close Browser succeeded\n"
    )
    details = client.get(f"/api/v1/executions/{execution_id}").json()["details"]
    assert details["run_id"] == "20261012T020000-abcd" and details["report_md"] == run["report_md"]


def test_successful_run_report():
    payload = {"flow_name": "Hello", "start_time": "2026-10-12T08:00:00Z", "has_error": False,
               "kinenix_version": "0.2.0b4", "metrics": {"total_duration_seconds": 3.25},
               "step_results": [_step("step_1", "Greet", "logic.set_variable", "success", output="hi")]}
    run = _rows("SELECT report_md, failure_count FROM v_runs WHERE execution_id = :id", _ingest(payload))[0]
    assert run["failure_count"] == 0
    assert run["report_md"] == "# Hello, 2026-10-12 08:00 +00:00 (success)\n- Worker: rpi4, Kinenix 0.2.0b4, duration 3.2 s\n- No failures\n"


def test_long_outputs_and_errors_are_stored_short():
    long_value = "x" * (OUTPUT_LIMIT + 100)
    payload = {"flow_name": "Long", "has_error": False, "kinenix_version": "0.2.0b4",
               "step_results": [_step("step_1", "Read", "file.read", "success", output=long_value),
                                _step("step_2", "Try", "web.click", "failed", error_message=long_value,
                                      failure=_failure("continued"))]}
    steps = _rows("SELECT output, error FROM v_steps WHERE execution_id = :id ORDER BY seq", _ingest(payload))
    assert steps[0]["output"] == "x" * OUTPUT_LIMIT + "..."
    assert steps[1]["error"] == "x" * OUTPUT_LIMIT + "..."
    assert short_text({"a": 1}) == '{"a": 1}' and short_text(None) is None


def test_runs_from_older_workers():
    """No kinenix_version: outputs were not redacted and are not stored; the stopping failure comes from failure_details."""
    payload = {
        "flow_name": "Old Flow", "start_time": "2026-10-01T09:00:00", "has_error": True,
        "metrics": {"total_duration_seconds": 5.0},
        "failure_details": {"failed_step_id": "s2", "failed_step_name": "Submit", "error_type": "Technical",
                            "exception_class": "TimeoutError", "error_message": "Timeout", "root_cause": "Slow page",
                            "suggested_fix": "Wait longer", "error_screenshot_path": "./errors/s2.png"},
        "step_results": [
            {"step_id": "s1", "step_name": "Fill", "action": "web.type", "status": "success",
             "duration_seconds": 1.0, "output": {"value": "customer@example.com"}},
            {"step_id": "s2", "step_name": "Submit", "action": "web.click", "status": "failed",
             "duration_seconds": 4.0, "error_message": "Timeout", "error_type": "Technical"},
        ],
    }
    execution_id = _ingest(payload)
    steps = _rows("SELECT step_name, output, step_path FROM v_steps WHERE execution_id = :id ORDER BY seq", execution_id)
    assert steps == [{"step_name": "Fill", "output": None, "step_path": None},
                     {"step_name": "Submit", "output": None, "step_path": None}]
    failures = _rows("SELECT step_name, handled, exception, screenshot FROM v_failures WHERE execution_id = :id", execution_id)
    assert failures == [{"step_name": "Submit", "handled": "stopped", "exception": "TimeoutError",
                         "screenshot": "./errors/s2.png"}]
    run = _rows("SELECT kinenix_version, report_md FROM v_runs WHERE execution_id = :id", execution_id)[0]
    assert run["kinenix_version"] is None and "- Worker: rpi4, duration 5.0 s\n" in run["report_md"]


def test_a_run_that_failed_before_any_step_still_has_its_failure():
    payload = {"flow_name": "Needs New", "has_error": True, "kinenix_version": "0.2.0b4", "step_results": [],
               "failure_details": {"failed_step_id": "flow_requires", "failed_step_name": "Kinenix version check",
                                   "action": "flow.requires", "error_type": "Technical", "exception_class": "RuntimeError",
                                   "error_message": "This flow requires kinenix>=0.3", "section": "steps"}}
    execution_id = _ingest(payload)
    failures = _rows("SELECT step_result_id, step_name, handled, message FROM failures WHERE execution_id = :id", execution_id)
    assert failures == [{"step_result_id": None, "step_name": "Kinenix version check", "handled": "stopped",
                         "message": "This flow requires kinenix>=0.3"}]


def test_details_hold_only_documented_keys():
    execution_id = _ingest(NEW_WORKER_RUN)
    for table, allowed in (("executions", EXECUTION_DETAILS_KEYS), ("step_results", STEP_DETAILS_KEYS),
                           ("failures", FAILURE_DETAILS_KEYS)):
        column = "id" if table == "executions" else "execution_id"
        for row in _rows(f"SELECT details FROM {table} WHERE {column} = :id", execution_id):
            details = json.loads(row["details"])
            assert details["v"] == 1
            assert set(details) <= set(allowed), (table, set(details) - set(allowed))


@pytest.mark.parametrize("seconds, expected", [(0.0, "0.0 s"), (59.9, "59.9 s"), (840, "14 min"), (3720, "1 h 2 min")])
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_the_run_screenshot_is_stored():
    """Workers send failure_details.error_screenshot_path; the Hub keeps it in executions.screenshot_path."""
    payload = {"flow_name": "Shot", "has_error": True, "kinenix_version": "0.2.0b4", "step_results": [],
               "failure_details": {"failed_step_id": "step_1", "failed_step_name": "Click", "error_type": "Technical",
                                   "exception_class": "TimeoutError", "error_message": "Timeout",
                                   "error_screenshot_path": "./errors/step_1.png"}}
    execution_id = _ingest(payload)
    assert client.get(f"/api/v1/executions/{execution_id}").json()["screenshot_path"] == "./errors/step_1.png"


# #110: a run that finished with failed items or steps on the way is partial, not success
PARTIAL_RUN = {
    "flow_name": "TIPH Motor Insurance Quotes", "start_time": "2026-10-22T08:13:59Z", "has_error": False,
    "kinenix_version": "0.4.0b1", "items": {"total": 2, "done": 1, "failed": 1},
    "metrics": {"total_duration_seconds": 82.1},
    "step_results": [
        _step("step_9", "Choose Insurance Class", "web.click", "failed", subflow="process_request",
              loop={"index": 2, "of": 2, "item": "R002 HONDA HR-V"}, error_message="Locator.click: Timeout",
              error_type="Technical", failure=_failure("continued")),
        _step("step_12", "Send Completion Notice", "email.send", "success"),
    ],
}


@pytest.mark.parametrize("payload, status", [
    (PARTIAL_RUN, "partial"),
    ({**PARTIAL_RUN, "items": None}, "partial"),  # no item counts: a failed step is enough
    ({**PARTIAL_RUN, "items": {"total": 2, "done": 2, "failed": 0},
      "step_results": [_step("s1", "Greet", "logic.set_variable", "success")]}, "success"),
    (NEW_WORKER_RUN, "failed"),
])
def test_run_status(payload, status):
    execution_id = _ingest(payload)
    assert _rows("SELECT status FROM v_runs WHERE execution_id = :id", execution_id)[0]["status"] == status
    assert client.get(f"/api/v1/executions/{execution_id}").json()["status"] == status


def test_a_partial_run_reports_what_failed():
    execution_id = _ingest(PARTIAL_RUN)
    run = _rows("SELECT report_md FROM v_runs WHERE execution_id = :id", execution_id)[0]
    assert run["report_md"].startswith("# TIPH Motor Insurance Quotes, 2026-10-22 08:13 +00:00 (partial)\n")
    assert "- Items: 1 of 2 done, 1 failed, 0 not reached\n" in run["report_md"]
    details = client.get(f"/api/v1/executions/{execution_id}").json()["details"]
    assert (details["items_failed"], details["failure_count"]) == (1, 1)


def test_partial_text_says_what_failed_in_plain_words():
    from kinenix_hub.console import partial_text
    assert partial_text({"items_total": 2, "items_failed": 1, "failure_count": 3}) == "1 of 2 items failed"
    assert partial_text({"failure_count": 2}) == "2 step(s) failed and the run went on"
    assert partial_text(None) == "some steps failed and the run went on"


@pytest.mark.parametrize("steps, status, code", [
    ("### 1. Wait (`logic.delay`)\n- **seconds:** 0\n", "success", 0),
    ("### 1. Read (`file.read_text`)\n- **path:** ./missing.txt\n- **on_error:** continue\n", "partial", 8),
    ("### 1. Read (`file.read_text`)\n- **path:** ./missing.txt\n", "failed", 1),
])
def test_the_exit_code_and_the_hub_agree_on_a_run(steps, status, code):
    from kinenix import exit_codes
    from kinenix.engine.interpreter import FlowInterpreter
    from kinenix.engine.logger import ExecutionLogger
    from kinenix.engine.markdown import markdown_to_flow
    from kinenix_hub.services.run_records import run_status

    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(markdown_to_flow(f"# Run\n\n## Steps\n\n{steps}"))
    assert run_status(context.model_dump(mode="json")) == status
    assert exit_codes.for_run(context) == code


def test_a_step_with_on_error_ignore_does_not_make_the_run_partial():
    """on_error: ignore (#197): the failure is recorded, but the run is not partial."""
    from kinenix_hub.services.run_records import run_status
    ignored = {"status": "failed", "failure": {"handled": "ignored"}}
    continued = {"status": "failed", "failure": {"handled": "continued"}}
    assert run_status({"step_results": [ignored]}) == "success"
    assert run_status({"step_results": [ignored, continued]}) == "partial"


def test_flows_view_has_one_row_per_flow_with_its_newest_run():
    def run(start, worker, **extra):
        payload = {"flow_name": "Flows View Demo", "start_time": start, "has_error": False,
                   "metrics": {"total_duration_seconds": 1.0}, **extra}
        return _ingest(payload, worker_id=worker)

    run("2026-11-01 02:00:00+07:00", "pi-a")
    run("2026-11-02 02:00:00+07:00", "pi-b", has_error=True,
        failure_details={"error_type": "Technical", "error_message": "boom"})
    newest = run("2026-11-03 02:00:00+07:00", "pi-a", interrupted=True)
    flow = _rows("SELECT * FROM v_flows WHERE flow_name = 'Flows View Demo'", None)
    assert len(flow) == 1
    flow = flow[0]
    assert (flow["run_count"], flow["success_count"], flow["failed_count"], flow["interrupted_count"],
            flow["partial_count"]) == (3, 1, 1, 1, 0)
    assert flow["worker_count"] == 2
    assert flow["first_run_at"].startswith("2026-10-31 19:00:00")
    assert flow["last_run_at"].startswith("2026-11-02 19:00:00")
    assert (flow["last_status"], flow["last_worker_id"], flow["last_execution_id"]) == ("interrupted", "pi-a", newest)
