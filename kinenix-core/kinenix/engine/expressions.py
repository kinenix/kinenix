"""Expressions inside ${...}: functions, arithmetic, indexing, and comparisons, without eval
(docs/design/expressions.md, docs/design/list-functions.md).

The text is parsed with ast.parse, which only builds a syntax tree and runs nothing. The tree is then
checked against a short list of allowed node types and functions, and walked by the evaluator below.
Nothing here calls eval, exec, or compile, and only dictionary keys are read: attributes of Python
objects and names starting with "_" are refused.
"""
import ast
import json
import math
import os
import re
import warnings
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_LENGTH = 500
MAX_DEPTH = 20
# Most items a list function takes, so one call cannot hold up a worker (docs/design/list-functions.md)
MAX_ITEMS = 100_000

# Text that cannot be read, or is refused, is an error only when it clearly means an expression: a function
# call, brackets, quotes, or an operator other than "-". Otherwise it is a key name that is missing, such as
# "row.Unit Price (THB)", "row.Terms and Conditions", or "row.Order-ID", and gives empty as before.
_LOOKS_LIKE_EXPRESSION = re.compile(r"\w\(|\[|['\"]|[+*/%<>=!]")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")
# The first number in a text: optional minus or opening parenthesis, digits with thousands separators, decimals
# A minus sign or "(" counts only when no letter or digit is right before it: "INV-100" is 100, "(1,200)" is -1200
# A leading decimal point counts when it starts a word: ".5" is 0.5, "v.5" is 5
_NUMBER_IN_TEXT = re.compile(r"(?:(?<!\w)(?P<neg>[-(]))?\s*(?P<num>\d[\d,]*(?:\.\d+)?|(?<![\w.])\.\d+)")


class ExpressionError(ValueError):
    """An expression that cannot be read or evaluated; the message names the expression and the reason."""

    def __init__(self, expression: str, reason: str):
        self.expression = expression
        self.reason = reason
        super().__init__(f"${{{expression}}}: {reason}")


class ExpressionSyntaxError(ExpressionError):
    """The text cannot be read as an expression at all (as opposed to an expression that is refused)."""


class _Environment:
    """`env` inside an expression: `env.NAME` reads an environment variable, as `${env.NAME}` does."""

    def get(self, name: str) -> str:
        return os.getenv(name, "")


# ---------------------------------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------------------------------

def _text(value: Any) -> str:
    """A value as it reads in text: 1200, true, and JSON for lists and objects, not Python's 1200.0, True, or [{'a': 1}]."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(_whole(value))
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def to_text(value: Any) -> str:
    """The text of a value placed inside longer text, such as `Total: ${x}`."""
    return _text(value)


def _whole(value: Any) -> Any:
    """A float that is a whole number is shown without .0."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return int(value)
    return value


def _number(value: Any, what: str) -> Any:
    """A number for arithmetic: numbers, and text that is a plain number such as "12" or "3.5"."""
    if isinstance(value, bool):
        raise ValueError(f"{what} is true or false, not a number")
    if isinstance(value, (int, float)):
        return value
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{what} is empty")
    if isinstance(value, str) and _PLAIN_NUMBER.match(value.strip()):
        text = value.strip()
        return float(text) if "." in text else int(text)
    raise ValueError(f"{what} '{_text(value)[:50]}' is not a number; use number(...) to read a number from text")


def _whole_number(value: Any, what: str) -> int:
    number = _number(value, what)
    if isinstance(number, float) and not number.is_integer():
        raise ValueError(f"{what} must be a whole number, not {number}")
    return int(number)


# ---------------------------------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------------------------------

def _len(x: Any) -> int:
    if x is None:
        return 0
    if isinstance(x, (str, list, tuple, dict)):
        return len(x)
    return len(_text(x))


def _join(items: Any, sep: Any = ", ") -> str:
    if items is None:
        return ""
    if isinstance(items, str):
        return items
    if isinstance(items, (list, tuple)):
        return _text(sep).join(_text(item) for item in items)
    raise ValueError("join needs a list")


def _parse_number(x: Any) -> Any:
    if x is None or (isinstance(x, str) and not x.strip()):
        return None
    if isinstance(x, bool):
        raise ValueError("number needs text or a number, not true or false")
    if isinstance(x, (int, float)):
        return x
    text = _text(x)
    match = _NUMBER_IN_TEXT.search(text)
    if not match:
        raise ValueError(f"'{text[:50]}' contains no number")
    digits = match.group("num").replace(",", "")
    value = float(digits) if "." in digits else int(digits)
    return -value if match.group("neg") else value


def parse_number(x: Any) -> Any:
    """The first number in a text, as number() reads it: "15,434.75 บาท/ปี" is 15434.75; empty gives None."""
    return _parse_number(x)


def _trim(x: Any) -> str:
    return _text(x).strip()


def _lower(x: Any) -> str:
    return _text(x).lower()


def _upper(x: Any) -> str:
    return _text(x).upper()


def _replace(x: Any, old: Any, new: Any) -> str:
    old_text = _text(old)
    if not old_text:
        raise ValueError("replace needs a non-empty text to replace")
    return _text(x).replace(old_text, _text(new))


def _default(x: Any, fallback: Any) -> Any:
    return fallback if x is None or x == "" else x


def _round(x: Any, digits: Any = 0) -> Any:
    if x is None or x == "":
        return None
    places = _whole_number(digits, "the number of digits")
    value = _number(x, "the value")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("the value is not a finite number")
    if isinstance(value, int) and places >= 0:
        return value
    # As in Excel: halves go away from zero, on the number as written, so 2.675 gives 2.68 and 2.5 gives 3
    try:
        result = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP,
                                              context=Context(prec=1000))
    except InvalidOperation:
        return value  # More digits than the number has
    return int(result) if places <= 0 else float(result)


def _part(x: Any, sep: Any, n: Any) -> str:
    separator = _text(sep)
    if not separator:
        raise ValueError("part needs a non-empty separator")
    pieces = _text(x).split(separator)
    index = _whole_number(n, "the piece number")
    if -len(pieces) <= index < len(pieces):
        return pieces[index]
    return ""


def _substring(x: Any, start: Any, length: Any = None) -> str:
    text = _text(x)
    first = _whole_number(start, "the start")
    if first < 0:
        raise ValueError("the start is counted from 0 and cannot be negative")
    if length is None:
        return text[first:]
    count = _whole_number(length, "the length")
    if count < 0:
        raise ValueError("the length cannot be negative")
    return text[first:first + count]


# ---------------------------------------------------------------------------------------------------
# Lists, comparisons, and true/false values (docs/design/list-functions.md)
# ---------------------------------------------------------------------------------------------------

def _rules():
    from . import conditions  # conditions imports this module, so it is imported here
    return conditions


def _items(value: Any, name: str) -> List[Any]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} needs a list, not '{_text(value)[:50]}'")
    if len(value) > MAX_ITEMS:
        raise ValueError(f"{name} takes at most {MAX_ITEMS} items, got {len(value)}")
    return list(value)


def _column(rows: List[Any], key: Any, name: str) -> List[Any]:
    """The values of `key` in each row; a key that no row has is an error, so a misspelled key is noticed."""
    if rows and not any(isinstance(row, dict) and key in row for row in rows):
        keys = sorted({str(k) for row in rows if isinstance(row, dict) for k in row})
        if not keys:
            raise ValueError(f"{name}: the items are not rows with keys, so '{key}' cannot be read")
        raise ValueError(f"{name}: no row has the key '{key}'; keys: {', '.join(keys)[:300]}")
    return [row.get(key) if isinstance(row, dict) else None for row in rows]


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _sort_rank(value: Any) -> Tuple[int, Any]:
    number = _rules().number_value(value)
    return (0, number) if number is not None else (1, _text(value).strip().lower())


def _sort_by(items: Any, *keys: Any) -> List[Any]:
    rows = _items(items, "sort_by")
    # Sorted by the last key first; Python's sort keeps the order of equal items, so earlier keys win
    for raw in reversed(keys or (None,)):
        key, descending = raw, False
        if isinstance(raw, str) and raw.startswith("-"):
            key, descending = raw[1:], True
        values = _column(rows, key, "sort_by") if key is not None else rows
        pairs = list(zip(values, rows))
        filled = [pair for pair in pairs if not _empty(pair[0])]
        empty = [pair for pair in pairs if _empty(pair[0])]  # always last, in either direction
        filled.sort(key=lambda pair: _sort_rank(pair[0]), reverse=descending)
        rows = [row for _, row in filled + empty]
    return rows


_WHERE_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "contains", "not contains", "in", "not in",
                    "starts with", "ends with", "is empty", "is not empty"}


def _where(items: Any, key: Any, operator: Any, value: Any = None) -> List[Any]:
    rows = _items(items, "where")
    op = " ".join(str(operator).split()).lower()
    if op not in _WHERE_OPERATORS:
        raise ValueError(f"where: unknown operator '{operator}'; use one of {', '.join(sorted(_WHERE_OPERATORS))}")
    values = _column(rows, key, "where")
    compare = _rules().compare
    kept = []
    ordered = op in ("<", "<=", ">", ">=")
    if ordered and _rules().number_value(value) is None:
        raise ValueError(f"where: '{_text(value)[:50]}' is not a number, so '{op}' cannot compare with it")
    for position, (cell, row) in enumerate(zip(values, rows)):
        if ordered and _empty(cell):
            continue  # an empty cell is neither more nor less than a number: the row is left out
        try:
            if compare(cell, op, value):
                kept.append(row)
        except ValueError as e:  # ConditionError: a value that cannot be compared as a number
            reason = e.reason if isinstance(e, _rules().ConditionError) else str(e)
            raise ValueError(f"where: row {position} ({key} = '{_text(cell)[:40]}'): {reason}") from None
    return kept


def _numbers(items: Any, key: Any, name: str) -> List[Any]:
    rows = _items(items, name)
    values = _column(rows, key, name) if key is not None else rows
    numbers = []
    for value in values:
        if _empty(value):
            continue  # an empty cell does not count
        number = _rules().number_value(value)
        if number is None:
            raise ValueError(f"{name}: '{_text(value)[:50]}' is not a number; use number(...) to read a number from text")
        numbers.append(number)
    return numbers


def _total(numbers: List[Any]) -> Any:
    # Rounded to 10 decimals, so prices such as 51.77 + 12 + 20 add up to 83.77, not 83.77000000000001
    return _whole(round(math.fsum(numbers), 10))


def _sum(items: Any, key: Any = None) -> Any:
    return _total(_numbers(items, key, "sum"))


def _min(items: Any, key: Any = None) -> Any:
    numbers = _numbers(items, key, "min")
    return _whole(min(numbers)) if numbers else None


def _max(items: Any, key: Any = None) -> Any:
    numbers = _numbers(items, key, "max")
    return _whole(max(numbers)) if numbers else None


def _average(items: Any, key: Any = None) -> Any:
    numbers = _numbers(items, key, "average")
    return _whole(round(math.fsum(numbers) / len(numbers), 10)) if numbers else None


def _column_values(items: Any, key: Any) -> List[Any]:
    return _column(_items(items, "column"), key, "column")


def _unique(items: Any, key: Any = None) -> List[Any]:
    rows = _items(items, "unique")
    values = _column(rows, key, "unique") if key is not None else rows
    seen, kept = set(), []
    for value, row in zip(values, rows):
        number = _rules().number_value(value)
        marker = ("n", number) if number is not None else ("t", _text(value).strip().lower())
        if marker not in seen:
            seen.add(marker)
            kept.append(row)
    return kept


def _first(items: Any) -> Any:
    rows = _items(items, "first")
    return rows[0] if rows else None


def _last(items: Any) -> Any:
    rows = _items(items, "last")
    return rows[-1] if rows else None


def _contains(value: Any, part: Any) -> bool:
    return _rules().compare(value, "contains", part)


def _as_text(value: Any) -> str:
    """text(x): the value as text, so == and != compare it as text (`0012` is not `12`)."""
    return _rules().QuotedText(_text(value))


def _ifelse(test: Any, when_true: Any, when_false: Any) -> Any:  # _evaluate evaluates only the chosen branch
    return when_true if _rules().is_true(test) else when_false


# name -> (function, fewest arguments, most arguments)
FUNCTIONS: Dict[str, Tuple[Callable[..., Any], int, int]] = {
    "len": (_len, 1, 1),
    "join": (_join, 1, 2),
    "number": (_parse_number, 1, 1),
    "trim": (_trim, 1, 1),
    "lower": (_lower, 1, 1),
    "upper": (_upper, 1, 1),
    "replace": (_replace, 3, 3),
    "default": (_default, 2, 2),
    "round": (_round, 1, 2),
    "part": (_part, 3, 3),
    "substring": (_substring, 2, 3),
    "sort_by": (_sort_by, 1, 10),
    "where": (_where, 3, 4),
    "column": (_column_values, 2, 2),
    "sum": (_sum, 1, 2),
    "min": (_min, 1, 2),
    "max": (_max, 1, 2),
    "average": (_average, 1, 2),
    "unique": (_unique, 1, 2),
    "first": (_first, 1, 1),
    "last": (_last, 1, 1),
    "contains": (_contains, 2, 2),
    "text": (_as_text, 1, 1),
    "ifelse": (_ifelse, 3, 3),
}

# Comparisons inside ${...}, with the rules of conditions (docs/design/list-functions.md, L5)
_COMPARISONS = {ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}

_OPERATORS: Dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
}
_SYMBOLS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%"}


# ---------------------------------------------------------------------------------------------------
# Parsing and checking
# ---------------------------------------------------------------------------------------------------

_REFUSED = {
    ast.Lambda: "lambdas are not allowed",
    ast.ListComp: "comprehensions are not allowed",
    ast.SetComp: "comprehensions are not allowed",
    ast.DictComp: "comprehensions are not allowed",
    ast.GeneratorExp: "comprehensions are not allowed",
    ast.JoinedStr: "f-strings are not allowed; write ${...} for each value",
    ast.IfExp: "if / else is not allowed; use a condition on the step",
    ast.NamedExpr: "assignment is not allowed",
    ast.Await: "await is not allowed",
    ast.Starred: "* in arguments is not allowed",
}


def _check(node: ast.AST, text: str, depth: int = 0) -> None:
    """Refuses everything outside the allowed node types and functions."""
    if depth > MAX_DEPTH:
        raise ExpressionError(text, f"nested more than {MAX_DEPTH} levels deep")
    if isinstance(node, ast.Expression):
        _check(node.body, text, depth + 1)
    elif isinstance(node, ast.Constant):
        if node.value is not None and not isinstance(node.value, (str, int, float, bool)):
            raise ExpressionError(text, f"the value {node.value!r} is not allowed")
    elif isinstance(node, ast.Name):
        if node.id.startswith("_"):
            raise ExpressionError(text, f"the name '{node.id}' is not allowed (names starting with _ are internal)")
    elif isinstance(node, ast.Attribute):
        if node.attr.startswith("_"):
            raise ExpressionError(text, f"'.{node.attr}' is not allowed (names starting with _ are internal)")
        _check(node.value, text, depth + 1)
    elif isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            raise ExpressionError(text, "slices such as [1:3] are not allowed; use substring(...)")
        _check(node.value, text, depth + 1)
        _check(node.slice, text, depth + 1)
    elif isinstance(node, ast.BinOp):
        if type(node.op) not in _OPERATORS:
            raise ExpressionError(text, "only + - * / % are allowed")
        _check(node.left, text, depth + 1)
        _check(node.right, text, depth + 1)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            raise ExpressionError(text, "only - + and not are allowed before a value")
        _check(node.operand, text, depth + 1)
    elif isinstance(node, ast.Compare):
        for op in node.ops:
            if type(op) not in _COMPARISONS:
                raise ExpressionError(text, "only == != < <= > >= compare values; for `in` use contains(list, value)")
        _check(node.left, text, depth + 1)
        for comparator in node.comparators:
            _check(comparator, text, depth + 1)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            _check(value, text, depth + 1)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError(text, "only functions can be called, not methods such as x.upper(); use upper(x)")
        name = node.func.id
        if name not in FUNCTIONS:
            raise ExpressionError(text, f"unknown function '{name}'; available: {', '.join(sorted(FUNCTIONS))}")
        if node.keywords:
            raise ExpressionError(text, f"{name} takes its values in order, without names")
        _, fewest, most = FUNCTIONS[name]
        if not fewest <= len(node.args) <= most:
            wanted = str(fewest) if fewest == most else f"{fewest} to {most}"
            raise ExpressionError(text, f"{name} takes {wanted} value{'s' if most > 1 else ''}, got {len(node.args)}")
        for arg in node.args:
            _check(arg, text, depth + 1)
    else:
        reason = next((why for kind, why in _REFUSED.items() if isinstance(node, kind)), None)
        raise ExpressionError(text, reason or f"{type(node).__name__} is not allowed")


@lru_cache(maxsize=2048)
def _syntax(text: str) -> ast.Expression:
    """The syntax tree, not checked yet. Raises ExpressionSyntaxError."""
    if len(text) > MAX_LENGTH:
        raise ExpressionSyntaxError(text[:40] + "...", f"longer than {MAX_LENGTH} characters")
    if "${" in text:
        raise ExpressionSyntaxError(text, "write variables without ${...} inside an expression, for example ${len(rows)}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Python warns about some malformed text, such as "1if"
            tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as e:
        raise ExpressionSyntaxError(text, f"cannot be read ({e.msg})")
    except (ValueError, RecursionError, MemoryError) as e:
        raise ExpressionSyntaxError(text, f"cannot be read ({e.__class__.__name__})")
    return tree


@lru_cache(maxsize=2048)
def parse(text: str) -> ast.Expression:
    """The checked syntax tree of an expression. Raises ExpressionError."""
    tree = _syntax(text)
    _check(tree, text)
    return tree


def _means_expression(text: str) -> bool:
    return bool(_LOOKS_LIKE_EXPRESSION.search(text)) or "${" in text


means_expression = _means_expression  # for kinenix validate


def is_plain_path(tree: ast.Expression) -> bool:
    """True for a lookup such as `row.name`: names and dots only."""
    node = tree.body
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name)


# ---------------------------------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------------------------------

def _evaluate(node: ast.AST, variables: Dict[str, Any], text: str) -> Any:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, variables, text)
    if isinstance(node, ast.Constant):
        # Text written in quotes compares as text, as a quoted side of a condition does (#160)
        return _rules().QuotedText(node.value) if isinstance(node.value, str) else node.value
    if isinstance(node, ast.Name):
        if node.id == "env" and "env" not in variables:
            return _Environment()
        return variables.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _evaluate(node.value, variables, text)
        if isinstance(base, (dict, _Environment)):
            return base.get(node.attr)
        return None  # only dictionary keys are read; never attributes of Python objects
    if isinstance(node, ast.Subscript):
        base = _evaluate(node.value, variables, text)
        key = _evaluate(node.slice, variables, text)
        if isinstance(base, dict):
            return base.get(key) if isinstance(key, (str, int, float)) else None
        if isinstance(base, (list, tuple, str)):
            index = _whole_number(key, "the index")
            return base[index] if -len(base) <= index < len(base) else None
        return None
    if isinstance(node, ast.BinOp):
        symbol = _SYMBOLS[type(node.op)]
        left = _number(_evaluate(node.left, variables, text), f"the value before {symbol}")
        right = _number(_evaluate(node.right, variables, text), f"the value after {symbol}")
        if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0:
            raise ValueError("division by zero")
        result = _OPERATORS[type(node.op)](left, right)
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError("the result is too large")
        return _whole(result)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _rules().is_true(_evaluate(node.operand, variables, text))
        value = _number(_evaluate(node.operand, variables, text), "the value")
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Compare):
        rules = _rules()
        left = _evaluate(node.left, variables, text)
        for op, comparator in zip(node.ops, node.comparators):
            right = _evaluate(comparator, variables, text)
            try:
                if not rules.compare(left, _COMPARISONS[type(op)], right):
                    return False
            except rules.ConditionError as e:
                raise ExpressionError(text, e.reason) from None
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        is_true = _rules().is_true
        if isinstance(node.op, ast.And):
            return all(is_true(_evaluate(value, variables, text)) for value in node.values)
        return any(is_true(_evaluate(value, variables, text)) for value in node.values)
    if isinstance(node, ast.Call) and node.func.id == "ifelse":
        # Only the branch that is chosen is evaluated
        test, when_true, when_false = node.args
        chosen = when_true if _rules().is_true(_evaluate(test, variables, text)) else when_false
        return _evaluate(chosen, variables, text)
    if isinstance(node, ast.Call):
        function = FUNCTIONS[node.func.id][0]
        args: List[Any] = [_evaluate(arg, variables, text) for arg in node.args]
        return _whole(function(*args))
    raise ExpressionError(text, f"{type(node).__name__} is not allowed")  # _check refuses these first


def evaluate(text: str, variables: Dict[str, Any]) -> Any:
    """The value of an expression. Raises ExpressionError for every problem, and nothing else."""
    tree = parse(text)
    try:
        value = _evaluate(tree, variables, text)
        # Quoted text and text(...) compare as text inside the expression; what is stored is plain text
        return str(value) if isinstance(value, str) and type(value) is not str else value
    except ExpressionError:
        raise
    except Exception as e:  # a wrong type or value in a function or operator
        raise ExpressionError(text, str(e) or e.__class__.__name__)


def evaluate_unresolved(text: str, variables: Dict[str, Any]) -> Any:
    """
    For text inside ${...} that is not a variable that exists (docs/design/expressions.md, section 4):
    an expression gives its value; a missing lookup gives empty, as before expressions existed.
    """
    try:
        tree = _syntax(text)
    except ExpressionSyntaxError:
        if _means_expression(text):
            raise
        return None
    if is_plain_path(tree):
        return None
    try:
        parse(text)
    except ExpressionError:
        if _means_expression(text):
            raise
        return None
    if not _means_expression(text) and not _words_are_values(tree.body, variables):
        # A missing key with and / or / not in its name, such as `row.Terms and Conditions`: empty, as before
        return None
    return evaluate(text, variables)


def _words_are_values(node: ast.AST, variables: Dict[str, Any]) -> bool:
    """For text without symbols, such as `in_stock and cheap`: every value it joins exists and is set."""
    if isinstance(node, ast.BoolOp):
        return all(_words_are_values(value, variables) for value in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _words_are_values(node.operand, variables)
    if isinstance(node, (ast.Name, ast.Attribute)) and is_plain_path(ast.Expression(body=node)):
        return _evaluate(node, variables, "") is not None
    return True


def problem(text: str) -> Optional[str]:
    """For `kinenix validate`: why this ${...} text cannot be evaluated, or None when it can (or is a lookup)."""
    if text.startswith("env."):
        return None
    try:
        tree = _syntax(text)
        if not is_plain_path(tree):
            parse(text)
    except ExpressionError as e:
        return str(e) if _means_expression(text) else None
    return None
