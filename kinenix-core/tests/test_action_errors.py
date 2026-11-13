"""#219: errors raised by Kinenix's own actions get a root_cause and suggested_fix that name the value and the step."""
import pytest

from kinenix.engine.action_errors import explain
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow


@pytest.mark.parametrize("message, cause, fix", [
    # Pi Hub, Motor Insurance Quote Requests, 2026-11-12: the fix used to be "Inspect input parameters to step 'step_6'"
    ("web.choose: option 'CX-30' not found; available: CX-3",
     "The value 'CX-30' is not one of the options in step 'Choose Model'. The page offers: CX-3.",
     "Check this item's input data"),
    ("web.choose: option 'CX-30' not found; available: ",
     "The page showed no options at all.", "Check this item's input data"),
    ("web.choose: option 'hr v' matches several options loosely: HR-V, HRV; give the exact name.",
     "The value 'hr v' matches more than one option in step 'Choose Model': HR-V, HRV.", "match: exact"),
    ("web.choose: the search box shows no options for 'Mazda'. The site filters by what is typed: set search_text "
     "to the start of the name as the site writes it (for example its first two letters), and keep match: loose to "
     "pick it.",
     "The search box in step 'Choose Model' showed no options for 'Mazda'.", "set search_text"),
    ("web.choose: no options appeared after clicking the dropdown; check the selector of the trigger, or set search: "
     "true if the list needs typing first.",
     "No options appeared after step 'Choose Model' clicked the dropdown.", "search: true"),
    ("web.choose: 'option' is empty. Check the value or the variable it refers to.",
     "The parameter 'option' of step 'Choose Model' was empty", "set for this item"),
    ("web.open: 'url' is empty. Check that the variable it refers to (for example config.url) is set.",
     "The parameter 'url' of step 'Choose Model' was empty", "a config value"),
    ("web.get_list: no element matches 'article.product_pod' within 10000 ms.",
     "Step 'Choose Model' found no element matching 'article.product_pod' within 10 s.", "screenshot"),
    ("web.get_list: expected at least 1 item(s) matching 'article.product_pod', found 0.",
     "read 0 items from 'article.product_pod', fewer than min_rows (1).", "lower min_rows"),
    ("web.get_table: expected at least 3 row(s) in 'table.rates', found 1.",
     "read 1 rows from 'table.rates', fewer than min_rows (3).", "lower min_rows"),
    ("web.get_list: item 4 has no 'price' (selector '.price_color'); the item reads {'title': 'A', 'price': ''}.",
     "Item 4 on the page has no 'price' (selector '.price_color')", "on_item_error: skip"),
    ("web.get_table: column(s) ['Rate'] not found; table headers are ['Currency', 'Buying']",
     "has no column ['Rate']; its headers are ['Currency', 'Buying']", "use the names shown"),
    ("No active browser page found. Please execute 'web.open' first.",
     "Step 'Choose Model' needs an open browser page, but none was open.", "Add a web.open"),
    ("Destination already exists and overwrite is false: output/report.csv",
     "'output/report.csv' already exists, and step 'Choose Model' does not overwrite it.", "overwrite: true"),
    ("Zip file already exists and overwrite is false: out.zip", "'out.zip' already exists", "${run.id}"),
    ("Could not read input/cars.csv as utf-8. Thai files from older systems are often 'cp874' or 'tis-620'; set "
     "the encoding parameter.",
     "could not read input/cars.csv as utf-8: the file uses another encoding.", "cp874"),
    ("GET https://api.example/cars/7 answered HTTP 404: {'detail': 'Not Found'}",
     "In step 'Choose Model', GET https://api.example/cars/7: the address was not found (HTTP 404)", "Check the URL"),
    ("POST https://api.example/quotes answered HTTP 401: denied",
     "asked for a login (HTTP 401)", "environment variable"),
    ("GET https://api.example/x answered HTTP 503: down",
     "the service had an error of its own (HTTP 503)", "Retry later (max_retries with retry_interval)"),
    ("GET https://api.example/x answered HTTP 418: teapot", "the service answered HTTP 418", "documentation"),
])
def test_known_action_messages(message, cause, fix):
    explained = explain(message, "Choose Model")
    assert explained is not None, message
    assert cause in explained.root_cause, explained.root_cause
    assert fix in explained.suggested_fix, explained.suggested_fix


@pytest.mark.parametrize("message", ["", "division by zero", "date.calc could not read date 'soon'.",
                                     "Locator.click: Timeout 5000ms exceeded."])
def test_unknown_messages_are_not_guessed(message):
    assert explain(message, "Any") is None


def _run(tmp_path, steps):
    md = f"# Causes\n\n## Steps\n\n{steps}"
    return FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(
        markdown_to_flow(md), initial_vars={"__flow_dir__": str(tmp_path)})


def test_a_message_no_rule_knows_names_the_step_and_its_line(tmp_path):
    ctx = _run(tmp_path, "### 1. Start Date (`date.calc`)\n- **date:** soon\n- **output_var:** start\n")
    assert ctx.has_error
    fix = ctx.failure_details.suggested_fix
    assert "step 'Start Date' (line 5)" in fix, fix
    assert "step_1" not in fix


def test_a_file_that_exists_is_explained_in_a_real_run(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    ctx = _run(tmp_path, "### 1. Copy The File (`file.copy`)\n- **source:** a.txt\n- **destination:** b.txt\n"
                            "- **overwrite:** false\n")
    assert ctx.has_error
    assert "already exists, and step 'Copy The File' does not overwrite it" in ctx.failure_details.root_cause
    assert "overwrite: true" in ctx.failure_details.suggested_fix


CHOOSE_PAGE = """<!doctype html><html><body>
<select id="model"><option>CX-3</option><option>CX-5</option></select>
</body></html>"""


def test_a_real_web_choose_names_the_value_and_the_options(tmp_path, chromium):
    page = tmp_path / "choose.html"
    page.write_text(CHOOSE_PAGE, encoding="utf-8")
    ctx = _run(tmp_path, f"""### 1. Open (`web.open`)
- **url:** {page.as_uri()}
- **headless:** true

### 2. Choose Model (`web.choose`)
- **selector:** `#model`
- **option:** CX-30
""")
    assert ctx.has_error
    assert ctx.failure_details.root_cause == (
        "The value 'CX-30' is not one of the options in step 'Choose Model'. The page offers: CX-3, CX-5.")
