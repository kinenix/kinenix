import logging
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from kinenix.engine.markdown import flow_to_markdown
from kinenix.models.flow import FlowDefinition
from kinenix_worker.hub_client import HubClient, resolve_worker_id
from kinenix_worker.runner import WorkerRunner


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    # Resolving the fake host "orch" would wait on DNS
    monkeypatch.setattr("kinenix_worker.hub_client._local_ip", lambda url: "192.0.2.10")


def _response(status_code):
    res = MagicMock()
    res.status_code = status_code
    return res


def test_worker_id_defaults_to_host_name(monkeypatch):
    monkeypatch.delenv("KINENIX_WORKER_ID", raising=False)
    assert resolve_worker_id() == socket.gethostname()
    monkeypatch.setenv("KINENIX_WORKER_ID", "rpi4-01")
    assert resolve_worker_id() == "rpi4-01"


def test_disabled_without_url_sends_nothing():
    client = HubClient(url="", api_key="")
    with patch("requests.post") as post:
        assert client.send_heartbeat() is False
    assert not post.called
    assert client.ping()["detail"] == "KINENIX_HUB_URL is not set"


def test_heartbeat_sends_payload_and_api_key():
    client = HubClient(url="http://orch:8080/", api_key="secret", worker_id="rpi4-01")
    client.current_task = "RPA Challenge Solver"
    with patch("requests.post", return_value=_response(200)) as post:
        assert client.send_heartbeat() is True
    assert post.call_args.args[0] == "http://orch:8080/api/v1/heartbeat"
    assert post.call_args.kwargs["headers"] == {"X-API-Key": "secret"}
    body = post.call_args.kwargs["json"]
    assert body["worker_id"] == "rpi4-01"
    assert body["current_task"] == "RPA Challenge Solver"
    for field in ("name", "ip_address", "os_info", "cpu_percent", "ram_usage"):
        assert field in body


def test_unreachable_hub_logs_once_and_never_raises(caplog):
    client = HubClient(url="http://orch:8080", api_key="", worker_id="w")
    with patch("requests.post", side_effect=requests.ConnectionError("refused")):
        with caplog.at_level(logging.WARNING, logger="kinenix_worker.hub"):
            assert client.send_heartbeat() is False
            assert client.send_heartbeat() is False
    assert len([r for r in caplog.records if "failed" in r.getMessage()]) == 1


def test_ping_reports_wrong_api_key():
    client = HubClient(url="http://orch:8080", api_key="wrong", worker_id="w")
    with patch("requests.get", return_value=_response(200)), patch("requests.post", return_value=_response(401)):
        result = client.ping()
    assert result["reachable"] is True
    assert result["authorized"] is False
    assert "API_KEY" in result["detail"]


def test_ping_success_and_unreachable():
    client = HubClient(url="http://orch:8080", api_key="k", worker_id="w")
    with patch("requests.get", return_value=_response(200)), patch("requests.post", return_value=_response(200)):
        assert client.ping() == {"reachable": True, "authorized": True, "detail": "Heartbeat accepted"}
    with patch("requests.get", side_effect=requests.ConnectionError("refused")):
        assert client.ping()["reachable"] is False


def _write_flow(tmp_path: Path, steps) -> Path:
    flow_file = tmp_path / "flow.md"
    flow_file.write_text(flow_to_markdown(FlowDefinition(name="Heartbeat Test Flow", steps=steps)), encoding="utf-8")
    return flow_file


def test_runner_reports_busy_then_idle_and_tags_telemetry(tmp_path: Path):
    client = MagicMock(spec=HubClient)
    client.worker_id = "rpi4-01"
    flow = _write_flow(tmp_path, [
        {"id": "s1", "name": "Set", "action": "logic.set_variable", "parameters": {"name": "x", "value": "1"}},
    ])
    res = WorkerRunner(client=client).execute_flow(str(flow))
    assert res["status"] == "success"
    assert [c.args[0] for c in client.set_task.call_args_list] == ["Heartbeat Test Flow", None]


def test_runner_failed_flow_returns_error_summary(tmp_path: Path):
    # Regression: a failed flow raised AttributeError on ctx.error_message
    client = MagicMock(spec=HubClient)
    client.worker_id = "w"
    flow = _write_flow(tmp_path, [
        {"id": "s1", "name": "Read Missing File", "action": "excel.read",
         "parameters": {"file_path": str(tmp_path / "missing.xlsx")}},
    ])
    res = WorkerRunner(client=client).execute_flow(str(flow))
    assert res["status"] == "failed"
    assert "Read Missing File" in res["error"]
    assert client.set_task.call_args_list[-1].args[0] is None


def test_a_heartbeat_that_reaches_the_hub_sends_the_runs_waiting_in_the_outbox():
    from kinenix.engine import outbox
    outbox.keep({"worker_id": "w1", "payload": {"run_id": "kept-run", "flow_name": "Kept"}})
    client = HubClient(url="http://orch:8080", api_key="k", worker_id="w1")
    with patch("kinenix_worker.hub_client.requests.post", return_value=_response(200)) as mock_post:
        assert client.send_heartbeat() is True
    urls = [call.args[0] for call in mock_post.call_args_list]
    assert urls == ["http://orch:8080/api/v1/heartbeat", "http://orch:8080/api/v1/telemetry"]
    assert mock_post.call_args_list[1].kwargs["headers"] == {"X-API-Key": "k"}
    assert outbox.pending() == []


def test_a_failed_heartbeat_leaves_the_outbox_alone():
    from kinenix.engine import outbox
    outbox.keep({"worker_id": "w1", "payload": {"run_id": "kept-run"}})
    client = HubClient(url="http://orch:8080", worker_id="w1")
    with patch("kinenix_worker.hub_client.requests.post", side_effect=requests.ConnectionError("down")) as mock_post:
        assert client.send_heartbeat() is False
    assert mock_post.call_count == 1
    assert len(outbox.pending()) == 1
