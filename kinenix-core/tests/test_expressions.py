"""0.3.0b1 (#56): expressions in ${...} and and / or / not in conditions (docs/design/expressions.md)."""
import ast
import random
import time
from pathlib import Path

import pytest

from kinenix.engine import expressions
from kinenix.engine.conditions import parse_boolean
from kinenix.engine.evaluator import VariableEvaluator
from kinenix.engine.expressions import ExpressionError
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow
from kinenix.engine.validation import validate_flow

VARS = {
    "rows": [{"id": "R1", "price": "15,434.75 บาท/ปี", "First Name": "Ann"}, {"id": "R2", "price": ""}],
    "ids": ["R1", "R2", "R3"],
    "count": "5",
    "due": "25-10-2019",
    "row": {"First Name": "Ann", "Role in Company": "Admin", "Unit Price (THB)": "1,200", "Order-ID": "7"},
    "empty": None,
}


def value(text):
    return VariableEvaluator.evaluate_value(text, VARS)


@pytest.mark.parametrize("text, expected", [
    ("${len(rows)}", 2),
    ("${len(ids)}", 3),
    ("${len(empty)}", 0),
    ("${len(due)}", 10),
    ("${join(ids, ', ')}", "R1, R2, R3"),
    ("${join(ids)}", "R1, R2, R3"),
    ("${join(empty, '-')}", ""),
    ("${number(rows[0].price)}", 15434.75),
    ("${number('(1,200)')}", -1200),
    ("${number('INV-100')}", 100),
    ("${number('-5 units')}", -5),
    ("${number(rows[1].price)}", None),
    ("${trim('  a b  ')}", "a b"),
    ("${upper(trim(rows[0].id))}", "R1"),
    ("${lower('ABC')}", "abc"),
    ("${replace(rows[0].price, ' บาท/ปี', '')}", "15,434.75"),
    ("${default(rows[1].price, 'n/a')}", "n/a"),
    ("${default(rows[0].id, 'n/a')}", "R1"),
    ("${round(10 / 3, 2)}", 3.33),
    ("${round(2.5)}", 3),
    ("${round(-2.5)}", -3),
    ("${round(3.5)}", 4),
    ("${round(2.675, 2)}", 2.68),
    ("${round(1.005, 2)}", 1.01),
    ("${round(1234.5678, 1)}", 1234.6),
    ("${round(1250, -2)}", 1300),
    ("${round(7)}", 7),
    ("${round(7, 2)}", 7),
    ("${round(1.5, 2000)}", 1.5),
    ("${number('.5')}", 0.5),
    ("${number('-.5')}", -0.5),
    ("${number('.5 kg')}", 0.5),
    ("${number('v.5')}", 5),
    ("${number('1.2.3')}", 1.2),
    ("${number('12 345')}", 12),
    ("${number('1e5')}", 1),
    ("${part(due, '-', 1)}", "10"),
    ("${part(due, '-', -1)}", "2019"),
    ("${part(due, '-', 9)}", ""),
    ("${substring(due, 3, 2)}", "10"),
    ("${substring(due, 6)}", "2019"),
    ("${substring(due, 50, 2)}", ""),
    ("${count + 1}", 6),
    ("${count * 2 - 1}", 9),
    ("${10 / 4}", 2.5),
    ("${10 / 2}", 5),
    ("${7 % 3}", 1),
    ("${-number(count)}", -5),
    ("${(1 + 2) * 3}", 9),
    ("${number(rows[0].price) * 12}", 185217),
    ("${rows[0].id}", "R1"),
    ("${rows[-1].id}", "R2"),
    ("${rows[9].id}", None),
    ("${ids[0]}", "R1"),
    ("${row['Unit Price (THB)']}", "1,200"),
    ("${number(part(due, '-', 1)) + 1}", 11),
])
def test_functions_operators_and_indexing(text, expected):
    assert value(text) == expected


def test_expressions_inside_text():
    assert value("${len(ids)} requests: ${join(ids, ', ')}") == "3 requests: R1, R2, R3"


@pytest.mark.parametrize("text, expected", [
    ("${row.First Name}", "Ann"),
    ("${row.Role in Company}", "Admin"),            # the word "in" in a key
    ("${row.Unit Price (THB)}", "1,200"),           # parentheses in a key
    ("${row.Order-ID}", "7"),                       # a minus sign in a key
    ("${rows}", VARS["rows"]),
    ("${row.Missing Column}", None),                # a missing key stays empty
    ("${row.Missing (THB)}", None),
    ("${nothing.at.all}", None),
    ("${__flow_dir__}", None),
    ("${row.Terms and Conditions}", None),
])
def test_lookups_that_work_today_are_unchanged(text, expected):
    assert value(text) == expected


@pytest.mark.parametrize("text, reason", [
    ("${row.__class__}", None),                     # a lookup: empty, never Python internals
    ("${len(row.__class__)}", "names starting with _"),
    ("${__import__('os')}", "unknown function '__import__'"),
    ("${rows[0].upper()}", "not methods"),
    ("${lambda: 1}", None),                         # read as a missing key; nothing runs
    ("${[x for x in rows]}", "comprehensions are not allowed"),
    ("${2 ** 64}", "only + - * / %"),
    ("${f'{count}'}", None),                        # contains }, so ${...} ends early; nothing runs
    ("${len(rows, 2)}", "len takes 1 value, got 2"),
    ("${len(lambda: 1)}", "lambdas are not allowed"),
    ("${len(count in rows)}", "for `in` use contains"),
    ("${join(sep=', ')}", "without names"),
    ("${rows[0:1]}", "slices"),
    ("${len(${ids})}", "without ${...}"),
    ("${'a' * 3}", "is not a number"),
    ("${1 / 0}", "division by zero"),
    ("${" + "len(" * 30 + "1" + ")" * 30 + "}", "nested more than 20"),
    ("${len('" + "x" * 600 + "')}", "longer than 500"),
])
def test_unsafe_or_wrong_expressions_are_refused(text, reason):
    if reason is None:
        try:
            assert value(text) in (None, "") or isinstance(value(text), str)
        except ExpressionError:
            pass
        return
    with pytest.raises(ExpressionError, match=reason.replace("(", r"\(").replace("[", r"\[").replace("*", r"\*")
                       .replace("+", r"\+").replace("$", r"\$").replace("{", r"\{")):
        value(text)


def test_no_code_execution_in_the_evaluator():
    """The expression modules never call eval, exec, compile, or __import__, and never use getattr on values."""
    engine = Path(expressions.__file__).parent
    for name in ("expressions.py", "evaluator.py", "conditions.py"):
        tree = ast.parse((engine / name).read_text(encoding="utf-8"))
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert not called & {"eval", "exec", "compile", "__import__", "getattr"}, name


GRAMMAR = ["len(", "join(", "number(", "trim(", "part(", "substring(", "round(", "default(", "replace(",
           "sort_by(", "where(", "sum(", "ifelse(", "text(", "contains(", "<", ">=", "!=", "or", "'-price'",
           "rows", "rows[0]", "ids", "count", "due", "row", ".id", ".price", "[", "]", "(", ")", ",", " ",
           "+", "-", "*", "/", "%", "'x'", '"-"', "1", "0", "-1", "3.5", "__class__", ".", "env", "lambda",
           "**", "==", "and", "not", "if", "else", ":", "{", "\\", "\0", "ราคา", chr(0x1F600), "\n"]  # chr(): no emoji in the source


def test_fuzz_never_crashes_or_hangs():
    """Random and malformed expressions end quickly with a value or an ExpressionError, never another exception."""
    rng = random.Random(56)
    cases = []
    for _ in range(3000):
        cases.append("".join(rng.choice(GRAMMAR) for _ in range(rng.randint(1, 12))))
    for _ in range(1000):
        cases.append("".join(chr(rng.randint(1, 0x2FFF)) for _ in range(rng.randint(1, 40))))
    for text in cases:
        started = time.monotonic()
        try:
            VariableEvaluator.evaluate_value("${" + text + "}", VARS)
        except ExpressionError:
            pass
        assert time.monotonic() - started < 1.0, repr(text)


@pytest.mark.parametrize("condition, expected", [
    ("${row.First Name} == ann and ${count} > 3", True),
    ("${row.First Name} == ann and ${count} > 9", False),
    ("${count} > 9 or ${due} contains -10-", True),
    ("${count} > 9 or ${due} contains -11- or ${row.Role in Company} == admin", True),
    ("not ${due} contains -10-", False),
    ("not ${empty} is empty", False),
    ("${len(ids)} == 3 and ${join(ids, '-')} == R1-R2-R3", True),
    ("${number(part(due, '-', 1))} >= 10", True),
    ("${row.Role in Company} == Admin", True),
])
def test_conditions(condition, expected):
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=None))
    assert interpreter._condition_holds(condition, VARS) is expected


def test_a_value_with_and_is_not_split():
    assert parse_boolean("${company} == Johnson and Johnson") == ("is", "${company} == Johnson and Johnson")
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=None))
    assert interpreter._condition_holds("${company} == Johnson and Johnson", {"company": "Johnson and Johnson"})
    assert interpreter._condition_holds("${c} == 'black or white'", {"c": "black or white"})


FLOW = """# Expressions

## Variables
- `ids`: ["R1", "R2", "R3"]
- `rows`: [{"id": "R1", "premium": "1,200.50 บาท"}, {"id": "R2", "premium": "800 บาท"}]

## Steps

### 1. Count (`logic.set_variable`)
- **name:** summary
- **value:** ${len(ids)} requests: ${join(ids, ', ')}

### 2. Total (`logic.set_variable`)
- **name:** total
- **value:** ${number(rows[0].premium) + number(rows[1].premium)}

### 3. Flag (`logic.set_variable`)
- **condition:** `${len(ids)} == 3 and ${total} > 2000`
- **name:** flag
- **value:** big
"""


def test_expressions_in_a_flow():
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(markdown_to_flow(FLOW))
    assert not context.has_error
    assert context.get_variable("summary") == "3 requests: R1, R2, R3"
    assert context.get_variable("total") == 2000.5
    assert context.get_variable("flag") == "big"


def test_a_wrong_expression_fails_the_step_with_its_reason():
    flow = markdown_to_flow(FLOW.replace("${len(ids)} requests", "${lenn(ids)} requests"))
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(flow)
    assert context.has_error and "unknown function 'lenn'" in context.failure_details.error_message


def test_validate_reports_expression_problems_with_their_line():
    flow = markdown_to_flow(FLOW.replace("${len(ids)} requests", "${lenn(ids)} requests")
                            .replace("${len(ids)} == 3 and", "${len(ids, 2)} == 3 and"))
    problems = [p for p in validate_flow(flow) if p.startswith("Step ")]
    assert any("line 9" in p and "unknown function 'lenn'" in p for p in problems)
    assert any("len takes 1 value, got 2" in p for p in problems)
    assert not [p for p in validate_flow(markdown_to_flow(FLOW)) if p.startswith("Step ")]


def test_validate_asks_for_the_version_that_understands_expressions():
    """Kinenix 0.2.0b4 turns ${len(rows)} into empty text, so a flow that uses expressions must exclude it."""
    def version_issues(text):
        return [p for p in validate_flow(markdown_to_flow(text)) if "older workers" in p]

    missing = version_issues(FLOW)
    assert len(missing) == 1 and "expressions in ${...}" in missing[0] and "and / or / not" in missing[0]
    assert "Add `> Requires: kinenix>=0.3.0b1`" in missing[0]
    too_low = version_issues(FLOW.replace("# Expressions\n", "# Expressions\n> Requires: kinenix>=0.2.0b4\n"))
    assert len(too_low) == 1 and "Raise `> Requires: kinenix>=0.3.0b1`" in too_low[0]
    assert version_issues(FLOW.replace("# Expressions\n", "# Expressions\n> Requires: kinenix>=0.3.0b1\n")) == []
    plain = "# Plain\n\n## Steps\n\n### 1. Set (`logic.set_variable`)\n- **name:** a\n- **value:** ${row.First Name}\n"
    assert version_issues(plain) == []
