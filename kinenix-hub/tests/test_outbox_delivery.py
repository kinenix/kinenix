"""A run kept while the Hub was down reaches the Hub once it is back, and is stored once (#173)."""
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient

from kinenix.engine import outbox
from kinenix.engine.logger import ExecutionLogger
from kinenix.models.context import ExecutionContext
from kinenix_hub import models  # noqa: F401  (models registers the tables on Base)
from kinenix_hub.app import app
from kinenix_hub.database import Base, SessionLocal, engine
from kinenix_hub.models import Execution

Base.metadata.create_all(bind=engine)
hub = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
WORKER = "outbox-worker"


@pytest.fixture(autouse=True)
def own_outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox, "outbox_dir", lambda: tmp_path / "outbox")
    monkeypatch.setenv("KINENIX_WORKER_ID", WORKER)
    monkeypatch.delenv("KINENIX_HUB_API_KEY", raising=False)


def _through_hub(url, json=None, headers=None, timeout=None):
    return hub.post(url.replace("http://127.0.0.1:8080", ""), json=json, headers=headers)


def _hub_down(*args, **kwargs):
    raise requests.ConnectionError("connection refused")


def _finish_run(run_id, post):
    payload = {"flow_name": "Outbox Delivery", "run_id": run_id, "start_time": "2026-11-11T08:00:00Z",
               "has_error": False, "metrics": {"total_duration_seconds": 1.0},
               "step_results": [{"step_id": "s1", "step_name": "One", "action": "logic.delay", "status": "success"}]}
    with patch("requests.post", side_effect=post):
        ExecutionLogger(log_dir=None)._send_telemetry("http://127.0.0.1:8080", payload,
                                                      ExecutionContext(flow_name="Outbox Delivery"))


def _stored_run_ids():
    with SessionLocal() as db:
        return sorted(e.run_id for e in db.query(Execution).filter(Execution.worker_id == WORKER))


def test_runs_kept_while_the_hub_was_down_are_stored_once_when_it_is_back():
    _finish_run("20261111T080000-down1", _hub_down)
    _finish_run("20261111T083000-down2", _hub_down)
    assert _stored_run_ids() == [] and len(outbox.pending()) == 2

    _finish_run("20261111T090000-back", _through_hub)
    assert _stored_run_ids() == ["20261111T080000-down1", "20261111T083000-down2", "20261111T090000-back"]
    assert outbox.pending() == []

    # A run sent again, for example by two processes at once, is not stored twice
    outbox.keep({"worker_id": WORKER, "payload": {"flow_name": "Outbox Delivery", "run_id": "20261111T080000-down1",
                                                  "start_time": "2026-11-11T08:00:00Z", "has_error": False}})
    with patch("requests.post", side_effect=_through_hub):
        assert outbox.send_pending("http://127.0.0.1:8080") == (1, 0)
    assert len(_stored_run_ids()) == 3
