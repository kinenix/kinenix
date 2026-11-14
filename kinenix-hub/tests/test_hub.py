import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from kinenix_hub import config as hub_config
from kinenix_hub.app import app

# Local-dev client: no API key configured, requests arrive from loopback
client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
remote_client = TestClient(app, client=("192.168.1.77", 50000))

HEARTBEAT_PAYLOAD = {"worker_id": "rpi-auth-01", "name": "Auth Test Node"}


@pytest.fixture(autouse=True)
def no_credentials_by_default(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_USER", "admin")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "")


def test_hub_healthz():
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_heartbeat_api():
    payload = {
        "worker_id": "rpi-test-01",
        "name": "Raspberry Pi Node",
        "ip_address": "192.168.1.100",
        "os_info": "Raspberry Pi OS",
        "cpu_percent": 12.5,
        "ram_usage": "1.2 / 8 GB",
        "current_task": "BOT"
    }
    response = client.post("/api/v1/heartbeat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["worker"]["id"] == "rpi-test-01"
    assert data["worker"]["status"] == "busy"

    # Verify listing
    res_list = client.get("/api/v1/workers")
    assert res_list.status_code == 200
    workers = res_list.json()["workers"]
    assert any(w["id"] == "rpi-test-01" for w in workers)


def test_telemetry_ingestion_success():
    log_payload = {
        "flow_name": "RPA Challenge",
        "start_time": "2026-09-21T18:00:00",
        "end_time": "2026-09-21T18:00:10",
        "has_error": False,
        "metrics": {
            "total_duration_seconds": 10.0,
            "total_steps": 5,
            "successful_steps": 5,
            "failed_steps": 0
        }
    }
    req = {
        "worker_id": "rpi-test-01",
        "payload": log_payload
    }
    response = client.post("/api/v1/telemetry", json=req)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "recorded"
    assert data["has_error"] is False


@pytest.mark.parametrize("duration", ["n/a", "NaN", -1])
def test_telemetry_with_invalid_duration_is_recorded_as_zero(duration):
    response = client.post("/api/v1/telemetry", json={
        "worker_id": "invalid-duration-worker",
        "payload": {
            "flow_name": "Invalid Duration",
            "start_time": "2026-11-04T18:00:00Z",
            "has_error": False,
            "metrics": {"total_duration_seconds": duration},
        },
    })

    assert response.status_code == 200
    execution = client.get(f"/api/v1/executions/{response.json()['execution_id']}").json()
    assert execution["duration_seconds"] == 0.0
    assert execution["end_time"] == execution["start_time"]


def test_telemetry_ingestion_failure_with_ai():
    log_payload = {
        "flow_name": "BOT Exchange Rates",
        "start_time": "2026-09-21T18:30:00",
        "end_time": "2026-09-21T18:30:15",
        "has_error": True,
        "failure_details": {
            "failed_step_id": "step_4",
            "failed_step_name": "Click Cookie Consent Button",
            "error_type": "Technical",
            "exception_class": "TimeoutError",
            "error_message": "Timeout 3000ms exceeded while waiting for button:has-text('Accept recommended cookies')"
        },
        "metrics": {
            "total_duration_seconds": 15.0,
            "total_steps": 4,
            "successful_steps": 3,
            "failed_steps": 1
        }
    }
    req = {
        "worker_id": "rpi-test-01",
        "payload": log_payload
    }

    with patch("requests.post") as post:
        response = client.post("/api/v1/telemetry", json=req)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "recorded"
    assert data["has_error"] is True
    # The Hub records the failure as the worker reported it and calls no model (1.2.0)
    assert not post.called
    execution = client.get(f"/api/v1/executions/{data['execution_id']}").json()
    assert execution["failed_step_name"] == "Click Cookie Consent Button"
    assert execution["ai_category"] is None


def test_list_executions():
    response = client.get("/api/v1/executions")
    assert response.status_code == 200
    items = response.json()["executions"]
    assert len(items) >= 2



def test_remote_worker_rejected_when_api_key_not_configured():
    response = remote_client.post("/api/v1/heartbeat", json=HEARTBEAT_PAYLOAD)
    assert response.status_code == 403


def test_remote_worker_missing_api_key_rejected(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "s3cret-key")
    response = remote_client.post("/api/v1/heartbeat", json=HEARTBEAT_PAYLOAD)
    assert response.status_code == 401


def test_remote_worker_wrong_api_key_rejected(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "s3cret-key")
    response = remote_client.post(
        "/api/v1/telemetry",
        json={"worker_id": "rpi-auth-01", "payload": {"flow_name": "X"}},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_remote_worker_valid_api_key_accepted(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "s3cret-key")
    response = remote_client.post(
        "/api/v1/heartbeat", json=HEARTBEAT_PAYLOAD, headers={"X-API-Key": "s3cret-key"}
    )
    assert response.status_code == 200
    assert response.json()["worker"]["id"] == "rpi-auth-01"


def test_localhost_must_send_api_key_once_configured(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "s3cret-key")
    response = client.post("/api/v1/heartbeat", json=HEARTBEAT_PAYLOAD)
    assert response.status_code == 401


def test_healthz_remains_public(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "s3cret-key")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "dash-pass")
    assert remote_client.get("/api/v1/healthz").status_code == 200


DASHBOARD_PATHS = ["/", "/api/v1/workers", "/api/v1/executions"]


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_remote_dashboard_rejected_when_password_not_configured(path):
    response = remote_client.get(path)
    assert response.status_code == 403


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_remote_dashboard_missing_credentials_prompts_login(monkeypatch, path):
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "dash-pass")
    response = remote_client.get(path)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


@pytest.mark.parametrize("auth", [("admin", "wrong-pass"), ("intruder", "dash-pass")])
def test_remote_dashboard_wrong_credentials_rejected(monkeypatch, auth):
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "dash-pass")
    response = remote_client.get("/api/v1/executions", auth=auth)
    assert response.status_code == 401


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_remote_dashboard_valid_credentials_accepted(monkeypatch, path):
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "dash-pass")
    response = remote_client.get(path, auth=("admin", "dash-pass"))
    assert response.status_code == 200


def test_localhost_dashboard_requires_credentials_once_configured(monkeypatch):
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "dash-pass")
    response = client.get("/api/v1/workers")
    assert response.status_code == 401


def test_worker_api_key_does_not_grant_dashboard_access(monkeypatch):
    monkeypatch.setattr(hub_config, "API_KEY", "s3cret-key")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "dash-pass")
    response = remote_client.get("/api/v1/executions", headers={"X-API-Key": "s3cret-key"})
    assert response.status_code == 401


def test_cross_origin_requests_get_no_cors_headers():
    response = client.get("/api/v1/healthz", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_is_not_allowed():
    response = client.options(
        "/api/v1/executions",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_default_host_is_localhost(monkeypatch):
    import importlib
    monkeypatch.delenv("KINENIX_HUB_HOST", raising=False)
    try:
        assert importlib.reload(hub_config).HOST == "127.0.0.1"
    finally:
        monkeypatch.undo()
        importlib.reload(hub_config)


def test_worker_key_check_endpoint(monkeypatch):
    """`kinenix connect` checks the key here before saving it; nothing is recorded."""
    assert client.get("/api/v1/auth/worker").status_code == 200  # no key set: localhost only
    assert remote_client.get("/api/v1/auth/worker").status_code == 403
    monkeypatch.setattr(hub_config, "API_KEY", "worker-key-1")
    assert remote_client.get("/api/v1/auth/worker", headers={"X-API-Key": "worker-key-1"}).status_code == 200
    assert remote_client.get("/api/v1/auth/worker", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/v1/auth/worker").status_code == 401


def test_a_localhost_only_hub_refuses_other_host_names(monkeypatch):
    """DNS rebinding (docs/design/threat-model.md, T4): a web page whose name now resolves to 127.0.0.1
    connects from localhost but sends its own name as Host; without a key or password it gets nothing."""
    monkeypatch.setattr(hub_config, "API_KEY", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD", "")
    monkeypatch.setattr(hub_config, "DASHBOARD_PASSWORD_HASH", "")
    rebound = TestClient(app, base_url="http://evil.example:8080", client=("127.0.0.1", 50000))
    assert rebound.get("/api/v1/executions").status_code == 403
    assert rebound.post("/api/v1/heartbeat", json={"worker_id": "x"}).status_code == 403
    assert "localhost" in rebound.get("/api/v1/executions").json()["detail"]
    for url in ("http://localhost:8080", "http://127.0.0.1:8080", "http://localhost"):
        assert TestClient(app, base_url=url, client=("127.0.0.1", 50000)).get("/api/v1/executions").status_code == 200, url


@pytest.mark.parametrize("header, host", [
    ("localhost:8080", "localhost"), ("127.0.0.1", "127.0.0.1"), ("[::1]:8080", "::1"), ("[::1]", "::1"),
    ("LocalHost.:8080", "localhost"), ("evil.example:8080", "evil.example"), ("", ""),
])
def test_host_header_without_its_port(header, host):
    from kinenix_hub.security import _request_host
    assert _request_host(MagicMock(headers={"host": header})) == host
