"""Sorting, filtering, totals, and comparisons in ${...} (docs/design/list-functions.md)."""
import pytest

from kinenix.engine.conditions import ConditionError
from kinenix.engine.evaluator import VariableEvaluator
from kinenix.engine.expressions import MAX_ITEMS, ExpressionError
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow

BOOKS = [
    {"title": "A", "price": "£51.77", "category": "Travel", "availability": "In stock (5 available)"},
    {"title": "B", "price": "£12.00", "category": "Poetry", "availability": "In stock"},
    {"title": "C", "price": "£20", "category": "Travel", "availability": "Out of stock"},
    {"title": "D", "price": "", "category": "Poetry", "availability": "In stock"},
    {"title": "E", "price": "1,200", "category": "art", "availability": "In stock"},
]
VARS = {"books": BOOKS, "limit": 25, "code": "0012", "other": "12", "x": 100, "flag": "true",
        "row": {"Terms": "yes"}, "nums": [3, "1", 2.5, None, ""], "empty_list": [],
        "picked": ["A", "E"], "mixed": ["a", "A", 1, "1.0", 2]}


def value(text):
    return VariableEvaluator.evaluate_value(text, VARS)


def titles(text):
    return [book["title"] for book in value(text)]


# sort_by ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("${sort_by(books, 'price')}", ["B", "C", "A", "E", "D"]),        # numbers as numbers, empty last
    ("${sort_by(books, '-price')}", ["E", "A", "C", "B", "D"]),       # high to low, empty still last
    ("${sort_by(books, 'category', 'price')}", ["E", "B", "D", "C", "A"]),  # text without case: art, Poetry, Travel
    ("${sort_by(books, 'category', '-price')}", ["E", "B", "D", "A", "C"]),
])
def test_sort_by(text, expected):
    assert titles(text) == expected


def test_sort_by_keeps_the_order_of_equal_rows_and_leaves_the_list_alone():
    before = [book["title"] for book in BOOKS]
    assert titles("${sort_by(books, 'availability')}") == ["B", "D", "E", "A", "C"]
    assert [book["title"] for book in BOOKS] == before


def test_sort_by_without_a_key_sorts_the_values():
    assert value("${sort_by(nums)}") == ["1", 2.5, 3, None, ""]
    assert value("${sort_by(empty_list, 'price')}") == []


# where, column, unique, first, last -------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("${where(books, 'price', '<', limit)}", ["B", "C"]),            # empty prices are left out
    ("${where(books, 'price', '>=', 20)}", ["A", "C", "E"]),
    ("${where(books, 'category', '==', 'travel')}", ["A", "C"]),     # without case, as in conditions
    ("${where(books, 'category', '!=', 'Travel')}", ["B", "D", "E"]),
    ("${where(books, 'availability', 'contains', 'in stock')}", ["A", "B", "D", "E"]),
    ("${where(books, 'availability', 'not contains', 'In stock')}", ["C"]),
    ("${where(books, 'title', 'in', picked)}", ["A", "E"]),
    ("${where(books, 'title', 'starts with', 'a')}", ["A"]),
    ("${where(books, 'price', 'is empty')}", ["D"]),
    ("${where(books, 'price', 'is  not  empty')}", ["A", "B", "C", "E"]),
    ("${where(where(books, 'price', '<', limit), 'availability', 'contains', 'In stock')}", ["B"]),
])
def test_where(text, expected):
    assert titles(text) == expected


def test_count_is_len_of_where():
    assert value("${len(where(books, 'category', '==', 'Poetry'))}") == 2


@pytest.mark.parametrize("text, expected", [
    ("${column(books, 'title')}", ["A", "B", "C", "D", "E"]),
    ("${join(column(sort_by(books, 'price'), 'title'), ', ')}", "B, C, A, E, D"),
    ("${column(unique(books, 'category'), 'category')}", ["Travel", "Poetry", "art"]),
    ("${unique(mixed)}", ["a", 1, 2]),
    ("${first(books).title}", "A"),
    ("${last(books).title}", "E"),
    ("${first(empty_list)}", None),
])
def test_column_unique_first_last(text, expected):
    assert value(text) == expected


# sum, min, max, average ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("${sum(books, 'price')}", 1283.77),                # 51.77 + 12 + 20 + 1200; the empty price does not count
    ("${min(books, 'price')}", 12),
    ("${max(books, 'price')}", 1200),
    ("${average(where(books, 'price', '<', 100), 'price')}", 27.9233333333),
    ("${sum(nums)}", 6.5),
    ("${sum(empty_list)}", 0),
    ("${max(empty_list)}", None),
])
def test_totals(text, expected):
    assert value(text) == expected


# comparisons, and / or / not, ifelse, contains, text ----------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("${x > 50}", True),
    ("${x == 100.00}", True),                 # numbers compare as numbers
    ("${x == '100.0'}", False),               # quoted text compares as text: '100.0' is not 100 (#160)
    ("${x == 100.0}", True),
    ("${code == other}", True),               # two numbers: 0012 and 12
    ("${code == '12'}", False),               # quoted: text
    ("${text(code) == text(other)}", False),  # text(...) keeps codes apart
    ("${text(code) == '0012'}", True),
    ("${1 < x <= 100}", True),
    ("${x > 50 and flag}", True),
    ("${x < 50 or not flag}", False),
    ("${not flag}", False),
    ("${ifelse(x > 50, 'big', 'small')}", "big"),
    ("${ifelse(x < 50, books[99].title, 'small')}", "small"),  # only the chosen branch is evaluated
    ("${contains('In stock (5)', 'in stock')}", True),
    ("${contains(column(books, 'title'), 'c')}", True),
    ("${contains(empty, 'x')}", False),
])
def test_comparisons_and_true_false_values(text, expected):
    assert value(text) == expected


def test_a_comparison_in_text_reads_true_or_false():
    assert VariableEvaluator.evaluate_value("Cheap: ${x < limit}", VARS) == "Cheap: false"


def test_text_from_text_is_stored_as_plain_text():
    assert type(value("${text(code)}")) is str


@pytest.mark.parametrize("text, reason", [
    ("${where(books, 'prcie', '<', 3)}", "no row has the key 'prcie'; keys: availability, category, price, title"),
    ("${where(books, 'price', 'like', 3)}", "unknown operator 'like'"),
    ("${where(books, 'price', '>', 'cheap')}", "'cheap' is not a number"),
    ("${where(books, 'title', '>', 3)}", "row 0 (title = 'A')"),
    ("${sort_by(x, 'price')}", "sort_by needs a list"),
    ("${sum(column(books, 'title'))}", "'A' is not a number"),
    ("${column(nums, 'id')}", "the items are not rows with keys"),
    ("${x < 'abc'}", "'abc' is not a number"),
    ("${x < empty}", "a side is empty"),
    ("${len(x in books)}", "for `in` use contains"),
])
def test_wrong_use_says_why(text, reason):
    with pytest.raises(ExpressionError) as error:
        value(text)
    assert reason in str(error.value)


def test_a_list_longer_than_the_limit_is_refused():
    with pytest.raises(ExpressionError, match="at most"):
        VariableEvaluator.evaluate_value("${len(sort_by(big))}", {"big": list(range(MAX_ITEMS + 1))})


def test_a_missing_key_with_and_in_its_name_is_still_empty():
    """`${row.Terms and Conditions}` was a missing key before comparisons were allowed, and still is."""
    assert value("${row.Terms and Conditions}") is None
    assert value("${row.Missing or Other}") is None
    assert value("${flag and row.Terms}") is True


# the same answer as a step's condition ------------------------------------------------------------------

@pytest.mark.parametrize("left, op, right", [
    ("100", "==", "100.00"), ("1,200", "==", "1200"), ("0012", "==", "12"), ("Travel", "==", "travel"),
    ("5", "<", "12"), ("12.5", ">=", "12.50"), ("abc", "!=", "abd"),
])
def test_a_comparison_in_an_expression_agrees_with_a_condition(left, op, right):
    variables = {"a": left, "b": right}
    condition = FlowInterpreter(logger=ExecutionLogger(log_dir=None))._condition_holds(f"${{a}} {op} ${{b}}", variables)
    assert VariableEvaluator.evaluate_value(f"${{a {op} b}}", variables) is condition


def test_a_comparison_that_cannot_be_decided_fails_the_step_with_exit_code_4():
    from kinenix import exit_codes
    flow = markdown_to_flow("# C\n\n## Steps\n\n### 1. Check (`logic.set_variable`)\n"
                            "- **name:** `ok`\n- **value:** `${missing < 3}`\n")
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(flow)
    assert context.has_error and exit_codes.for_run(context) == exit_codes.INVALID_FLOW
    assert "a side is empty" in context.failure_details.error_message


def test_a_key_with_in_in_its_name_is_still_a_lookup():
    """`in` is not a comparison inside ${...}, so `row.Role in Company` stays a key, as before."""
    assert VariableEvaluator.evaluate_value("${row.Role in Company}", {"row": {"Role in Company": "Admin"}}) == "Admin"
    assert VariableEvaluator.evaluate_value("${row.Role in Team}", {"row": {}}) is None


def test_condition_error_is_an_expression_error():
    assert issubclass(ConditionError, ExpressionError)


# kinenix validate ---------------------------------------------------------------------------------------

def _issues(requires, value):
    from kinenix.engine.validation import validate_flow
    head = f"# C\n\n> Requires: kinenix>={requires}\n\n" if requires else "# C\n\n"
    return validate_flow(markdown_to_flow(head + "## Steps\n\n### 1. Pick (`logic.set_variable`)\n"
                                          f"- **name:** pick\n- **value:** `{value}`\n"))


@pytest.mark.parametrize("value", ["${sort_by(rows, 'price')}", "${a < b}", "${a and b}", "${not done}",
                                   "${len(where(rows, 'p', '>', 1))}", "${ifelse(x, 1, 2)}"])
def test_validate_asks_for_requires_1_1_0(value):
    assert any("Requires: kinenix>=1.1.0" in issue for issue in _issues(None, value))
    assert any("Requires: kinenix>=1.1.0" in issue for issue in _issues("1.0.1", value))
    assert not any("Requires" in issue for issue in _issues("1.1.0", value))


def test_validate_does_not_ask_for_older_expressions():
    assert not any("1.1.0" in issue for issue in _issues("0.3.0b1", "${len(rows) + 1}"))
