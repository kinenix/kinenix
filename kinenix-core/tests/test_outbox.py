"""Runs that could not reach the Hub are kept and sent later (#173)."""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from kinenix.engine import outbox
from kinenix.engine.logger import ExecutionLogger
from kinenix.models.context import ExecutionContext


def _send_run(run_id, post):
    context = ExecutionContext(flow_name="Outbox Test")
    with patch("requests.post", side_effect=post) as mock_post:
        ExecutionLogger(log_dir=None)._send_telemetry(
            "http://127.0.0.1:8080", {"flow_name": "Outbox Test", "run_id": run_id}, context)
    return mock_post


def _ok(*args, **kwargs):
    return MagicMock(status_code=200)


def _down(*args, **kwargs):
    raise requests.ConnectionError("connection refused")


def _sent_run_ids(mock_post):
    return [call.kwargs["json"]["payload"]["run_id"] for call in mock_post.call_args_list]


def test_a_run_the_hub_cannot_receive_is_kept():
    _send_run("run-1", _down)
    kept = outbox.pending()
    assert len(kept) == 1
    body = json.loads(kept[0].read_text(encoding="utf-8"))
    assert body["payload"]["run_id"] == "run-1" and body["worker_id"]


def test_the_next_run_that_reaches_the_hub_sends_the_kept_ones_oldest_first():
    _send_run("run-1", _down)
    _send_run("run-2", _down)
    mock_post = _send_run("run-3", _ok)
    assert _sent_run_ids(mock_post) == ["run-3", "run-1", "run-2"]
    assert outbox.pending() == []


@pytest.mark.parametrize("status, kept", [(500, True), (503, True), (401, True), (429, True), (422, False)])
def test_which_hub_answers_keep_the_run(status, kept):
    _send_run("run-1", lambda *a, **k: MagicMock(status_code=status, text="no"))
    assert bool(outbox.pending()) is kept


def test_sending_stops_at_the_first_failure_and_keeps_the_rest():
    for run_id in ("run-1", "run-2", "run-3"):
        _send_run(run_id, _down)
    answers = iter([MagicMock(status_code=200), MagicMock(status_code=503)])
    with patch("requests.post", side_effect=lambda *a, **k: next(answers)):
        sent, left = outbox.send_pending("http://127.0.0.1:8080")
    assert (sent, left) == (1, 2)
    assert [json.loads(p.read_text(encoding="utf-8"))["payload"]["run_id"] for p in outbox.pending()] == ["run-2", "run-3"]


def test_a_run_the_hub_will_never_accept_is_set_aside():
    _send_run("run-1", _down)
    with patch("requests.post", return_value=MagicMock(status_code=422)):
        assert outbox.send_pending("http://127.0.0.1:8080") == (0, 0)
    assert len(list((outbox.outbox_dir() / "rejected").glob("*.json"))) == 1


def test_the_outbox_drops_the_oldest_runs_beyond_its_limit(monkeypatch):
    monkeypatch.setattr(outbox, "LIMIT", 3)
    for number in range(5):
        _send_run(f"run-{number}", _down)
    kept = [json.loads(p.read_text(encoding="utf-8"))["payload"]["run_id"] for p in outbox.pending()]
    assert kept == ["run-2", "run-3", "run-4"]


def test_one_send_is_limited_to_a_batch():
    for number in range(4):
        _send_run(f"run-{number}", _down)
    with patch("requests.post", return_value=MagicMock(status_code=200)) as mock_post:
        assert outbox.send_pending("http://127.0.0.1:8080", batch=3) == (3, 1)
    assert mock_post.call_count == 3


def test_an_empty_outbox_sends_nothing():
    with patch("requests.post") as mock_post:
        assert outbox.send_pending("http://127.0.0.1:8080") == (0, 0)
    mock_post.assert_not_called()


def test_the_default_outbox_is_next_to_the_saved_settings(monkeypatch, tmp_path):
    monkeypatch.undo()  # the autouse fixture replaced outbox_dir
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "settings" / "kinenix.env"))
    assert outbox.outbox_dir() == tmp_path / "settings" / "outbox"
