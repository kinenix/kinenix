"""1.0.0: failures from outside the flow (docs/roadmap.md, failure-injection tests).

The Hub is down, slow, or broken during a run; an input file is missing; the browser dies in the middle of a
loop. In every case the run finishes on its own, keeps its log, says what happened once, and leaves no
browser process behind.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kinenix import exit_codes
from kinenix.actions.base import BaseAction
from kinenix.actions.registry import register_action
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow

WAIT = "# Hub Test\n\n## Steps\n\n### 1. Wait (`logic.delay`)\n- **seconds:** 0\n"


def _cli(tmp_path, *args, **env):
    return subprocess.run([sys.executable, "-m", "kinenix.cli", *args], cwd=tmp_path,
                          env={**os.environ, "KINENIX_FLOWS_DIR": str(tmp_path),
                               # Runs kept for the Hub (#173) stay in this test's folder
                               "KINENIX_SETTINGS_FILE": str(tmp_path / "settings" / "kinenix.env"), **env},
                          capture_output=True, text=True, timeout=120)


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Hub(http.server.ThreadingHTTPServer):
    """A Hub that answers telemetry late or with an error."""

    def __init__(self, delay: float = 0.0, status: int = 200):
        self.delay, self.status, self.posts = delay, status, 0
        hub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                hub.posts += 1
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                time.sleep(hub.delay)
                try:
                    self.send_response(hub.status)
                    self.end_headers()
                    self.wfile.write(b'{"detail": "database is locked"}')
                except OSError:
                    pass  # the run stopped waiting

            def log_message(self, *args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server_address[1]}"
        threading.Thread(target=self.serve_forever, daemon=True).start()


def _run_with_hub(tmp_path, hub_url, caplog):
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=str(tmp_path / "logs")))
    started = time.monotonic()
    with caplog.at_level("WARNING"):
        context = interpreter.run_flow(markdown_to_flow(WAIT), initial_vars={"hub_url": hub_url})
    return context, time.monotonic() - started


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def test_a_hub_that_is_down_does_not_stop_the_run(tmp_path):
    (tmp_path / "ok").mkdir()
    (tmp_path / "ok" / "flow.md").write_text(WAIT, encoding="utf-8")
    result = _cli(tmp_path, "run", "ok", "--log-dir", str(tmp_path / "logs"),
                  KINENIX_HUB_URL=f"http://127.0.0.1:{_free_port()}",
                  KINENIX_SETTINGS_FILE=str(tmp_path / "settings" / "kinenix.env"))
    assert result.returncode == exit_codes.OK, result.stderr
    assert list((tmp_path / "logs").rglob("*_success.json"))
    output = result.stdout + result.stderr
    assert output.count("The run was not sent to the Hub") == 1
    # Kept in the outbox and sent when the Hub is back (#173)
    assert "The run is kept on this machine and sent when the Hub can be reached again" in output
    assert len(list((tmp_path / "settings" / "outbox").glob("*.json"))) == 1


def test_a_slow_hub_is_given_up_on_and_the_log_is_kept(tmp_path, caplog):
    hub = _Hub(delay=15)
    try:
        context, seconds = _run_with_hub(tmp_path, hub.url, caplog)
    finally:
        hub.shutdown()
    assert not context.has_error
    assert seconds < 12, f"the run waited {seconds:.1f} s for the Hub"
    assert hub.posts == 1  # sent once, not retried while the run waits
    assert list((tmp_path / "logs").rglob("*_success.json"))
    sent = [w for w in _warnings(caplog) if "not sent to the Hub" in w]
    assert len(sent) == 1 and "firewall" not in sent[0]  # it answered the connection, so no firewall blocks it


def test_a_hub_that_answers_with_an_error_is_reported_once(tmp_path, caplog):
    hub = _Hub(status=500)
    try:
        context, _ = _run_with_hub(tmp_path, hub.url, caplog)
    finally:
        hub.shutdown()
    assert not context.has_error
    assert list((tmp_path / "logs").rglob("*_success.json"))
    assert [w for w in _warnings(caplog) if "HTTP 500" in w] and len(_warnings(caplog)) == 1


def test_a_missing_input_file_fails_the_run_but_on_error_and_finally_still_run(tmp_path):
    flow = """# Read Orders

## Steps

### 1. Read Orders (`csv.read`)
- **file_path:** ./input/orders.csv
- **output_var:** `orders`

### 2. Never Reached (`file.write_text`)
- **path:** ./output/reached.txt
- **content:** reached

## On Error

### 3. Note The Failure (`file.write_text`)
- **path:** ./output/on_error.txt
- **content:** ${error.message}

## Finally

### 4. Always (`file.write_text`)
- **path:** ./output/finally.txt
- **content:** done
"""
    bundle = tmp_path / "orders"
    bundle.mkdir()
    (bundle / "flow.md").write_text(flow, encoding="utf-8")
    result = _cli(tmp_path, "run", "orders", "--log-dir", str(tmp_path / "logs"))
    assert result.returncode == exit_codes.TECHNICAL, result.stderr
    assert "orders.csv" in result.stdout + result.stderr  # the message names the file
    output = bundle / "output"
    assert not (output / "reached.txt").exists()
    assert "orders.csv" in (output / "on_error.txt").read_text(encoding="utf-8")
    assert (output / "finally.txt").read_text(encoding="utf-8") == "done"
    assert list((tmp_path / "logs").rglob("*_failed.json"))


# --- The browser dies in the middle of a loop -------------------------------------------------------------

def _browser_processes():
    """Chromium and Playwright driver processes started by this test process."""
    psutil = pytest.importorskip("psutil")
    found = []
    for child in psutil.Process().children(recursive=True):
        try:
            name = child.name().lower()
            if any(part in name for part in ("chrom", "headless_shell", "node", "playwright")):
                found.append(child)
        except psutil.Error:
            pass
    return found


@register_action("test.kill_browser")
class _KillBrowser(BaseAction):
    """Kills the browser as a crash or a person closing it would: the Playwright driver stays."""
    accepted_parameters = ()
    side_effects = ("none",)

    def execute(self, parameters, context):
        import psutil
        for process in _browser_processes():
            if "node" not in process.name().lower() and "playwright" not in process.name().lower():
                try:
                    process.kill()
                except psutil.Error:
                    pass
        time.sleep(0.5)
        return True


def test_the_browser_closing_in_a_loop_fails_the_items_and_finally_still_runs(tmp_path, chromium):
    pytest.importorskip("psutil")
    page = tmp_path / "page.html"
    page.write_text("<h1 id='title'>Orders</h1>", encoding="utf-8")
    flow = f"""# Browser Dies
> Requires: kinenix>=0.4.0b1

## Steps

### 1. Open (`web.open`)
- **url:** {page.as_uri()}
- **headless:** true

### 2. Each Order (`logic.loop`)
- **items:** [1, 2, 3]
- **item_var:** n
- **item_label:** order ${{n}}
- **Sub-steps:**
  - Browser Dies On The Second (`test.kill_browser`):
    - **condition:** `${{n}} == 2`
  - Read Title (`web.get_text`):
    - **selector:** #title
    - **output_var:** `title`
    - **on_error:** next_item

## Finally

### 3. Close (`web.close`)

### 4. Mark (`logic.set_variable`)
- **name:** finally_ran
- **value:** yes
"""
    started = time.monotonic()
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=str(tmp_path / "logs"))).run_flow(markdown_to_flow(flow))
    seconds = time.monotonic() - started

    assert context.get_variable("finally_ran") == "yes"
    assert context.items == {"total": 3, "done": 1, "failed": 2}
    assert seconds < 60, f"the dead browser made the run wait {seconds:.0f} s"
    assert list((tmp_path / "logs").rglob("*.json"))
    deadline = time.monotonic() + 10
    while _browser_processes() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert _browser_processes() == [], "a browser or Playwright process was left behind"
