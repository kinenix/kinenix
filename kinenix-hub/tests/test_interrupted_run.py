"""A run stopped on request has its own status on the Hub, and is not a failure (#166)."""

from fastapi.testclient import TestClient

from kinenix_hub.app import app
from kinenix_hub.services.run_records import run_status

client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))


def test_interrupted_wins_over_the_other_statuses():
    assert run_status({"interrupted": True, "has_error": False}) == "interrupted"
    assert run_status({"interrupted": True, "has_error": True}) == "interrupted"
    assert run_status({"interrupted": False, "has_error": False}) == "success"
    assert run_status({"has_error": True}) == "failed"


def test_an_interrupted_run_is_stored():
    payload = {"flow_name": "Stopped", "run_id": "20261106T100000-stop", "interrupted": True, "has_error": False,
               "start_time": "2026-11-06T03:00:00Z", "metrics": {"total_duration_seconds": 2.0}}
    response = client.post("/api/v1/telemetry", json={"worker_id": "stop-worker", "payload": payload})
    assert response.status_code == 200
    execution = client.get(f"/api/v1/executions/{response.json()['execution_id']}").json()
    assert execution["status"] == "interrupted" and execution["has_error"] is False
