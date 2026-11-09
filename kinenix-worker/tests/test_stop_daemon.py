"""A worker that is stopped lets its running flows end cleanly (#166)."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kinenix.engine import stopping
from kinenix_worker.runner import WorkerRunner
from kinenix_worker.triggers.manager import TriggerManager
from kinenix_worker.triggers.scheduler import CronSchedulerTrigger

FLOW = """# Long

## Steps

### 1. Wait (`logic.delay`)
- **seconds:** 60

## Finally

### 2. Write (`file.write_text`)
- **path:** {done}
- **content:** done
"""


@pytest.fixture(autouse=True)
def no_stop_left_behind():
    stopping.clear_stop()
    yield
    stopping.clear_stop()


def _flow(tmp_path: Path) -> Path:
    flow = tmp_path / "flow.md"
    flow.write_text(FLOW.format(done=(tmp_path / "done.txt").as_posix()), encoding="utf-8")
    return flow


def test_stopping_the_manager_waits_for_the_running_flow(tmp_path: Path):
    results = []
    manager = TriggerManager(runner=WorkerRunner())
    manager.add_trigger(CronSchedulerTrigger(str(_flow(tmp_path)), interval_seconds=3600, runner=manager.runner,
                                             callback=results.append))
    manager.start_all(blocking=False)
    time.sleep(1.0)
    started = time.monotonic()
    manager.stop()
    assert time.monotonic() - started < 10
    assert results and results[0]["status"] == "interrupted" and results[0]["exit_code"] == 130
    assert (tmp_path / "done.txt").exists()
    assert not stopping.stop_requested()


def test_a_stopped_manager_starts_no_new_run(tmp_path: Path):
    results = []
    manager = TriggerManager(runner=WorkerRunner())
    manager.add_trigger(CronSchedulerTrigger(str(_flow(tmp_path)), interval_seconds=0.1, runner=manager.runner,
                                             callback=results.append))
    manager.start_all(blocking=False)
    time.sleep(1.0)
    manager.stop()
    count = len(results)
    time.sleep(1.5)
    assert len(results) == count == 1


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM ends a process at once on Windows")
def test_sigterm_to_the_daemon_runs_finally(tmp_path: Path):
    config = tmp_path / "triggers.json"
    config.write_text('{"triggers": [{"type": "scheduler", "flow": "%s", "interval_seconds": 3600}]}' % _flow(tmp_path).as_posix(),
                      encoding="utf-8")
    env = {**os.environ}
    env.pop("KINENIX_HUB_URL", None)
    process = subprocess.Popen([sys.executable, "-m", "kinenix_worker.cli", "daemon", "--config", str(config)], cwd=tmp_path, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(4.0)
    process.send_signal(signal.SIGTERM)
    output = process.communicate(timeout=30)[0]
    assert (tmp_path / "done.txt").exists(), output
    assert process.returncode == 0, output
