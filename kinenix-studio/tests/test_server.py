import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kinenix.engine.markdown import flow_to_markdown, load_flow
from kinenix.models.flow import FlowDefinition
from kinenix_studio.server import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "kinenix-studio"


def test_root_serves_frontend():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Kinenix Studio" in response.text


def test_list_actions():
    response = client.get("/api/actions")
    assert response.status_code == 200
    data = response.json()
    assert "actions" in data
    action_types = [a["type"] for a in data["actions"]]
    assert "web.open" in action_types
    assert "excel.read" in action_types
    assert "ai.prompt" in action_types


def test_list_flows():
    response = client.get("/api/flows")
    assert response.status_code == 200
    flows = response.json()
    assert isinstance(flows, list)
    flow_names = [f["name"] for f in flows]
    assert "Motor Insurance Quote Requests" in flow_names


def test_get_quote_requests_flow():
    response = client.get("/api/flow", params={"path": "flows/examples/quote_requests"})
    assert response.status_code == 200
    data = response.json()
    assert data["is_valid"] is True
    assert data["flow"]["name"] == "Motor Insurance Quote Requests"
    assert len(data["flow"]["steps"]) >= 4
    # Verify associated config was loaded
    assert data["config"]


def test_update_flow_validation_failure():
    # Attempting to save an invalid flow with a step missing required fields ('action' and 'name')
    bad_payload = {
        "path": "flows/examples/non_existent_flow.md",
        "flow": {
            "name": "Broken Flow",
            "steps": [
                {
                    "id": "step_1"
                    # Missing required fields: 'name' and 'action'
                }
            ]
        }
    }
    response = client.put("/api/flow", json=bad_payload)
    # Pydantic validation error should return 422
    assert response.status_code == 422


def test_save_and_update_step_isolated():
    # Test saving and updating steps within flows directory
    root = Path(__file__).resolve().parent.parent.parent
    test_dir = root / "flows" / "_test_studio"
    test_dir.mkdir(parents=True, exist_ok=True)
    tmp_flow = test_dir / "flow.md"

    try:
        initial_flow = {
            "name": "Test Flow",
            "description": "Temporary flow for testing",
            "version": "1.0.0",
            "variables": {},
            "steps": [
                {
                    "id": "step_1",
                    "name": "Initial Step",
                    "action": "logic.set_variable",
                    "parameters": {"name": "msg", "value": "hello"}
                }
            ]
        }
        tmp_flow.write_text(flow_to_markdown(FlowDefinition(**initial_flow)), encoding="utf-8")

        # 1. Update single step via PUT /api/flow/step
        updated_step = {
            "id": "step_1",
            "name": "Modified Step",
            "action": "logic.set_variable",
            "parameters": {"name": "msg", "value": "world"}
        }
        step_resp = client.put("/api/flow/step", json={
            "path": str(tmp_flow.relative_to(root)),
            "step_id": "step_1",
            "step": updated_step
        })
        assert step_resp.status_code == 200

        # Verify disk updated
        disk_data = load_flow(tmp_flow).model_dump(exclude_none=True)
        assert disk_data["steps"][0]["name"] == "Modified Step"
        assert disk_data["steps"][0]["parameters"]["value"] == "world"

        # 2. Update whole flow via PUT /api/flow
        disk_data["name"] = "Renamed Flow"
        save_resp = client.put("/api/flow", json={
            "path": str(tmp_flow.relative_to(root)),
            "flow": disk_data
        })
        assert save_resp.status_code == 200

        reloaded = load_flow(tmp_flow).model_dump(exclude_none=True)
        assert reloaded["name"] == "Renamed Flow"

        # 3. Test running the flow via POST /api/flow/run
        run_resp = client.post("/api/flow/run", json={
            "path": str(tmp_flow.relative_to(root))
        })
        assert run_resp.status_code == 200
        run_data = run_resp.json()
        assert run_data["status"] == "success"
        assert run_data["is_completed"] is True

    finally:
        if test_dir.exists():
            shutil.rmtree(test_dir, ignore_errors=True)


def test_path_containment_rejects_traversal():
    # Attempt directory traversal outside flows/
    resp = client.get("/api/flow", params={"path": "../../windows/win.ini"})
    assert resp.status_code == 403

    resp_put = client.put("/api/flow", json={
        "path": "../../outside_flow.md",
        "flow": {"name": "Hacked", "steps": []}
    })
    assert resp_put.status_code == 403

