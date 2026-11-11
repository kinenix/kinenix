"""The daemon's own messages reach stderr, so journald shows which triggers started and when they fire (#156)."""
import json
import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from kinenix_worker.logs import configure_logging
from kinenix_worker.triggers.cron import CronExpression
from kinenix_worker.triggers.manager import TriggerManager
from kinenix_worker.triggers.scheduler import CronSchedulerTrigger


@pytest.fixture
def worker_logger(monkeypatch):
    """configure_logging with a clean logger; its handler writes to the stderr that capsys replaced."""
    monkeypatch.delenv("KINENIX_WORKER_LOG_LEVEL", raising=False)
    logger = logging.getLogger("kinenix_worker")
    saved = (logger.handlers[:], logger.level, logger.propagate)
    logger.handlers = []
    yield
    logger.handlers, logger.level, logger.propagate = saved


def test_daemon_start_logs_one_line_per_trigger(tmp_path, capsys, worker_logger):
    configure_logging()
    cfg = tmp_path / "triggers.json"
    cfg.write_text(json.dumps({"triggers": [
        {"type": "scheduler", "flow": "soak-hello", "interval_seconds": 1800, "run_at_start": False},
        {"type": "scheduler", "flow": "bot_fx_rate", "cron": "0 8 * * *"},
        {"type": "file_watcher", "flow": "invoice_check", "watch_dir": str(tmp_path / "inbox"), "pattern": "*.xlsx"},
    ]}), encoding="utf-8")
    manager = TriggerManager(runner=MagicMock())
    manager.load_from_config(str(cfg))
    manager.start_all(blocking=False)
    manager.stop()

    err = capsys.readouterr().err
    assert "[INFO] Starting scheduler on flow 'soak-hello' every 1800.0s, first run " in err
    assert "[INFO] Starting scheduler on flow 'bot_fx_rate' cron '0 8 * * *', next run " in err
    assert "[INFO] Starting file watcher on: " in err and "(pattern: *.xlsx)" in err
    assert "[INFO] Started 3 triggers in background daemon." in err


def test_a_firing_is_logged_with_flow_and_time(capsys, worker_logger):
    configure_logging()
    CronSchedulerTrigger(flow_path="soak-hello", interval_seconds=60, runner=MagicMock()).trigger_now(
        datetime(2026, 11, 11, 9, 30))
    assert "Scheduler triggering flow: soak-hello at 2026-11-11T09:30:00" in capsys.readouterr().err


def test_log_level_variable_lowers_the_volume(capsys, worker_logger, monkeypatch):
    monkeypatch.setenv("KINENIX_WORKER_LOG_LEVEL", "warning")
    configure_logging().info("hidden")
    assert "hidden" not in capsys.readouterr().err


def test_configure_logging_twice_adds_one_handler(worker_logger):
    configure_logging()
    configure_logging()
    assert len(logging.getLogger("kinenix_worker").handlers) == 1


@pytest.mark.parametrize("expression, after, due", [
    ("0 8 * * *", datetime(2026, 11, 11, 7, 59), datetime(2026, 11, 11, 8, 0)),
    ("0 8 * * *", datetime(2026, 11, 11, 8, 0), datetime(2026, 11, 12, 8, 0)),
    ("0 8 1 * *", datetime(2026, 11, 11, 9, 0), datetime(2026, 12, 1, 8, 0)),
    ("30 7 * * 1-5", datetime(2026, 11, 13, 8, 0), datetime(2026, 11, 16, 7, 30)),  # Friday -> Monday
])
def test_cron_next_after(expression, after, due):
    assert CronExpression(expression).next_after(after) == due


def test_first_run_text():
    now = datetime(2026, 11, 11, 9, 0, 30)
    assert CronSchedulerTrigger("a", interval_seconds=60, runner=MagicMock()).first_run(now) == "first run now"
    assert CronSchedulerTrigger("a", interval_seconds=3600, runner=MagicMock(), run_at_start=False).first_run(now) == \
        "first run 2026-11-11 10:00:30"
    assert CronSchedulerTrigger("a", runner=MagicMock(), cron="0 8 * * *").first_run(now) == "next run 2026-11-12 08:00"
    assert CronSchedulerTrigger("a", runner=MagicMock(), cron="0 9 * * *").first_run(now) == "next run 2026-11-11 09:00"
