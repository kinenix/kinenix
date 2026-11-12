"""on_error: ignore (#197) and a step's error_message (#193)."""
import pytest

from kinenix import exit_codes
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import flow_to_markdown, markdown_to_flow
from kinenix.engine.validation import validate_flow

ITEMS = [{"no": "A"}, {"no": "B"}, {"no": "C"}]


def run(markdown, tmp_path=None, **initial):
    flow = markdown_to_flow(markdown)
    return FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(
        flow, initial_vars={"items": ITEMS, **initial})


def loop(on_error, extra=""):
    return f"""# Popups

## Steps

### 1. Each Item (`logic.loop`)
- **items:** ${{items}}
- **item_var:** it
- **item_label:** ${{it.no}}
- **Sub-steps:**
  - Close Popup If Shown (`file.read_text`):
    - **path:** ./no-popup-here.txt
    - **on_error:** {on_error}
{extra}
  - Keep (`logic.append`):
    - **target:** done
    - **item:** ${{it.no}}

### 2. After (`logic.set_variable`)
- **name:** after
- **value:** reached
"""


# on_error: ignore -------------------------------------------------------------------------------------

def test_an_ignored_failure_is_recorded_but_the_run_succeeds():
    ctx = run(loop("ignore"))
    assert ctx.get_variable("done") == ["A", "B", "C"] and ctx.get_variable("after") == "reached"
    assert ctx.items == {"total": 3, "done": 3, "failed": 0}
    assert not ctx.has_error and not ctx.is_partial
    assert exit_codes.for_run(ctx) == exit_codes.OK
    assert ctx.metrics.failed_steps == 0
    ignored = [r for r in ctx.step_results if r.status == "failed"]
    assert len(ignored) == 3 and all(r.failure["handled"] == "ignored" for r in ignored)


def test_continue_still_counts_the_failure():
    ctx = run(loop("continue"))
    assert ctx.items["failed"] == 3 and ctx.is_partial
    assert exit_codes.for_run(ctx) == exit_codes.PARTIAL


def test_ignore_retries_first_and_sets_error():
    ctx = run(loop("ignore", "    - **max_retries:** 1\n    - **retry_interval:** 0"))
    first = next(r for r in ctx.step_results if r.status == "failed")
    assert first.retries == 1
    assert "no-popup-here.txt" in ctx.get_variable("error")["message"]


def test_an_ignored_subflow_does_not_fail_the_item(tmp_path):
    (tmp_path / "subflows").mkdir()
    (tmp_path / "subflows" / "popup.md").write_text(
        "# Popup\n\n## Steps\n\n### 1. Read (`file.read_text`)\n- **path:** ./missing.txt\n", encoding="utf-8")
    md = loop("ignore").replace(
        "  - Close Popup If Shown (`file.read_text`):\n    - **path:** ./no-popup-here.txt",
        "  - Close Popup If Shown (`flow.call`):\n    - **flow:** ./subflows/popup.md")
    ctx = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(
        markdown_to_flow(md), initial_vars={"items": ITEMS, "__flow_dir__": str(tmp_path)})
    assert ctx.items == {"total": 3, "done": 3, "failed": 0}
    assert exit_codes.for_run(ctx) == exit_codes.OK


def test_ignore_in_finally_does_not_fail_the_run():
    md = loop("ignore") + "\n## Finally\n\n### 1. Clean Up (`file.read_text`)\n- **path:** ./gone.txt\n- **on_error:** ignore\n"
    ctx = run(md)
    assert exit_codes.for_run(ctx) == exit_codes.OK


# error_message ------------------------------------------------------------------------------------------

OPEN = """# Open

## Steps

### 1. Open The Site (`file.read_text`)
- **path:** ./site.txt
- **error_message:** เปิดเว็บไม่ได้: ${{error.message}}
{extra}
### 2. After (`logic.set_variable`)
- **name:** after
- **value:** reached
"""


def test_error_message_replaces_the_failure_message_and_can_use_the_original():
    ctx = run(OPEN.format(extra=""))
    assert ctx.has_error and exit_codes.for_run(ctx) == exit_codes.TECHNICAL
    message = ctx.failure_details.error_message
    assert message.startswith("เปิดเว็บไม่ได้: ") and "site.txt" in message
    assert ctx.step_results[0].error_message == message
    assert ctx.get_variable("error")["message"] == message


def test_error_message_with_continue_keeps_going():
    ctx = run(OPEN.format(extra="- **on_error:** continue\n"))
    assert ctx.get_variable("after") == "reached"
    assert ctx.step_results[0].error_message.startswith("เปิดเว็บไม่ได้: ")


def test_error_message_that_cannot_be_read_keeps_the_original(caplog):
    ctx = run(OPEN.format(extra="").replace("${error.message}", "${len(1, 2)}"))
    assert "site.txt" in ctx.failure_details.error_message
    assert any("error_message could not be read" in r.getMessage() for r in caplog.records)


def test_error_message_survives_flow_md_round_trip():
    flow = markdown_to_flow(OPEN.format(extra="- **on_error:** ignore\n"))
    handler = flow.steps[0].error_handler
    assert handler.error_message == "เปิดเว็บไม่ได้: ${error.message}" and handler.on_error == "ignore"
    again = markdown_to_flow(flow_to_markdown(flow))
    assert again.steps[0].error_handler == handler


# kinenix validate ---------------------------------------------------------------------------------------

def test_validate_accepts_ignore_and_asks_for_requires():
    issues = validate_flow(markdown_to_flow(loop("ignore")))
    assert not any("is not one of" in i for i in issues)
    assert any("on_error: ignore" in i and "Requires: kinenix>=1.1.0" in i for i in issues)


def test_validate_asks_for_requires_for_error_message():
    issues = validate_flow(markdown_to_flow(OPEN.format(extra="")))
    assert any("error_message" in i and "Requires: kinenix>=1.1.0" in i for i in issues)


@pytest.mark.parametrize("action", ["logic.if", "logic.loop"])
def test_validate_reports_error_message_on_a_block(action):
    md = (f"# B\n\n## Steps\n\n### 1. Block (`{action}`)\n- **condition:** `${{x}} == 1`\n- **items:** ${{items}}\n"
          f"- **error_message:** nope\n- **Sub-steps:**\n  - Set (`logic.set_variable`):\n    - **name:** a\n    - **value:** 1\n")
    assert any("error_message has no effect" in i for i in validate_flow(markdown_to_flow(md)))
