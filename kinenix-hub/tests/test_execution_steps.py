from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from kinenix_hub import config as hub_config
from kinenix_hub import console as hub_console
from kinenix_hub.app import app
from kinenix_hub.services.telemetry_service import STEP_FIELDS, step_summaries

client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
remote_client = TestClient(app, client=("192.168.1.77", 50000))

PAYLOAD = {
    "flow_name": "Steps Demo",
    "start_time": "2026-10-03T10:00:00+00:00",
    "has_error": False,
    "variables": {"customer_email": "private@example.com"},
    "metrics": {"total_duration_seconds": 3.5},
    "step_results": [
        {"step_id": "s1", "step_name": "Open site", "action": "web.open", "status": "success",
         "duration_seconds": 1.2, "output": {"url": "https://example.com/?token=secret"}},
        {"step_id": "s2", "step_name": "Fill form", "action": "web.fill", "status": "skipped",
         "duration_seconds": 0.0, "output": {"value": "private@example.com"}},
    ],
}


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD_HASH", "")


def _ingest(payload=PAYLOAD) -> str:
    res = client.post("/api/v1/telemetry", json={"worker_id": "steps-worker", "payload": payload})
    assert res.status_code == 200
    return res.json()["execution_id"]


def test_step_summaries_keep_only_safe_fields():
    import json
    steps = step_summaries(json.dumps(PAYLOAD))
    assert [s["step_name"] for s in steps] == ["Open site", "Fill form"]
    assert all(set(s) == set(STEP_FIELDS) for s in steps)
    assert "secret" not in json.dumps(steps) and "private@example.com" not in json.dumps(steps)


@pytest.mark.parametrize("raw", [None, "", "not json", "[]", '{"step_results": null}'])
def test_step_summaries_tolerate_missing_or_bad_logs(raw):
    assert step_summaries(raw) == []


def test_steps_endpoint_returns_steps_without_business_data():
    execution_id = _ingest()
    res = client.get(f"/api/v1/executions/{execution_id}/steps")
    assert res.status_code == 200
    body = res.json()
    assert body["execution"]["id"] == execution_id
    assert [s["status"] for s in body["steps"]] == ["success", "skipped"]
    assert "private@example.com" not in res.text and "secret" not in res.text


def test_steps_endpoint_unknown_id_and_auth():
    assert client.get("/api/v1/executions/does-not-exist/steps").status_code == 404
    execution_id = _ingest()
    assert remote_client.get(f"/api/v1/executions/{execution_id}/steps").status_code == 403


def _response(json_body):
    res = MagicMock(status_code=200)
    res.json.return_value = json_body
    return res


def test_fetch_execution_log_resolves_prefix_and_latest():
    listing = {"executions": [{"id": "abc12345-1"}, {"id": "abd99999-2"}, {"id": "abd88888-3"}]}
    detail = {"execution": {"id": "abc12345-1"}, "steps": []}
    with patch("kinenix_hub.console.requests.get", side_effect=[_response(listing), _response(detail)]) as get:
        assert hub_console.fetch_execution_log("http://orch", None, "abc") == detail
    assert get.call_args_list[1].args[0] == "http://orch/api/v1/executions/abc12345-1/steps"

    with patch("kinenix_hub.console.requests.get", side_effect=[_response(listing), _response(detail)]) as get:
        hub_console.fetch_execution_log("http://orch", None, None)
    assert get.call_args_list[1].args[0].endswith("/abc12345-1/steps")

    for prefix, message in (("abd", "matches 2"), ("zzz", "No recent execution")):
        with patch("kinenix_hub.console.requests.get", return_value=_response(listing)):
            with pytest.raises(LookupError, match=message):
                hub_console.fetch_execution_log("http://orch", None, prefix)

    with patch("kinenix_hub.console.requests.get", return_value=_response({"executions": []})):
        with pytest.raises(LookupError, match="No executions"):
            hub_console.fetch_execution_log("http://orch", None, None)


def test_print_execution_log_shows_steps_and_failure():
    data = {
        "execution": {"id": "abc12345-1", "flow_name": "Demo [bold]", "worker_id": "pi4-01", "status": "failed",
                      "has_error": True, "duration_seconds": 4.25, "failed_step_name": "Submit",
                      "error_message": "Timeout 3000ms",
                      "created_at": "2026-10-03T11:59:00+00:00"},
        "steps": [
            {"step_name": "Open", "action": "web.open", "status": "success", "duration_seconds": 1.0},
            {"step_name": "Submit", "action": "web.click", "status": "failed", "duration_seconds": 3.0,
             "error_type": "Technical", "error_message": "Timeout 3000ms"},
        ],
    }
    console = Console(record=True, width=160, color_system=None)
    hub_console.print_execution_log(console, data, now=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))
    out = console.export_text()
    for expected in ("Demo [bold]", "pi4-01", "4.2s", "Submit", "Steps (2)",
                     "web.click", "Technical: Timeout 3000ms", "1m ago"):
        assert expected in out


def test_print_execution_log_without_steps():
    console = Console(record=True, width=120, color_system=None)
    hub_console.print_execution_log(console, {"execution": {"id": "x", "status": "success"}, "steps": []})
    assert "No step details" in console.export_text()


def test_a_failed_step_shows_the_workers_diagnosis_and_its_item():
    # #111: the dashboard and `hub logs` show root_cause and suggested_fix first, and which item failed
    payload = {**PAYLOAD, "step_results": [
        {"step_id": "s9", "step_name": "Choose Insurance Class", "action": "web.click", "status": "failed",
         "duration_seconds": 10.0, "error_type": "Technical", "error_message": "Locator.click: Timeout 10000ms",
         "loop": {"index": 2, "of": 2, "item": "R002 HONDA HR-V"},
         "failure": {"root_cause": "The click was blocked: div#onetrust-consent-sdk (cookie banner) covered it.",
                     "suggested_fix": "Accept or close the cookie banner before this step.", "handled": "continued"}},
    ]}
    step = client.get(f"/api/v1/executions/{_ingest(payload)}/steps").json()["steps"][0]
    assert step["root_cause"].startswith("The click was blocked") and step["item"] == "R002 HONDA HR-V"
    assert step["suggested_fix"] == "Accept or close the cookie banner before this step."

    console = Console(record=True, width=200)
    hub_console.print_execution_log(console, {"execution": {"id": "x", "status": "partial", "details": {
        "items_total": 2, "items_failed": 1}}, "steps": [step]})
    text = console.export_text()
    assert "(cookie banner) covered it" in text and "Fix: Accept or close" in text and "(R002 HONDA HR-V)" in text
    assert "1 of 2 items failed" in text
