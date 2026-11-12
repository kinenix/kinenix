"""#198: kinenix validate asks for `> Requires:` when a flow uses a feature added after 0.4.0b1 that an older worker
would run wrongly instead of refusing."""
import pytest

from kinenix.engine.markdown import markdown_to_flow
from kinenix.engine.validation import validate_flow


def _version_issues(steps, requires=""):
    header = f"> Requires: {requires}\n" if requires else ""
    flow = markdown_to_flow(f"# Newer\n{header}\n## Steps\n\n{steps}")
    return [p for p in validate_flow(flow) if "older workers" in p]


CHOOSE = "### 1. Choose (`web.choose`)\n- **selector:** `#model`\n- **option:** HRV\n- **match:** loose\n"
SEARCH = "### 1. Choose (`web.choose`)\n- **selector:** `#model`\n- **option:** HR-V\n- **search_text:** HR\n"
HTTP = "### 1. Call (`http.request`)\n- **url:** https://api.example/x\n- **fail_on_error:** true\n"
ROUND = "### 1. Total (`logic.set_variable`)\n- **name:** total\n- **value:** ${round(price, 2)}\n"
LIST = ("### 1. Books (`web.get_list`)\n- **selector:** article\n- **fields:** {\"title\": \"h3\"}\n"
        "- **required_fields:** [\"title\"]\n- **on_item_error:** skip\n- **output_var:** books\n")
TABLE = "### 1. Rates (`web.get_table`)\n- **selector:** table\n- **on_item_error:** skip\n- **output_var:** rates\n"


@pytest.mark.parametrize("steps, feature, needed, effect", [
    (CHOOSE, "match or search_text on web.choose", "0.5.0b1", "Kinenix 0.4.0b1 and older ignores match"),
    (SEARCH, "match or search_text on web.choose", "0.5.0b1", "is not found"),
    (HTTP, "fail_on_error on http.request", "1.0.0", "Kinenix 1.0.0rc2 and older ignores fail_on_error"),
    (ROUND, "round() on halves", "1.0.0", "round(2.5) gives 2"),
    (LIST, "on_item_error on web.get_list or web.get_table", "1.1.0", "Kinenix 1.0.1 and older ignores on_item_error"),
    (TABLE, "on_item_error on web.get_list or web.get_table", "1.1.0", "first item with a missing field"),
])
def test_a_newer_feature_asks_for_the_version_that_understands_it(steps, feature, needed, effect):
    issues = _version_issues(steps)
    assert len(issues) == 1, issues
    assert feature in issues[0] and effect in issues[0]
    assert f"Add `> Requires: kinenix>={needed}`" in issues[0]
    assert _version_issues(steps, f"kinenix>={needed}") == []


def test_fail_on_error_false_is_what_older_versions_did_anyway():
    assert _version_issues(HTTP.replace("true", "false")) == []
    assert _version_issues(HTTP.replace("- **fail_on_error:** true\n", "")) == []


def test_web_choose_without_match_or_search_text_needs_no_newer_version():
    assert _version_issues(CHOOSE.replace("- **match:** loose\n", "")) == []


def test_the_highest_version_wins_and_each_older_version_says_what_it_does():
    issues = _version_issues(CHOOSE + "\n" + LIST.replace("### 1.", "### 2."))
    assert len(issues) == 1
    assert "Add `> Requires: kinenix>=1.1.0`" in issues[0]
    assert "Kinenix 0.4.0b1 and older ignores match" in issues[0]
    assert "Kinenix 1.0.1 and older ignores on_item_error" in issues[0]
    # A requirement that excludes 0.4.0b1 but not 1.0.1 still asks, naming only what 1.0.1 would do wrong
    raised = _version_issues(CHOOSE + "\n" + LIST.replace("### 1.", "### 2."), "kinenix>=0.5.0b1")
    assert len(raised) == 1 and "Raise `> Requires: kinenix>=1.1.0`" in raised[0]
    assert "ignores match" not in raised[0]
