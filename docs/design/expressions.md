# Design: Expressions in `${...}` (0.3.0b1)

Status: **approved** (2026-10-16). Milestone: [0.3.0b1: Expressions](https://github.com/kinenix/kinenix/milestone/3). Issue: #56. Checklist: #86.

## 1. Goal

A flow can count, join, clean, and calculate values inside `${...}` without workarounds, and nothing written in a flow can run code. Every flow that works today keeps working unchanged.

```markdown
- **subject:** ${len(packages)} packages for ${join(ok_ids, ', ')}
- **value:** ${number(row.premium) * 12}
- **name:** ${trim(upper(row.brand))}
- **first:** ${rows[0].request_id}
- **condition:** ${row.status} == Active and ${row.amount} > 0
```

## 2. Decisions

| # | Topic | Decision |
| :--- | :--- | :--- |
| E1 | Compatibility | A lookup that works today wins: `${row.First Name}` and `${row.Role in Company}` stay lookups. The text is read as an expression only when it is not a variable that exists (section 4) |
| E2 | Parsing | Python's own parser (`ast.parse`, which only builds a tree and runs nothing), then a whitelist of node types and our own evaluator. No `eval`, `exec`, or `compile` of code |
| E3 | Arithmetic | Numbers only. Text that is a plain number (`"12"`, `"3.5"`) counts as that number; other text is an error that suggests `number(...)` |
| E4 | Comparisons and `and` / `or` / `not` | In conditions only (section 6), where they already live. Inside `${...}` there are values, not comparisons, so equality has one meaning (the condition's, case-insensitive). **Changed in 1.1.0** ([list-functions.md](list-functions.md), L5): allowed inside `${...}` too, decided by the same comparison functions as conditions, so equality still has one meaning |
| E5 | Missing values | An unknown variable, key, or index is empty (`None`), as today. Functions treat empty as documented (section 5) |
| E6 | Errors | A malformed expression, an unknown function, or a wrong type fails the step with the expression and the reason, for example `${len(rows, 2)}: len takes 1 value, got 2` |
| E7 | Safety | No attribute access to Python objects: `.name` reads dictionary keys only, and names starting with `_` are refused (this also closes `${x.__class__}`, which today reads Python internals). Limits: 500 characters, nesting depth 20 |
| E8 | Validation | `kinenix validate` parses every `${...}` in a flow and reports syntax errors and unknown functions with their line |

## 3. Syntax

| Form | Example | Result |
| :--- | :--- | :--- |
| Lookup (as today) | `${row.First Name}`, `${config.email.to}`, `${env.HOME}` | The value |
| Index | `${rows[0]}`, `${rows[-1]}`, `${row['Unit Price (THB)']}`, `${rows[i].id}` | Item or key; empty when missing |
| Text and numbers | `'abc'`, `"abc"`, `12`, `3.5` | Literals for function arguments |
| Arithmetic | `${count + 1}`, `${number(row.price) * 1.07}`, `${total / len(rows)}`, `${n % 2}`, `${-x}` | Number; a whole result is shown without `.0` |
| Functions | `${len(rows)}`, `${join(ids, ', ')}` | Section 5 |
| Parentheses | `${(a + b) * 2}` | Grouping |

Not allowed, with a clear error: comparisons and `and`/`or`/`not` inside `${...}` (use a condition), attribute access to non-dictionaries, method calls (`x.upper()`), lambdas, comprehensions, f-strings, `**`, assignment, and any function outside the list.

## 4. Lookup or expression

For the text inside `${...}`:

1. `env.NAME`: the environment variable, as today.
2. Read it as a dotted path, as today. If the first part names an existing variable and every part is found, that is the value. `${row.Role in Company}` finds the key `Role in Company`.
3. Otherwise, parse it as an expression. If it parses, evaluate it.
4. If it does not parse and contains no expression syntax (parentheses, brackets, operators, or quotes), it is a missing lookup and gives empty, as today (`${row.Missing Column}`). If it does contain expression syntax, it is an error (E6).

So a dictionary key that happens to look like an expression is still read as a key, and nothing that resolves today changes its value. The only change: text inside `${...}` that resolved to empty and is a valid expression now has a value, for example `${len(items)}` (before: empty).

## 5. Functions

| Function | Result | Empty input |
| :--- | :--- | :--- |
| `len(x)` | Number of characters, items, or keys | `0` |
| `join(list, sep)` | Items as text, joined by `sep` (default `", "`) | `""` |
| `number(x)` | The first number in the text, without thousands separators and units: `"15,434.75 บาท/ปี"` gives `15434.75`, `"(1,200)"` gives `-1200` | empty; text with no number is an error |
| `trim(x)`, `lower(x)`, `upper(x)` | Text without surrounding spaces, lower case, upper case | `""` |
| `replace(x, old, new)` | Text with every `old` replaced | `""` |
| `default(x, fallback)` | `x`, or `fallback` when `x` is empty or `""` | `fallback` |
| `round(x, digits)` | Rounded number (`digits` defaults to 0), halves away from zero as in Excel | empty |
| `part(x, sep, n)` | Piece `n` of the text split at `sep`, counted from 0; a negative `n` counts from the end: `part('25-10-2019', '-', 1)` gives `10`, `part('INV-2026-00123', '-', -1)` gives `00123` | `""`, also when there is no piece `n` |
| `substring(x, start, length)` | `length` characters from position `start` (counted from 0), or to the end when `length` is left out; positions past the end give what is there | `""` |

Extra functions are added only when a real flow needs them; the list is in one place (`engine/expressions.py`), with its tests and `docs/flow_markdown_spec.md`.

## 6. Conditions: `and`, `or`, `not`

```markdown
- **condition:** ${row.status} == Active and ${row.amount} > 0
- **condition:** ${brand} is empty or ${model} is empty
- **condition:** not ${row.note} contains skip
```

- `and` binds tighter than `or`; there are no parentheses at this level. `not` applies to one comparison.
- A condition is split at ` and ` / ` or ` outside `${...}` and quotes, and **only when every part is a condition** (it has an operator, or is a single `${...}`). So `${company} == Johnson and Johnson` stays one comparison with the right side `Johnson and Johnson`, as today. Quoting is the safe form: `${company} == 'Johnson and Johnson'`.
- Each part keeps today's comparison rules (case-insensitive text, numeric `<` and `>`, `in`, `contains`, `is empty`).

## 7. Implementation

- `kinenix-core/kinenix/engine/expressions.py`: parse with `ast.parse(text, mode="eval")`, cache the tree per text, walk it with an evaluator that accepts only these nodes: `Expression`, `Name`, `Constant` (text and numbers), `Attribute` (dictionary key), `Subscript`, `BinOp` (`+ - * / %`), `UnaryOp` (`-`, `+`), `Call` (whitelisted name, positional arguments). Every other node is refused.
- `engine/evaluator.py`: the order of section 4; the dotted lookup stops reading attributes of non-dictionaries and names starting with `_`.
- `engine/conditions.py`: `and` / `or` / `not` as in section 6, on top of the existing splitter.
- `engine/validation.py`: expression syntax and function names in `kinenix validate`.

## 8. Tests

- Each function and operator, with normal, empty, and bad input; numbers from Thai and English text.
- Compatibility: every example flow and every existing test runs unchanged; keys with spaces, parentheses, and the word `in`.
- Safety: `__class__`, `__import__`, method calls, lambdas, comprehensions, `**`, very long and deeply nested input are refused; the evaluator module contains no `eval`, `exec`, or `compile` call.
- Fuzz: thousands of random and malformed expressions built from the grammar and from random characters; each ends within a time limit with a value or an expression error, never another exception.

## 9. Out of scope

User-defined functions, loops, or lambdas (never, for safety); date arithmetic (`date.calc`); regular expressions (1.1.0 if a real flow needs them); comparisons inside `${...}` (conditions do this).
