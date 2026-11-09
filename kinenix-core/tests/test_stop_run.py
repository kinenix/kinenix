"""A run that is stopped on request ends cleanly: Finally runs and the run is recorded (#166)."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from kinenix import exit_codes
from kinenix.actions.base import BaseAction
from kinenix.actions.registry import register_action
from kinenix.engine import stopping
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow

unix_only = pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM ends a process at once on Windows")


@pytest.fixture(autouse=True)
def no_stop_left_behind():
    stopping.clear_stop()
    yield
    stopping.clear_stop()


@register_action("test.ask_to_stop")
class AskToStop(BaseAction):
    def execute(self, parameters, context):
        stopping.request_stop()
        if parameters.get("then_fail"):
            raise ConnectionError("browser closed")
        return "asked"


ASK = "### 1. Ask (`test.ask_to_stop`)\n"
MARK = "### {n}. {name} (`logic.set_variable`)\n- **name:** {name}\n- **value:** ran\n"
SECTIONS = "\n## On Error\n\n" + MARK.format(n=8, name="on_error_ran") + "\n## Finally\n\n" + MARK.format(n=9, name="finally_ran") \
    + "### 10. Status (`logic.set_variable`)\n- **name:** seen_status\n- **value:** ${run.status}\n"


def _run(steps, tmp_path=None, initial_vars=None):
    log_dir = tmp_path / "logs" if tmp_path else None
    return FlowInterpreter(logger=ExecutionLogger(log_dir=log_dir)).run_flow(
        markdown_to_flow(f"# Stop\n\n## Steps\n\n{steps}"), initial_vars=initial_vars)


def test_the_remaining_steps_are_skipped_and_finally_runs(tmp_path):
    context = _run(ASK + MARK.format(n=2, name="next_ran") + SECTIONS, tmp_path)
    assert context.interrupted and not context.has_error and not context.is_completed
    assert context.variables.get("next_ran") is None
    assert context.variables["finally_ran"] == "ran"
    assert context.variables["seen_status"] == "interrupted"
    assert exit_codes.for_run(context) == exit_codes.INTERRUPTED
    assert list((tmp_path / "logs").rglob("*_interrupted.json"))


def test_on_error_does_not_run_because_nothing_failed():
    assert _run(ASK + MARK.format(n=2, name="next_ran") + SECTIONS).variables.get("on_error_ran") is None


def test_a_step_that_fails_because_of_the_stop_is_not_a_failure():
    context = _run("### 1. Ask (`test.ask_to_stop`)\n- **then_fail:** true\n- **max_retries:** 3\n- **retry_interval:** 30\n"
                   "- **on_error:** continue\n" + MARK.format(n=2, name="next_ran") + SECTIONS)
    assert context.interrupted and not context.has_error
    assert context.variables.get("next_ran") is None and context.variables.get("on_error_ran") is None


def test_a_loop_stops_and_its_item_is_not_a_failed_item():
    context = _run("### 1. Each (`logic.loop`)\n- **items:** [1, 2, 3]\n- **item_var:** `i`\n- **item_label:** ${i}\n- **Sub-steps:**\n"
                   "  - Ask (`test.ask_to_stop`):\n    - **condition:** `${i} == 2`\n"
                   "  - Mark (`logic.append`):\n    - **target:** `seen`\n    - **item:** ${i}\n")
    assert context.interrupted
    assert context.variables["seen"] == [1]
    assert context.items["failed"] == 0 and context.items["done"] == 1


def test_a_subflow_runs_its_finally_and_then_the_flow_stops(tmp_path):
    (tmp_path / "sub.md").write_text(f"# Sub\n\n## Steps\n\n{ASK}{MARK.format(n=2, name='sub_next')}\n## Finally\n\n"
                                     f"### 3. Write (`file.write_text`)\n- **path:** {(tmp_path / 'sub_finally.txt').as_posix()}\n- **content:** done\n",
                                     encoding="utf-8")
    context = _run("### 1. Call (`flow.call`)\n- **flow:** ./sub.md\n- **on_error:** continue\n" + MARK.format(n=2, name="next_ran") + SECTIONS,
                   initial_vars={"__flow_dir__": str(tmp_path)})
    assert context.interrupted and context.variables.get("next_ran") is None
    assert (tmp_path / "sub_finally.txt").read_text(encoding="utf-8") == "done"
    assert context.variables["finally_ran"] == "ran"


def test_a_subflow_called_from_finally_runs_to_its_end(tmp_path):
    (tmp_path / "sub.md").write_text(f"# Sub\n\n## Steps\n\n### 1. Write (`file.write_text`)\n- **path:** {(tmp_path / 'clean.txt').as_posix()}\n"
                                     "- **content:** done\n", encoding="utf-8")
    _run(ASK + "\n## Finally\n\n### 2. Clean (`flow.call`)\n- **flow:** ./sub.md\n", initial_vars={"__flow_dir__": str(tmp_path)})
    assert (tmp_path / "clean.txt").exists()


def test_a_delay_ends_at_once():
    threading.Timer(0.1, stopping.request_stop).start()
    started = time.monotonic()
    context = _run("### 1. Wait (`logic.delay`)\n- **seconds:** 30\n" + MARK.format(n=2, name="next_ran"))
    assert time.monotonic() - started < 5 and context.interrupted


def test_a_delay_in_finally_still_waits():
    started = time.monotonic()
    _run(ASK + "\n## Finally\n\n### 2. Wait (`logic.delay`)\n- **seconds:** 0.2\n")
    assert time.monotonic() - started >= 0.2


def test_a_stopped_run_with_handled_failures_is_not_partial():
    context = _run("### 1. Read (`file.read_text`)\n- **path:** ./missing.txt\n- **on_error:** continue\n"
                   "### 2. Ask (`test.ask_to_stop`)\n" + MARK.format(n=3, name="next_ran"))
    assert context.interrupted and not context.is_partial
    assert exit_codes.for_run(context) == exit_codes.INTERRUPTED


def test_a_failure_in_finally_stays_interrupted():
    context = _run(ASK + MARK.format(n=2, name="next_ran") + "\n## Finally\n\n### 3. Read (`file.read_text`)\n- **path:** ./missing.txt\n")
    assert context.interrupted and context.has_error
    assert exit_codes.for_run(context) == exit_codes.INTERRUPTED


def test_the_hub_is_told(tmp_path):
    with patch("requests.post") as post:
        post.return_value = MagicMock(status_code=200)
        _run(ASK + MARK.format(n=2, name="next_ran"), tmp_path, initial_vars={"hub_url": "http://hub.test"})
    payload = post.call_args.kwargs["json"]
    payload = payload.get("payload", payload)
    assert payload["interrupted"] is True and payload["has_error"] is False


def test_a_stop_after_the_last_step_finished_is_not_an_interruption():
    context = _run(ASK)
    assert not context.interrupted and exit_codes.for_run(context) == exit_codes.OK


def test_a_delay_that_is_the_last_step_is_an_interruption():
    threading.Timer(0.1, stopping.request_stop).start()
    assert _run("### 1. Wait (`logic.delay`)\n- **seconds:** 30\n").interrupted


def test_a_run_without_a_stop_is_not_interrupted():
    context = _run(MARK.format(n=1, name="first"))
    assert not context.interrupted and exit_codes.for_run(context) == exit_codes.OK


FLOW = """# Stop Me

## Steps

### 1. Wait (`logic.delay`)
- **seconds:** 60

### 2. After (`file.write_text`)
- **path:** {after}
- **content:** no

## Finally

{finally_steps}
"""


def _start(tmp_path, finally_steps, command=("kinenix.cli", "run")):
    bundle = tmp_path / "stopme"
    bundle.mkdir()
    (bundle / "flow.md").write_text(FLOW.format(after=(tmp_path / "after.txt").as_posix(), finally_steps=finally_steps), encoding="utf-8")
    env = {**os.environ, "KINENIX_FLOWS_DIR": str(tmp_path)}
    env.pop("KINENIX_HUB_URL", None)
    process = subprocess.Popen([sys.executable, "-m", *command, "stopme", "--log-dir", str(tmp_path / "logs")], cwd=tmp_path, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 30
    while not list((tmp_path / "logs").rglob("*.jsonl")) and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)
    return process


@unix_only
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_a_real_signal_runs_finally_and_writes_the_log(tmp_path, signum):
    done = (tmp_path / "finally.txt").as_posix()
    process = _start(tmp_path, f"### 3. Write (`file.write_text`)\n- **path:** {done}\n- **content:** done\n")
    process.send_signal(signum)
    output = process.communicate(timeout=30)[0]
    assert process.returncode == exit_codes.INTERRUPTED, output
    assert (tmp_path / "finally.txt").exists() and not (tmp_path / "after.txt").exists()
    log = next((tmp_path / "logs").rglob("*_interrupted.json"))
    assert json.loads(log.read_text(encoding="utf-8"))["interrupted"] is True


@unix_only
def test_a_second_signal_stops_at_once(tmp_path):
    process = _start(tmp_path, "### 3. Long Clean Up (`logic.delay`)\n- **seconds:** 60\n")
    process.send_signal(signal.SIGTERM)
    time.sleep(1.0)
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=10)
    assert process.returncode == exit_codes.INTERRUPTED
    assert not list((tmp_path / "logs").rglob("*_interrupted.json"))
