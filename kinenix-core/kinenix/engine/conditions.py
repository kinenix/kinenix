"""Condition expressions such as `${status} == ok`, `${note} is empty`, or `${word} in ${allowed}`.

The expression is split into operands and an operator before any variable is replaced, so a value that
contains an operator character (for example "< 5,000 km") can never split the expression in the wrong
place. Text inside ${...} and inside quotes is never read as an operator. No eval is used.
"""
import operator
import re
from typing import Any, Dict, Optional, Tuple

from .evaluator import VariableEvaluator
from .expressions import ExpressionError

# Binary operators: symbol or words -> operator name understood by FlowInterpreter._evaluate_condition
_SYMBOL_OPERATORS = (("==", "equals"), ("!=", "not_equals"), (">=", "greater_than_or_equal"),
                     ("<=", "less_than_or_equal"), (">", "greater_than"), ("<", "less_than"))
_WORD_OPERATORS = re.compile(
    r"\s(?P<op>not\s+contains|not\s+in|contains|in|starts\s+with|ends\s+with)\s", re.IGNORECASE)
_EMPTY_CHECK = re.compile(r"\s+is\s+(?P<not>not\s+)?empty\s*$", re.IGNORECASE)
_WORD_NAMES = {"not contains": "not_contains", "not in": "not_in", "contains": "contains", "in": "in",
               "starts with": "starts_with", "ends with": "ends_with"}

_ORDER_OPERATORS = {"greater_than": operator.gt, ">": operator.gt, "gt": operator.gt,
                    "greater_than_or_equal": operator.ge, ">=": operator.ge, "gte": operator.ge,
                    "less_than": operator.lt, "<": operator.lt, "lt": operator.lt,
                    "less_than_or_equal": operator.le, "<=": operator.le, "lte": operator.le}

# The whole value is one number: thousands separators and a money sign are allowed, other text is not, so
# `3 of 5` is not read as 3. Use number(...) to take a number out of text
_NUMBER_VALUE = re.compile(
    r"(?P<sign>[+-]?)\s*[฿$€£¥]?\s*(?P<inner>-?)\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)\s*[฿$€£¥]?")

# A group: an opening parenthesis at the start of the condition or right after and / or / not. A value such
# as `Acme (Thailand)` is not one
_GROUPING = re.compile(r"(?:^\s*|\s(?:and|or|not)\s+|^\s*not\s+)\(", re.IGNORECASE)


class ConditionError(ExpressionError):
    """A condition that cannot be decided: a side is not a number, or it groups with parentheses."""

    def __init__(self, reason: str, condition: str = ""):
        self.expression = condition
        self.reason = reason
        ValueError.__init__(self, f"Condition `{condition}`: {reason}" if condition else f"Condition: {reason}")


class QuotedText(str):
    """A side written in quotes: `==` and `!=` compare it as text, also when it looks like a number."""


def number_value(value: Any) -> Any:
    """The number a value stands for (100, "100.00", "1,200", "฿1200"), or None when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    match = _NUMBER_VALUE.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        return None
    number = float(match.group("num").replace(",", ""))
    return -number if "-" in (match.group("sign"), match.group("inner")) else number


def _needed_number(value: Any) -> Any:
    number = number_value(value)
    if number is not None:
        return number
    if value is None or not str(value).strip():
        raise ConditionError("a side is empty, so it cannot be compared as a number; "
                             "check it first with `is not empty`")
    raise ConditionError(f"'{str(value)[:50]}' is not a number; use number(...) to read a number from text")


def is_order_operator(name: str) -> bool:
    return name in _ORDER_OPERATORS


def compare_order(left: Any, name: str, right: Any) -> bool:
    """`>`, `>=`, `<`, `<=`: both sides must be numbers, or the condition fails and says why."""
    return _ORDER_OPERATORS[name](_needed_number(left), _needed_number(right))


def values_equal(left: Any, right: Any) -> bool:
    """Two numbers compare as numbers (100.0 == 100); a quoted side and anything else compare as text."""
    if not isinstance(left, QuotedText) and not isinstance(right, QuotedText):
        numbers = number_value(left), number_value(right)
        if None not in numbers:
            return numbers[0] == numbers[1]
    s_left = "" if left is None else str(left).strip()
    s_right = "" if right is None else str(right).strip()
    return s_left.lower() == s_right.lower()


def is_true(value: Any) -> bool:
    """A single value used as a condition: true, or the text true, 1, or yes."""
    return value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1", "yes")


def compare(left: Any, operator: str, right: Any) -> bool:
    """One comparison by operator name or symbol, with the rules of conditions; also used by where(...) in ${...}."""
    op = (operator or "equals").lower().strip().replace(" ", "_")

    if op in ["is_empty", "empty"]:
        return left is None or str(left).strip() == ""
    if op in ["is_not_empty", "not_empty"]:
        return left is not None and str(left).strip() != ""

    if is_order_operator(op):
        return compare_order(left, op, right)

    s_left = "" if left is None else str(left).strip()
    s_right = "" if right is None else str(right).strip()

    if op in ["equals", "==", "eq"]:
        return values_equal(left, right)
    if op in ["not_equals", "!=", "neq"]:
        return not values_equal(left, right)
    # `left in right` means left is part of right; a list on the other side is checked item by item
    if op in ["in", "not_in"]:
        if isinstance(right, (list, tuple, set)):
            found = any(s_left.lower() == ("" if item is None else str(item).strip()).lower() for item in right)
        else:
            found = s_left.lower() in s_right.lower()
        return found if op == "in" else not found
    if op in ["contains", "not_contains"]:
        if isinstance(left, (list, tuple, set)):
            found = any(s_right.lower() == ("" if item is None else str(item).strip()).lower() for item in left)
        else:
            found = s_right.lower() in s_left.lower()
        return found if op == "contains" else not found
    if op in ["starts_with", "startswith"]:
        return s_left.lower().startswith(s_right.lower())
    if op in ["ends_with", "endswith"]:
        return s_left.lower().endswith(s_right.lower())

    return s_left == s_right


def grouping_problem(expression: Any) -> Optional[str]:
    """What is wrong with a condition that groups with parentheses, which conditions do not support."""
    if not isinstance(expression, str):
        return None
    text = expression.strip().strip("`")
    if not _GROUPING.search(_mask(text)):
        return None
    return ("parentheses cannot group a condition. `and` binds tighter than `or`, so write out each case, as in "
            "`${a} == 1 and ${c} == 3 or ${b} == 2 and ${c} == 3`, or use logic.if steps. "
            "Quote a value that starts with a parenthesis")


def _mask(expression: str) -> str:
    """Hides ${...} placeholders and quoted text behind a filler of the same length."""
    out = list(expression)
    i = 0
    while i < len(expression):
        if expression.startswith("${", i):
            end = expression.find("}", i)
            end = len(expression) - 1 if end == -1 else end
            out[i:end + 1] = "\0" * (end + 1 - i)
            i = end + 1
        elif expression[i] in "'\"" and (i == 0 or not expression[i - 1].isalnum()):
            # A quote opens only at the start of a word, so the apostrophe of don't is plain text
            end = expression.find(expression[i], i + 1)
            if end == -1:
                i += 1
                continue
            out[i:end + 1] = "\0" * (end + 1 - i)
            i = end + 1
        else:
            i += 1
    return "".join(out)


def split_condition(expression: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Splits `left OP right` into (left, operator name, right), using the leftmost operator outside
    placeholders and quotes; `left is empty` gives (left, "is_empty", None). None when there is no operator.
    """
    masked = _mask(expression)

    best = None  # (start, end, name)
    for symbol, name in _SYMBOL_OPERATORS:
        pos = masked.find(symbol)
        if pos != -1 and (best is None or pos < best[0] or (pos == best[0] and len(symbol) > best[1] - best[0])):
            best = (pos, pos + len(symbol), name)
    word = _WORD_OPERATORS.search(masked)
    if word and (best is None or word.start("op") < best[0]):
        best = (word.start("op"), word.end("op"), _WORD_NAMES[" ".join(word.group("op").lower().split())])

    empty = _EMPTY_CHECK.search(masked)
    if empty and (best is None or best[0] >= empty.start()):
        return expression[:empty.start()], "is_not_empty" if empty.group("not") else "is_empty", None
    if best is None:
        return None
    return expression[:best[0]], best[2], expression[best[1]:]


def _operand(raw: str, variables: Dict[str, Any]) -> Any:
    """A side of a condition: quoted text stays text (with ${...} replaced inside), anything else is evaluated."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"`":
        inner = str(VariableEvaluator.evaluate_value(text[1:-1], variables))
        return inner if text[0] == "`" else QuotedText(inner)
    return VariableEvaluator.evaluate_value(text, variables)


def resolve_condition(expression: Any, variables: Dict[str, Any]) -> Tuple[Any, Optional[str], Any]:
    """
    Turns a condition into (left value, operator name, right value). The operator is None when the
    expression has none; left is then the evaluated expression, read as true or false by the caller.
    """
    if isinstance(expression, bool):
        return expression, None, None
    text = str(expression).strip()
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    parts = split_condition(text)
    if parts is None:
        return VariableEvaluator.evaluate_value(text, variables), None, None
    left, op, right = parts
    return _operand(left, variables), op, (None if right is None else _operand(right, variables))


# ---------------------------------------------------------------------------------------------------
# and / or / not (docs/design/expressions.md, section 6)
# ---------------------------------------------------------------------------------------------------

_NOT_PREFIX = re.compile(r"^\s*not\s+", re.IGNORECASE)
_PLACEHOLDER_ONLY = re.compile(r"^\s*`?\$\{[^}]+\}`?\s*$")


def _split_top(text: str, word: str) -> list:
    """Splits at ` word ` outside ${...} and quotes (any case)."""
    masked = _mask(text)
    pattern = re.compile(rf"\s+{word}\s+", re.IGNORECASE)
    parts, start = [], 0
    for match in pattern.finditer(masked):
        parts.append(text[start:match.start()])
        start = match.end()
    parts.append(text[start:])
    return parts


def _is_comparison(text: str) -> bool:
    """A part that can stand alone as a condition: it has an operator, or is a single ${...}."""
    inner = _NOT_PREFIX.sub("", text, count=1)
    return bool(inner.strip()) and (split_condition(inner.strip()) is not None or bool(_PLACEHOLDER_ONLY.match(inner)))


def _is_conjunction(text: str) -> bool:
    parts = _split_top(text, "and")
    return all(_is_comparison(p) for p in parts)


def parse_boolean(expression: str) -> Any:
    """
    The structure of a condition: ("or", [...]), ("and", [...]), ("not", text), or ("is", text).
    A condition is split at and / or only when every part is a condition by itself, so a value such as
    `Johnson and Johnson` is never split. `and` binds tighter than `or`.
    """
    text = expression.strip()
    ors = _split_top(text, "or")
    if len(ors) > 1 and all(_is_conjunction(p) for p in ors):
        return ("or", [_parse_conjunction(p) for p in ors])
    return _parse_conjunction(text)


def _parse_conjunction(text: str) -> Any:
    ands = _split_top(text, "and")
    if len(ands) > 1 and all(_is_comparison(p) for p in ands):
        return ("and", [_parse_atom(p) for p in ands])
    return _parse_atom(text)


def _parse_atom(text: str) -> Any:
    stripped = text.strip()
    negated = _NOT_PREFIX.match(stripped)
    if negated and _is_comparison(stripped[negated.end():]):
        return ("not", stripped[negated.end():].strip())
    return ("is", stripped)
