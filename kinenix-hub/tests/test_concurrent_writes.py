"""Heartbeats and runs from the same worker that arrive together are all stored, without HTTP 500 (#201)."""
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from kinenix_hub import models  # noqa: F401  (models registers the tables on Base)
from kinenix_hub.app import app
from kinenix_hub.database import Base, SessionLocal, engine
from kinenix_hub.models import Execution

Base.metadata.create_all(bind=engine)

WORKER = "busy-worker"
HEARTBEAT = {"worker_id": WORKER, "name": "Busy", "ip_address": "127.0.0.1", "os_info": "Linux",
             "cpu_percent": 1.0, "ram_usage": "1 GB", "current_task": None}


def _client():
    return TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))


def _run(number, failed=False):
    payload = {"run_id": f"20261111T000000-{number:04d}", "flow_name": "Busy Flow",
               "start_time": "2026-11-11T00:00:00Z", "has_error": failed,
               "metrics": {"total_duration_seconds": 1.0},
               "step_results": [{"step_id": "s1", "step_name": "One", "action": "logic.delay", "status": "success"}]}
    if failed:
        payload["failure_details"] = {"error_message": "boom", "error_type": "Technical"}
    return {"worker_id": WORKER, "payload": payload}


def test_only_write_sessions_take_the_write_lock_at_their_start():
    from sqlalchemy import event, text

    from kinenix_hub.database import WriteSessionLocal

    begins = []

    def record(conn, cursor, statement, *args):
        if statement.startswith("BEGIN"):
            begins.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        with WriteSessionLocal() as db:
            db.execute(text("SELECT 1"))
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert begins == ["BEGIN", "BEGIN IMMEDIATE"]


def test_heartbeats_and_runs_at_the_same_time_all_succeed():
    stop = threading.Event()
    statuses = []

    def beat():
        client = _client()
        while not stop.is_set():
            statuses.append(client.post("/api/v1/heartbeat", json=HEARTBEAT).status_code)

    def send(numbers):
        client = _client()
        for number in numbers:
            statuses.append(client.post("/api/v1/telemetry", json=_run(number)).status_code)

    with ThreadPoolExecutor(max_workers=4) as pool:
        beaters = [pool.submit(beat) for _ in range(2)]
        senders = [pool.submit(send, range(start, start + 30)) for start in (0, 100)]
        for sender in senders:
            sender.result()
        stop.set()
        for beater in beaters:
            beater.result()

    assert statuses and set(statuses) == {200}, sorted(set(statuses))
    with SessionLocal() as db:
        assert db.query(Execution).filter(Execution.worker_id == WORKER).count() == 60

