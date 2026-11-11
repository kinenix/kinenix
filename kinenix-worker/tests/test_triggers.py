import json
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from kinenix_worker.triggers.watcher import FileWatcherTrigger
from kinenix_worker.triggers.scheduler import CronSchedulerTrigger
from kinenix_worker.triggers.manager import TriggerManager


def test_file_watcher_scan_once(tmp_path):
    mock_runner = MagicMock()
    mock_runner.execute_flow.return_value = {
        "job_id": "job_1",
        "flow_name": "TestFlow",
        "status": "success"
    }

    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir()

    watcher = FileWatcherTrigger(
        watch_dir=str(inbox_dir),
        flow_path="flows/test.json",
        pattern="*.csv",
        poll_interval=0.1,
        stabilization_wait=0.0,
        runner=mock_runner
    )

    # 1. No files initially
    res = watcher.scan_once()
    assert len(res) == 0
    mock_runner.execute_flow.assert_not_called()

    # 2. Add a matching file
    f1 = inbox_dir / "orders.csv"
    f1.write_text("id,amount\n1,100", encoding="utf-8")

    # Add a non-matching file
    f2 = inbox_dir / "notes.txt"
    f2.write_text("ignore me", encoding="utf-8")

    res2 = watcher.scan_once()
    assert len(res2) == 1
    assert res2[0]["status"] == "success"
    assert mock_runner.execute_flow.call_count == 1

    call_args = mock_runner.execute_flow.call_args[1]
    assert call_args["flow_path_or_alias"] == "flows/test.json"
    assert call_args["extra_vars"]["trigger_file_name"] == "orders.csv"
    assert "trigger_file_path" in call_args["extra_vars"]

    # 3. Subsequent scan without file changes does not re-trigger
    res3 = watcher.scan_once()
    assert len(res3) == 0
    assert mock_runner.execute_flow.call_count == 1


def test_scheduler_trigger():
    mock_runner = MagicMock()
    mock_runner.execute_flow.return_value = {"status": "success"}

    sched = CronSchedulerTrigger(
        flow_path="flows/scheduled.json",
        interval_seconds=10.0,
        runner=mock_runner
    )

    # First check: should run
    res = sched.check_and_run()
    assert res is not None
    assert res["status"] == "success"
    assert mock_runner.execute_flow.call_count == 1

    # Immediate second check: interval (10s) has not elapsed, should not run
    res2 = sched.check_and_run()
    assert res2 is None
    assert mock_runner.execute_flow.call_count == 1


def test_trigger_manager_config_loading(tmp_path):
    mock_runner = MagicMock()

    cfg_file = tmp_path / "triggers.json"
    cfg_data = {
        "triggers": [
            {
                "type": "file_watcher",
                "watch_dir": str(tmp_path / "drop"),
                "flow": "flows/import.json",
                "pattern": "*.xlsx",
                "interval": 1.0
            },
            {
                "type": "scheduler",
                "flow": "flows/report.json",
                "interval_seconds": 60
            }
        ]
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")

    manager = TriggerManager(runner=mock_runner)
    manager.load_from_config(str(cfg_file))

    assert len(manager.triggers) == 2
    assert isinstance(manager.triggers[0], FileWatcherTrigger)
    assert isinstance(manager.triggers[1], CronSchedulerTrigger)

    # Test start and stop
    manager.start_all(blocking=False)
    time.sleep(0.1)
    manager.stop()


def test_interval_trigger_runs_at_start_by_default():
    from datetime import datetime
    sched = CronSchedulerTrigger(flow_path="daily", interval_seconds=86400, runner=MagicMock())
    assert sched.should_run(datetime(2026, 11, 11, 9, 0)) is True


def test_run_at_start_false_waits_one_interval_before_the_first_run():
    from datetime import datetime, timedelta
    start = datetime(2026, 11, 11, 9, 0)
    sched = CronSchedulerTrigger(flow_path="daily", interval_seconds=3600, runner=MagicMock(), run_at_start=False)
    assert sched.should_run(start) is False
    assert sched.should_run(start + timedelta(minutes=59)) is False
    assert sched.should_run(start + timedelta(hours=1)) is True
    sched.last_run_time = start + timedelta(hours=1)
    assert sched.should_run(start + timedelta(hours=1, minutes=30)) is False
    assert sched.should_run(start + timedelta(hours=2)) is True


def test_run_at_start_is_read_from_triggers_json(tmp_path):
    cfg = tmp_path / "triggers.json"
    cfg.write_text(json.dumps({"triggers": [
        {"type": "scheduler", "flow": "a", "interval_seconds": 60},
        {"type": "scheduler", "flow": "b", "interval_seconds": 60, "run_at_start": False},
    ]}), encoding="utf-8")
    manager = TriggerManager(runner=MagicMock())
    manager.load_from_config(str(cfg))
    assert [t.run_at_start for t in manager.triggers] == [True, False]


def test_run_at_start_as_text_stops_the_daemon_at_load(tmp_path):
    cfg = tmp_path / "triggers.json"
    cfg.write_text(json.dumps({"triggers": [
        {"type": "scheduler", "flow": "a", "interval_seconds": 60, "run_at_start": "false"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="run_at_start"):
        TriggerManager(runner=MagicMock()).load_from_config(str(cfg))
