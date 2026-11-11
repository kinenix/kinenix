"""logic.break and loops with times (docs/design/loop-control.md, #191)."""
import pytest

from kinenix import exit_codes
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow
from kinenix.engine.validation import validate_flow


def run(markdown, **initial):
    return FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(markdown_to_flow(markdown), initial_vars=initial)


def pages(times="5", stop_at="3", label="- **item_label:** Page ${page}\n", extra=""):
    return f"""# Pages

## Steps

### 1. Each Page (`logic.loop`)
- **times:** {times}
- **item_var:** page
{label}- **Sub-steps:**
  - Read (`logic.append`):
    - **target:** read
    - **item:** ${{page}}
  - Last Page (`logic.break`):
    - **condition:** `${{page}} == {stop_at}`
  - Next (`logic.append`):
    - **target:** clicked
    - **item:** ${{page}}
{extra}
### 2. After (`logic.set_variable`)
- **name:** after
- **value:** reached
"""


def loop_step(ctx):
    return next(r for r in ctx.step_results if r.action == "logic.loop")


# times ------------------------------------------------------------------------------------------------

def test_times_runs_that_many_iterations_numbered_from_1():
    ctx = run(pages(stop_at="99"))
    assert ctx.get_variable("read") == [1, 2, 3, 4, 5]
    assert ctx.get_variable("page_index") == 4
    assert loop_step(ctx).output == {"total_items_processed": 5, "stopped_early": False}
    assert ctx.items == {"total": 5, "done": 5, "failed": 0}
    assert exit_codes.for_run(ctx) == exit_codes.OK  # running out of times is not an error


@pytest.mark.parametrize("times, expected", [("${config.max_pages}", [1, 2]), ("0", None), ("2.0", [1, 2])])
def test_times_from_a_value(times, expected):
    ctx = run(pages(times=times, stop_at="99"), config={"max_pages": 2})
    assert ctx.get_variable("read") == expected and ctx.get_variable("after") == "reached"


@pytest.mark.parametrize("times", ["abc", "-1", "2.5", "10001"])
def test_bad_times_stops_with_exit_code_4(times):
    ctx = run(pages(times=times))
    assert ctx.has_error and exit_codes.for_run(ctx) == exit_codes.INVALID_FLOW
    assert "times must be a whole number from 0 to 10000" in ctx.failure_details.error_message


# logic.break ------------------------------------------------------------------------------------------

def test_break_leaves_the_loop_and_skips_the_rest_of_the_iteration():
    ctx = run(pages())
    assert ctx.get_variable("read") == [1, 2, 3]
    assert ctx.get_variable("clicked") == [1, 2]       # page 3 broke before Next
    assert ctx.get_variable("after") == "reached"
    assert loop_step(ctx).output == {"total_items_processed": 3, "stopped_early": True}
    breaks = [r for r in ctx.step_results if r.action == "logic.break"]
    assert [r.status for r in breaks] == ["skipped", "skipped", "success"]
    assert breaks[-1].output == {"status": "loop stopped"}


def test_items_not_reached_are_not_counted():
    ctx = run(pages(times="10", stop_at="4"))
    assert ctx.items == {"total": 4, "done": 4, "failed": 0}
    assert exit_codes.for_run(ctx) == exit_codes.OK


def test_break_in_a_loop_over_items():
    md = """# Items

## Steps

### 1. Each (`logic.loop`)
- **items:** ${names}
- **item_var:** name
- **Sub-steps:**
  - Stop At Bob (`logic.break`):
    - **condition:** `${name} == Bob`
  - Keep (`logic.append`):
    - **target:** kept
    - **item:** ${name}
"""
    ctx = run(md, names=["Ann", "Bob", "Cid"])
    assert ctx.get_variable("kept") == ["Ann"]


def test_break_inside_logic_if_leaves_the_loop():
    md = pages().replace("""  - Last Page (`logic.break`):
    - **condition:** `${page} == 3`
""", """  - Check (`logic.if`):
    - **condition:** `${page} == 3`
    - **Sub-steps:**
      - Last Page (`logic.break`):
""")
    ctx = run(md)
    assert ctx.get_variable("read") == [1, 2, 3] and ctx.get_variable("clicked") == [1, 2]


def test_break_in_a_nested_loop_ends_only_the_inner_loop():
    md = """# Nested

## Steps

### 1. Outer (`logic.loop`)
- **times:** 3
- **item_var:** row
- **Sub-steps:**
  - Inner (`logic.loop`):
    - **times:** 5
    - **item_var:** col
    - **Sub-steps:**
      - Stop (`logic.break`):
        - **condition:** `${col} == 2`
      - Cell (`logic.append`):
        - **target:** cells
        - **item:** ${row}-${col}
"""
    ctx = run(md)
    assert ctx.get_variable("cells") == ["1-1", "2-1", "3-1"]


def test_break_in_finally():
    md = pages(stop_at="99") + """
## Finally

### 1. Clean (`logic.loop`)
- **times:** 3
- **Sub-steps:**
  - Done (`logic.break`):
  - Never (`logic.set_variable`):
    - **name:** never
    - **value:** yes
"""
    ctx = run(md)
    assert ctx.get_variable("never") is None and exit_codes.for_run(ctx) == exit_codes.OK


def test_break_outside_a_loop_stops_with_exit_code_4():
    ctx = run("# B\n\n## Steps\n\n### 1. Stop (`logic.break`)\n\n### 2. After (`logic.set_variable`)\n- **name:** after\n- **value:** x\n")
    assert ctx.has_error and exit_codes.for_run(ctx) == exit_codes.INVALID_FLOW
    assert "outside a logic.loop" in ctx.failure_details.error_message
    assert ctx.get_variable("after") is None


def test_break_in_a_subflow_does_not_leave_the_callers_loop(tmp_path):
    (tmp_path / "subflows").mkdir()
    (tmp_path / "subflows" / "one.md").write_text("# One\n\n## Steps\n\n### 1. Stop (`logic.break`)\n", encoding="utf-8")
    md = """# Caller

## Steps

### 1. Each (`logic.loop`)
- **times:** 3
- **Sub-steps:**
  - Call (`flow.call`):
    - **flow:** ./subflows/one.md
    - **on_error:** continue
  - Count (`logic.append`):
    - **target:** went_on
    - **item:** ${item}
"""
    ctx = run(md, __flow_dir__=str(tmp_path))
    assert ctx.get_variable("went_on") == [1, 2, 3]  # the caller's loop was not left


# kinenix validate ---------------------------------------------------------------------------------------

def issues(md):
    return validate_flow(markdown_to_flow(md))


def test_validate_asks_for_requires_1_1_0():
    found = issues(pages())
    assert any("logic.break" in i and "times on logic.loop" in i and "Requires: kinenix>=1.1.0" in i for i in found)
    assert not any("Requires" in i for i in issues("# P\n\n> Requires: kinenix>=1.1.0\n\n" + pages().split("\n", 2)[2]))


def test_validate_reports_break_outside_a_loop():
    assert any("logic.break is outside a logic.loop" in i
               for i in issues("# B\n\n## Steps\n\n### 1. Stop (`logic.break`)\n"))


@pytest.mark.parametrize("params, problem", [
    ("- **items:** ${x}\n- **times:** 3\n", "not both"),
    ("- **item_var:** x\n", "has neither"),
])
def test_validate_reports_items_and_times(params, problem):
    md = f"# L\n\n## Steps\n\n### 1. Loop (`logic.loop`)\n{params}- **Sub-steps:**\n  - S (`logic.set_variable`):\n    - **name:** a\n    - **value:** 1\n"
    assert any(problem in i for i in issues(md))


def test_validate_reports_error_keys_on_break():
    md = pages().replace("    - **condition:** `${page} == 3`\n", "    - **condition:** `${page} == 3`\n    - **on_error:** continue\n")
    assert any("has no effect on logic.break" in i for i in issues(md))


# logic.next -------------------------------------------------------------------------------------------

BOOKS_MD = """# Books

## Steps

### 1. Each Book (`logic.loop`)
- **items:** ${books}
- **item_var:** book
- **item_label:** ${book.title}
- **Sub-steps:**
  - Skip Out Of Stock (`logic.next`):
    - **condition:** `${book.availability} contains Out of stock`
  - Open (`logic.append`):
    - **target:** opened
    - **item:** ${book.title}
  - Save (`logic.append`):
    - **target:** saved
    - **item:** ${book.title}
"""
BOOKS = [{"title": "A", "availability": "In stock"}, {"title": "B", "availability": "Out of stock"},
         {"title": "C", "availability": "In stock"}]


def test_next_skips_the_rest_of_the_item_and_counts_it_as_done():
    ctx = run(BOOKS_MD, books=BOOKS)
    assert ctx.get_variable("opened") == ["A", "C"] and ctx.get_variable("saved") == ["A", "C"]
    assert ctx.items == {"total": 3, "done": 3, "failed": 0}
    assert exit_codes.for_run(ctx) == exit_codes.OK
    nexts = [r for r in ctx.step_results if r.action == "logic.next"]
    assert [r.status for r in nexts] == ["skipped", "success", "skipped"]
    assert nexts[1].output == {"status": "next item"}


def test_next_in_a_times_loop_and_inside_logic_if():
    md = pages(stop_at="99").replace("""  - Last Page (`logic.break`):
    - **condition:** `${page} == 99`
""", """  - Even Pages (`logic.if`):
    - **condition:** `${page % 2} == 0`
    - **Sub-steps:**
      - Skip (`logic.next`):
""")
    ctx = run(md)
    assert ctx.get_variable("read") == [1, 2, 3, 4, 5] and ctx.get_variable("clicked") == [1, 3, 5]


def test_next_after_a_continued_failure_still_counts_the_item_as_failed():
    md = BOOKS_MD.replace("""  - Skip Out Of Stock (`logic.next`):""", """  - Read (`file.read_text`):
    - **path:** ./missing.txt
    - **on_error:** continue
  - Skip Out Of Stock (`logic.next`):""")
    ctx = run(md, books=BOOKS)
    assert ctx.items == {"total": 3, "done": 0, "failed": 3}


def test_next_outside_a_loop_stops_with_exit_code_4_and_validate_reports_it():
    md = "# N\n\n## Steps\n\n### 1. Next (`logic.next`)\n"
    ctx = run(md)
    assert exit_codes.for_run(ctx) == exit_codes.INVALID_FLOW
    assert any("logic.next is outside a logic.loop" in i for i in issues(md))


def test_validate_asks_for_requires_for_next():
    assert any("logic.next" in i and "Requires: kinenix>=1.1.0" in i for i in issues(BOOKS_MD))
