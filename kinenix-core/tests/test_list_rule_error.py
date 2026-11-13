"""#146: rule_error on web.get_list and web.get_table makes a list that breaks its rules (min_rows, required
fields, numbers) a business error, which is not retried. 'system' means technical, as in other RPA tools."""
import pytest

from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow
from kinenix.engine.validation import validate_flow

PAGE = """<!doctype html><html><body>
<h1 class="category">Poetry</h1>
<table id="t"><thead><tr><th>Title</th><th>Price</th></tr></thead><tbody>
<tr><td>A</td><td>51.77</td></tr><tr><td>B</td><td>N/A</td></tr></tbody></table>
<article class="book"><h3>A Light in the Attic</h3><p class="price">51.77</p></article>
<article class="book"><h3></h3><p class="price">53.74</p></article>
</body></html>"""
EMPTY = """<!doctype html><html><body><h1 class="category">Travel</h1><p>No books found</p></body></html>"""

BOOKS = """### 2. Books (`web.get_list`)
- **selector:** `article.book`
- **fields:** {"title": "h3", "price": ".price"}
- **required_fields:** ["title"]
- **timeout:** 1000
- **max_retries:** 2
- **retry_interval:** 0
- **output_var:** `books`
"""
PRICES = """### 2. Prices (`web.get_table`)
- **selector:** `#t`
- **numeric_columns:** ["Price"]
- **max_retries:** 2
- **retry_interval:** 0
- **output_var:** `rows`
"""


@pytest.fixture
def pages(tmp_path, chromium):
    urls = {}
    for name, html in (("page", PAGE), ("empty", EMPTY)):
        path = tmp_path / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        urls[name] = path.as_uri()
    return urls


def _run(steps, url):
    flow = f"# Web\n\n## Steps\n\n### 1. Open (`web.open`)\n- **url:** {url}\n- **headless:** true\n\n{steps}"
    return FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(markdown_to_flow(flow))


def _failure(context):
    assert context.has_error
    error = context.get_variable("error")
    return context.failure_details.error_type, error["retries"], context.failure_details.error_message


def test_by_default_a_broken_rule_is_technical_and_retried(pages):
    kind, retries, message = _failure(_run(BOOKS, pages["page"]))
    assert (kind, retries) == ("Technical", 2) and "item 2 has no 'title'" in message


def test_rule_error_business_is_not_retried(pages):
    kind, retries, message = _failure(_run(BOOKS + "- **rule_error:** business\n", pages["page"]))
    assert (kind, retries) == ("Business", 0) and "item 2 has no 'title'" in message


def test_an_empty_category_is_a_business_error_with_the_flows_own_message(pages):
    steps = (BOOKS.replace('- **required_fields:** ["title"]\n', "- **min_rows:** 1\n")
             + "- **rule_error:** business\n- **error_message:** Category ${category} shows no books\n")
    flow_steps = "### 0. Name (`logic.set_variable`)\n- **name:** category\n- **value:** Travel\n\n" + steps
    kind, retries, message = _failure(_run(flow_steps, pages["empty"]))
    assert (kind, retries, message) == ("Business", 0, "Category Travel shows no books")


def test_fewer_rows_than_min_rows_is_a_business_error(pages):
    steps = BOOKS.replace('- **required_fields:** ["title"]\n', "- **min_rows:** 3\n") + "- **rule_error:** business\n"
    kind, retries, message = _failure(_run(steps, pages["page"]))
    assert (kind, retries) == ("Business", 0) and "expected at least 3 item(s)" in message


def test_get_table_numbers_and_min_rows_follow_rule_error(pages):
    kind, retries, message = _failure(_run(PRICES + "- **rule_error:** business\n", pages["page"]))
    assert (kind, retries) == ("Business", 0) and "value 'N/A' in column 'Price' is not a number" in message
    fewer = PRICES.replace('- **numeric_columns:** ["Price"]\n', "- **min_rows:** 5\n") + "- **rule_error:** business\n"
    kind, retries, message = _failure(_run(fewer, pages["page"]))
    assert (kind, retries) == ("Business", 0) and "expected at least 5 row(s)" in message


def test_on_item_error_skip_still_keeps_the_good_items(pages):
    context = _run(BOOKS + "- **rule_error:** business\n- **on_item_error:** skip\n", pages["page"])
    assert not context.has_error
    assert [b["title"] for b in context.get_variable("books")] == ["A Light in the Attic"]


def test_system_means_technical_and_a_wrong_value_says_which_values_work(pages):
    kind, retries, _ = _failure(_run(BOOKS + "- **rule_error:** System\n", pages["page"]))
    assert (kind, retries) == ("Technical", 2)
    _, _, message = _failure(_run(BOOKS + "- **rule_error:** data\n", pages["page"]))
    assert "rule_error must be business or technical (system means technical), not 'data'" in message


@pytest.mark.parametrize("category, kind", [("business", "Business"), ("technical", "Technical"),
                                            ("system", "Technical"), ("", "Business")])
def test_flow_fail_category_accepts_system_for_technical(category, kind):
    line = f"- **category:** {category}\n" if category else ""
    flow = f"# F\n\n## Steps\n\n### 1. Stop (`flow.fail`)\n- **message:** stop here\n{line}"
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(markdown_to_flow(flow))
    assert context.failure_details.error_type == kind
    assert context.failure_details.error_message == "stop here"


def test_flow_fail_names_the_values_for_a_wrong_category():
    flow = "# F\n\n## Steps\n\n### 1. Stop (`flow.fail`)\n- **message:** stop here\n- **category:** data\n"
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(markdown_to_flow(flow))
    assert "category must be business or technical (system means technical)" in context.failure_details.error_message


@pytest.mark.parametrize("steps, feature", [
    (BOOKS + "- **rule_error:** business\n", "rule_error on web.get_list or web.get_table"),
    ("### 2. Stop (`flow.fail`)\n- **message:** x\n- **category:** system\n", "category: system on flow.fail"),
])
def test_validate_asks_for_1_1_0(steps, feature):
    flow = markdown_to_flow(f"# F\n\n## Steps\n\n{steps}")
    issues = [i for i in validate_flow(flow) if "older workers" in i]
    assert len(issues) == 1 and feature in issues[0] and "kinenix>=1.1.0" in issues[0]
