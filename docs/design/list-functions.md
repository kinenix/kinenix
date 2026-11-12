# Design: Working with lists in `${...}` (1.1.0)

Status: **approved** (2026-11-11). Milestone: [1.1.0: Flow data tools](https://github.com/kinenix/kinenix/milestone/8). Issues: #142 (sort), #143 (filter, count, sum), #144 (true/false values without `logic.if`). Builds on [expressions.md](expressions.md).

## 1. Goal

After `web.get_list`, `web.get_table`, `excel.read`, or `csv.read`, a flow can sort, filter, count, and add up rows, and set a true/false or either-or value, in one step instead of a loop. Nothing written in a flow can run code, and every flow that works on 1.0 keeps working unchanged.

Found by an AI assistant building `get_book` (books from books.toscrape.com) on 1.0.0rc3:

- Sorting 40 books by category and price took 35 lines of nested loops and ran 1,300 steps instead of 150 (#142).
- Counting the cheap books of a category took a counter, a loop, and a `logic.if` (#143).
- Each true/false column of a row took a 16-line `logic.if` with `Else-steps` (#144).

## 2. Before and after

Before (#144), for one column:

```markdown
- Set Cheap Mark (`logic.if`):
  - **condition:** `${price_num} < ${config.cheap_limit}`
  - **Sub-steps:**
    - Mark As Cheap (`logic.set_variable`):
      - **name:** `cheap_val`
      - **value:** true
  - **Else-steps:**
    - Mark As Not Cheap (`logic.set_variable`):
      - **name:** `cheap_val`
      - **value:** false
```

After, in the row itself:

```markdown
- **value:** {"title": "${book.title}", "cheap": "${price_num < config.cheap_limit}", "in_stock": "${contains(book.availability, 'In stock')}"}
```

After (#142, #143), with no loop:

```markdown
1. **Sort The Books** (`logic.set_variable`)
   - name: `sorted_books`
   - value: `${sort_by(books, 'category', 'price')}`

2. **Write The Summary** (`logic.set_variable`)
   - name: `summary`
   - value: `${len(where(books, 'price', '<', config.cheap_limit))} cheap books, ${sum(books, 'price')} THB in total`
```

## 3. Decisions to make

Each has a recommendation; the rest of this document follows the recommendations.

| # | Topic | Options | Recommendation |
| :--- | :--- | :--- | :--- |
| L1 | Where sorting lives | (a) `sort_by` and `descending` on `excel.write` and `csv.write`, as #142 asks; (b) a `logic.sort` action; (c) a function `sort_by(...)` in `${...}` | **Agreed: (c)**: one function works with every action (email, `logic.loop`, a file), and no write action grows sort parameters |
| L2 | Descending order | (a) a `-` before the key: `sort_by(rows, 'category', '-price')`; (b) a separate `sort_by_desc`; (c) a last argument `'desc'` | **Agreed: (a)**. Low to high is the default; `-` asks for high to low, and one call can mix directions. A `-` at the start of a key always means high to low (section 5, rule 3) |
| L3 | Filtering | (a) only a function `where(list, key, operator, value)`; (b) only a `logic.filter` action with a full condition per item; (c) both | **Agreed: (a)**. Two conditions that must both hold are two `where` calls, one inside the other; `logic.filter` waits until a real flow needs `or` (section 7) |
| L4 | Counting | (a) `count(list, key, value)` as #143 asks; (b) `len(where(...))` | **Agreed: (b)**: one way to filter, and `len` exists. No `count` function |
| L5 | Comparisons inside `${...}` (#144) | (a) keep them out (expressions.md, E4) and add functions `lt`, `gt`, `eq`; (b) allow `<`, `<=`, `>`, `>=`, `==`, `!=`, `and`, `or`, `not` inside `${...}`, with the rules of conditions; (c) only an `ifelse` function | **Agreed: (b)** and an `ifelse` function: flows built by AI assistants write `${a < b}` without being told, and one set of comparison rules (conditions.py) decides both places, so `100 == 100.0` and `'0012'` mean the same everywhere |
| L6 | Choosing number or text comparison | (a) as today: two values that look like numbers compare as numbers, a value in quotes as text; (b) also a function `text(x)` that makes a value compare as text, beside the existing `number(x)`; (c) column types when a file is read (`types: {code: text}` on `excel.read`); (d) a strict operator such as `===` | **Agreed: (a) and (b)**: `${text(a.code) == text(b.code)}` keeps codes such as `0012` apart from `12` also between two variables, where quotes cannot help. (c) waits for a real problem when reading files |

L5 changes decision E4 of expressions.md. E4 kept comparisons out so equality had one meaning; using the same comparison functions as conditions keeps that promise.

## 4. Syntax added

| Form | Example | Result |
| :--- | :--- | :--- |
| Comparison | `${price < config.cheap_limit}`, `${row.status == 'Active'}` | `true` or `false`, by the rules of conditions (section 6) |
| `and`, `or`, `not` | `${in_stock and price < 20}`, `${not done}` | `true` or `false`; `and` and `or` stop at the first deciding side |
| Parentheses | `${(a or b) and c}` | Grouping, inside `${...}` only. A step's `condition` still has no parentheses (#195, 1.2.0) |

Still not allowed: `a if b else c` (use `ifelse`), lambdas, comprehensions, method calls, and every function outside the list.

## 5. Functions added

| Function | Result | Empty or missing |
| :--- | :--- | :--- |
| `sort_by(list, key, ...)` | A new list sorted by one or more keys; `-key` sorts that key from high to low. Numbers (and text that is one number, such as `"1,200"`) sort as numbers, other text by its letters without case. The order of equal rows stays as it was | `[]` for an empty list; rows without the key go last |
| `where(list, key, operator, value)` | A new list of the rows whose `key` compares to `value`. Operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`, `not contains`, `in`, `not in`, `starts with`, `ends with`, `is empty`, `is not empty` (the last two take no `value`) | `[]` |
| `column(list, key)` | The values of one key, in order: `column(rows, 'id')` gives `['A1', 'A2']` | `[]` |
| `sum(list)`, `sum(list, key)` | The total of the numbers, or of one key | `0`; text that is not a number is an error, as with `+` |
| `min(...)`, `max(...)`, `average(...)` | Smallest, largest, mean; same arguments as `sum` | empty |
| `unique(list)`, `unique(list, key)` | The values once each, in the order first seen; with a key, one row per value of that key (the first) | `[]` |
| `first(list)`, `last(list)` | The first or last item | empty |
| `text(x)` | The value as text, so `==` and `!=` compare it as text: `text(12)` is `'12'`, and `text(a.code) == text(b.code)` keeps `0012` apart from `12` (L6) | `''` |
| `contains(text_or_list, part)` | `true` when the text holds `part` (without case) or the list holds the value | `false` |
| `ifelse(test, when_true, when_false)` | `when_true` when `test` is true, else `when_false` | a missing `test` counts as false |

Rules:

1. Functions never change the list they are given; they return a new one. `sort_by(rows, ...)` leaves `rows` as it was.
2. A key is a column name, as in `${row['Unit Price (THB)']}`. A key that no row has is an error (`where: no row has the key 'prcie'; keys: title, price, category`), because a misspelled key would otherwise give an empty list without a warning.
3. For L2, a `-` at the start of a key always means high to low; column names that start with `-` are not supported by `sort_by`.
4. Text values are what they look like: `"true"` from a cell is text, not `true`. The comparison rules decide (section 6).
5. Size limit: 100,000 items in one list, so a flow cannot hang the worker with one call.

## 6. One set of comparison rules

`where`, `sort_by`, `contains`, and comparisons in `${...}` use the functions conditions use today (`conditions.py`: `values_equal`, `compare_order`, `number_value`):

- `==` and `!=`: two numbers compare as numbers (`100 == 100.0`, `"1,200" == 1200`); anything else compares as text, without case and surrounding spaces. A value in quotes inside `${...}`, or one passed through `text(...)`, compares as text, as a quoted side in conditions does (#160): `${branch == '0012'}` does not match `12`, nor does `${text(branch) == text(other.branch)}`.
- `<`, `<=`, `>`, `>=`: both sides must be numbers; an empty side or other text stops the step with exit code 4 and says which value is the problem, as a condition does.
- `sort_by` does not stop on mixed values: numbers come before text, and empty values come last.

## 7. Filters with more than one comparison (L3)

Two comparisons that must both hold are two `where` calls, the inner one first:

```markdown
- value: `${where(where(books, 'price', '<', config.cheap_limit), 'availability', 'contains', 'In stock')}`
```

Either of two comparisons (`or`) is not covered: two `where` calls and a loop that joins them, or one `logic.loop` with a condition. If real flows need it often, a `logic.filter` action with a full step condition per item comes in a later release; it would use the same comparison rules.

## 8. Compatibility

- Additions only. A `${...}` text that is a variable today is still read as that variable (expressions.md, E1). Text with `<` or `>` inside `${...}` was refused before, so no working flow changes meaning.
- A flow that uses any of this needs `> Requires: kinenix>=1.1.0`. `kinenix validate` names the function or form that needs it, through the list of newer features (#198).
- `docs/compatibility.md`: the new functions and comparisons become part of the 1.x promise when 1.1.0 is released.

## 9. Implementation

- `engine/expressions.py`: the functions in `FUNCTIONS`; `ast.Compare`, `ast.BoolOp`, and `not` move from refused to allowed, evaluated through `conditions.values_equal` and `compare_order`. Limits stay: 500 characters, nesting depth 20.
- `engine/conditions.py`: the operator table shared with `where`.
- `engine/requires.py`: the new names in the newer-features list (#198).
- `docs/flow_markdown_spec.md`, `llms.txt`, and the `AGENTS.md` template for new projects: the new functions, with the before-and-after of section 2, so AI assistants use them.

## 10. Tests

- Each function with normal, empty, missing-key, and mixed input; Thai text and numbers with separators.
- Comparisons in `${...}` give the same answer as the same comparison in a step's condition, for a table of cases (numbers, quoted codes, empty values, text).
- `sort_by`: stable order, several keys, `-key`, numbers stored as text, rows without the key.
- `where` inside `where`, every operator, an empty list, a value that cannot be compared as a number.
- Safety and fuzz, as for expressions: the new nodes cannot reach Python internals, and random input ends with a value or an expression error.
- The `get_book` flow from #142 rewritten with these functions gives the same files with about 150 steps instead of 1,300.

## 11. Out of scope

`logic.filter` with `or` (section 7); grouping (`group_by`) and joining two lists (a later issue if a real flow needs them); regular expressions; user-defined functions or lambdas (never); parentheses in a step's `condition` (#195, 1.2.0).
