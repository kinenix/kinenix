"""A run sent to the Hub twice is stored once, for each worker (#165)."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from kinenix_hub import models  # noqa: F401  (models registers the tables on Base)
from kinenix_hub.app import app
from kinenix_hub.database import Base, SessionLocal
from kinenix_hub.migrations import run_migrations
from kinenix_hub.models import Execution, StepResult
from kinenix_hub.services import telemetry_service

client = TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))


def _send(run_id, worker="once-worker", flow="Once", **extra):
    payload = {"flow_name": flow, "start_time": "2026-11-05T01:00:00Z", "has_error": False,
               "metrics": {"total_duration_seconds": 1.0},
               "step_results": [{"step_id": "s1", "step_name": "One", "action": "logic.delay", "status": "success"}],
               **extra}
    if run_id is not None:
        payload["run_id"] = run_id
    response = client.post("/api/v1/telemetry", json={"worker_id": worker, "payload": payload})
    assert response.status_code == 200, response.text
    return response.json()


def _rows(flow):
    with SessionLocal() as db:
        return db.query(Execution).filter(Execution.flow_name == flow).all()


def test_a_run_sent_twice_is_stored_once():
    first = _send("20261105T010000-aaaa", flow="Twice")
    second = _send("20261105T010000-aaaa", flow="Twice")
    assert second["execution_id"] == first["execution_id"] and second["status"] == "recorded"
    assert len(_rows("Twice")) == 1
    with SessionLocal() as db:
        assert db.query(StepResult).filter(StepResult.execution_id == first["execution_id"]).count() == 1


def test_the_same_run_id_from_another_worker_is_another_run():
    _send("20261105T010000-cccc", worker="worker-a", flow="Two Workers")
    _send("20261105T010000-cccc", worker="worker-b", flow="Two Workers")
    assert len(_rows("Two Workers")) == 2


def test_runs_from_older_workers_without_a_run_id_are_all_kept():
    _send(None, flow="Older Worker")
    _send(None, flow="Older Worker")
    assert len(_rows("Older Worker")) == 2


@pytest.mark.parametrize("bad", ["", 12345, "x" * 65])
def test_a_run_id_that_cannot_be_one_is_stored_without_it(bad):
    flow = f"Bad Id {str(bad)[:5]}"
    _send(bad, flow=flow)
    assert [row.run_id for row in _rows(flow)] == [None]


def test_two_copies_arriving_at_the_same_moment_keep_one_record():
    first = _send("20261105T010000-dddd", flow="Same Moment")
    real = telemetry_service._stored_run
    calls = []

    def stored(db, worker_id, run_id):
        calls.append(run_id)  # The first check sees nothing, as if the other copy was not written yet
        return None if len(calls) == 1 else real(db, worker_id, run_id)

    with patch.object(telemetry_service, "_stored_run", side_effect=stored):
        second = _send("20261105T010000-dddd", flow="Same Moment")
    assert second["execution_id"] == first["execution_id"]
    assert len(_rows("Same Moment")) == 1


def _old_database(path):
    """Runs stored before migration 4: run ids only inside details."""
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_executions_worker_run"))
        conn.execute(text("ALTER TABLE executions DROP COLUMN run_id"))
        conn.execute(text("DELETE FROM schema_version WHERE version = 4"))
        rows = (("e1", "w1", "r1", "2026-01-01"), ("e2", "w1", "r1", "2026-01-02"), ("e3", "w2", "r1", "2026-01-03"),
                ("e4", "w1", "r2", "2026-01-04"))
        for row_id, worker, run_id, created in rows:
            conn.execute(text("INSERT INTO executions (id, worker_id, flow_name, status, details, created_at) "
                              "VALUES (:id, :w, 'Old', 'success', :d, :c)"),
                         {"id": row_id, "w": worker, "d": json.dumps({"v": 1, "run_id": run_id}), "c": created})
        conn.execute(text("INSERT INTO executions (id, worker_id, flow_name, status) VALUES ('e5', 'w1', 'Old', 'success')"))
        conn.execute(text("INSERT INTO executions (id, worker_id, flow_name, status, details) "
                          "VALUES ('e6', 'w1', 'Old', 'success', 'not json')"))
    return engine


def test_the_upgrade_fills_run_ids_and_keeps_every_row(tmp_path):
    engine = _old_database(tmp_path / "hub.db")
    assert run_migrations(engine) == [4]
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, run_id FROM executions")).fetchall())
    assert rows == {"e1": "r1", "e2": None, "e3": "r1", "e4": "r2", "e5": None, "e6": None}
    assert run_migrations(engine) == []


def test_the_upgrade_makes_run_ids_unique_for_a_worker(tmp_path):
    engine = _old_database(tmp_path / "hub.db")
    run_migrations(engine)
    indexes = {i["name"]: i for i in inspect(engine).get_indexes("executions")}
    assert indexes["uq_executions_worker_run"]["unique"]
    assert indexes["uq_executions_worker_run"]["column_names"] == ["worker_id", "run_id"]
