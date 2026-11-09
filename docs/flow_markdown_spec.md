# Flow Markdown Specification (`flow.md` Rulebook)

This document establishes the official syntax rules and structural guidelines for **`flow.md`**, the file format of every Kinenix flow.

---

## 1. Vision & Core Principles

A Kinenix flow is one file, **`flow.md`**: the file people read, the file an AI assistant writes, and the file Kinenix runs.

- **Readable:** Markdown with headings and bullet points, readable on GitHub, in an editor, or in a pull request diff.
- **Written well by AI:** the step headings and `- **parameter:** value` bullets are easy for language models to produce. In a comparison on the `bot_fx_rate` requirement, a local 7B model wrote valid `flow.md` more reliably than the same flow in YAML, whose quoting rules clash with `${...}` expressions ([benchmark](benchmarks/flow_format.md)).
- **Checked before it runs:** `kinenix validate`, `kinenix run`, and the worker parse the file, then report unknown actions and parameters, lines the parser ignores, and step headings without an action, with line numbers and suggestions.

There is no separate JSON file to keep in sync. `kinenix run` and `kinenix-worker run` read `flow.md` directly and compile it in memory on every run; subflows (`flow.call`) work the same way. To inspect the compiled form, run `kinenix compile <bundle>`, which prints it as JSON (validated against [flow.schema.json](../schemas/flow.schema.json)) without writing any file next to `flow.md`.

Flows written as `flow.json` by Kinenix 0.2.0b3 or older are not run; `kinenix export-md <bundle>` converts one into `flow.md` once. Files with a UTF-8 BOM (written by Windows PowerShell 5 and some editors) are read correctly.

---

## 2. The 5 Golden Rules of `flow.md`

To ensure 100% deterministic compilation without requiring massive cloud LLMs, every `flow.md` must strictly adhere to the following 5 rules:

```text
Rule 1: Document Header & Metadata (Title, Description, Variables)
Rule 2: Step Declarations with Mandatory Action Anchors in Parentheses
Rule 3: Key-Value Action Parameters as Bullet Points
Rule 4: Standard Indentation for Nested Sub-steps (Loops & Conditions)
Rule 5: Variable Interpolation Syntax (${config.*}, ${var.*})
```

---

### Rule 1: Document Header & Metadata

Every `flow.md` must start with a Level 1 Heading (`#`) denoting the Flow Name, followed by optional blockquotes for description and version, and an optional `## Variables` section.

#### Syntax
```markdown
# [Flow Name]
> Description: [Brief summary of business intent]
> Version: [Semantic version, e.g. 1.0.0]
> Requires: [Kinenix version needed, e.g. kinenix>=0.2.0b4]

## Variables
- `variable_name`: [initial_value]
```

`> Requires:` is optional. A Kinenix older than the version named refuses to run the flow with a message to upgrade. Flows that use `## On Error` or `## Finally` need `> Requires: kinenix>=0.2.0b4` (section 3.2).

#### Example
```markdown
# RPA Challenge Solver
> Description: Automatically complete 10 rounds of RPA Challenge form submission using Excel data.
> Version: 1.0.0

## Variables
- `non_programmers`: []
- `processed_count`: 0
```

---

### Rule 2: Step Declarations & Mandatory Action Anchors

Each step must be declared as a Level 3 Heading (`###`) and **MUST** include the exact registered action name in parentheses `([action_name])`.

#### Syntax
```markdown
### [Step Number or ID]. [Step Name] (`[action.name]`)
```

- **Step Number / ID:** Can be a number (`1.`) or explicit ID (`step_1.`). If a number is given, the compiler automatically assigns `step_1`, `step_2`, etc.
- **Action Anchor:** The action name enclosed in parentheses (e.g. `(web.open)`, `(excel.read)`, `(logic.loop)`). This anchor prevents AI models from inventing unregistered action names.

#### Example
```markdown
### 1. Open Challenge Webpage (`web.open`)
### 2. Read Candidate Spreadsheet (`excel.read`)
### 3. Click Start Timer Button (`web.click`)
```

---

### Rule 3: Key-Value Action Parameters as Bullet Points

All parameters passed to the action must be written as Markdown bullet items directly under the step header, using the format `- **parameter_name:** value`.

#### Syntax
```markdown
### [Step Name] (`[action.name]`)
- **[parameter_1]:** [value]
- **[parameter_2]:** [value]
- **output_var:** [variable_name]
```

#### Supported Value Types:
- **String:** `- **url:** https://example.com`
- **Boolean:** `- **headless:** false` or `- **clean_headers:** true`
- **Number:** `- **timeout:** 5000` or `- **delay:** 1.5`. A value with a leading zero, such as `- **branch:** 0012`, stays text, so codes keep their zeros. To make any value text, quote it: `"120"`
- **List or object (JSON):** `- **columns:** ["Date", "Rate"]` or `- **item:** {"net": "${number(inv.amount)}"}`. Put quotes around `${...}` inside JSON; a value written as `{...}` or `[...]` that is not valid JSON is read as text, and `kinenix validate` reports it
- **Dynamic Variable Expression:** `- **url:** ${config.website}`
- **Output Variable:** `- **output_var:** my_result` (stores action result in context). An action that returns nothing and a step that fails leave it empty, so a loop never reuses the previous item's value; a step skipped by its `condition` leaves it as it was
- **Error Handling:** `- **on_error:** continue`, `- **max_retries:** 2`, `- **retry_interval:** 3.0`, `- **fallback_step_id:** step_9` (deprecated). These four keys are compiled into the step's `error_handler`, not into the action parameters (see [Step Resilience & Error Handling](actions_reference.md#step-resilience--error-handling-error_handler)).

#### Example
```markdown
### 1. Open Challenge Webpage (`web.open`)
- **url:** `${config.website}`
- **headless:** false
- **timeout:** 10000

### 2. Read Candidate Spreadsheet (`excel.read`)
- **file_path:** `${config.excel_path}`
- **clean_headers:** true
- **output_var:** `challenge_data`
```

---

#### Multi-line Values
A value with several lines, such as an email body, starts with `|` after the parameter name. The lines below it that are indented further than the parameter line are its value; their common indentation is removed, and blank lines inside are kept. The value ends at the first line that is not indented further, such as the next parameter.

```markdown
### 5. Email Report (`email.send`)
- **to:** `${config.email.to}`
- **subject:** Insurance packages
- **body:** |
    Hello,

    The packages for ${request_count} requests are attached.
    - Source: tipinsure.com
- **attachments:** ["${packed.zip_path}"]
```

The `body` above is `"Hello,\n\nThe packages for ${request_count} requests are attached.\n- Source: tipinsure.com"`. A `|` with no indented lines after it is the plain value `|` (for example `- **delimiter:** |`). Text lines under a step that are neither a parameter nor part of a `|` value are ignored, and `kinenix validate` reports each one with its line number.

---

### Rule 4: Standard Indentation for Control Flow (`logic.loop` & `logic.if`)

For actions that contain nested steps, use standard Markdown 2-space or 4-space indentation under `- **Sub-steps:**` (and optionally `- **Else-steps:**` for `logic.if`).

#### A. Loop Syntax (`logic.loop`)
```markdown
### [Step Name] (`logic.loop`)
- **items:** `${collection_variable}`
- **item_var:** `item_name`
- **Sub-steps:**
  - [Child Step Name] (`[action.name]`):
    - **param1:** value
    - **param2:** value
```

#### B. Condition Syntax (`logic.if`)
```markdown
### [Step Name] (`logic.if`)
- **condition:** `${row.Status} == 'Active'`
- **Sub-steps:**
  - [Then Step Name] (`[action.name]`):
    - **param1:** value
- **Else-steps:**
  - [Else Step Name] (`[action.name]`):
    - **param1:** value
```


#### C. Conditions
`condition` on any step runs the step only when the condition is true; on `logic.if` it chooses between `Sub-steps` and `Else-steps`. A condition is `left operator right`, or `left is empty` / `left is not empty`:

| Operator | True when |
| :--- | :--- |
| `==`, `!=` | the two sides are equal / differ. Two numbers compare as numbers, so `100.0`, `100`, and `100.00` are equal; anything else compares as text and ignores case. A side in quotes always compares as text |
| `>`, `>=`, `<`, `<=` | both sides are numbers and compare so. `1,200` and `฿1200` are numbers; a side that is empty or is other text, such as `N/A` or `12 items`, stops the run with exit code 4 and says why |
| `contains`, `not contains` | right is / is not part of left; with a list on the left, an item equals right |
| `in`, `not in` | left is / is not part of right; with a list on the right, an item equals left |
| `starts with`, `ends with` | left starts / ends with right |
| `is empty`, `is not empty` | left is / is not missing or blank (no right side) |

The condition is split into its sides before variables are replaced, so values containing `<`, `>`, or the word `in` (for example `< 5,000 km`) never split it, and neither does text inside `${...}` or quotes. Quote a literal that contains an operator: `${label} == 'x > y'`.

Join comparisons with `and` and `or`, and put `not` before one comparison (Kinenix 0.3.0b1 and newer). `and` binds tighter than `or`. Parentheses cannot group a condition: `kinenix validate` and the run report it. Write out each case instead, or use `logic.if` steps:

```markdown
- **condition:** `${tier} == VIP and ${paid} == yes or ${amount} > 1000 and ${paid} == yes`
```

**Numbers and text:** values from CSV files and web pages are text, so a code such as `0012` looks like a number. When a value is a code, compare it as text with quotes: `${branch} == '0012'` is false for `12`, while `${branch} == 0012` is true. To compare a value that may be empty, check it first: `${amount} is not empty and ${amount} > 0`. To take a number out of longer text, use `number`: `${number(price)} > 500`.

Examples:

```markdown
- **condition:** `${row.status} == Active and ${row.amount} > 0`
- **condition:** `${brand} is empty or ${model} is empty`
- **condition:** `not ${row.note} contains skip`
```

A condition is split at `and` / `or` only when every part is a comparison by itself, so `${company} == Johnson and Johnson` still compares with the text `Johnson and Johnson`. Quoting is the safe form: `${company} == 'Johnson and Johnson'`.

```markdown
### 6. Skip Requests Without A Model (`flow.fail`)
- **condition:** `${req.model} is empty`
- **message:** Request ${req.request_id} has no car model
- **category:** business
```

#### Example
```markdown
### 4. Loop Applicants and Submit Form (`logic.loop`)
- **items:** `${challenge_data}`
- **item_var:** `row`
- **Sub-steps:**
  - Fill First Name (`web.type`):
    - **selector:** `//input[@ng-reflect-name="labelFirstName"]`
    - **text:** `${row.First Name}`
  - Fill Last Name (`web.type`):
    - **selector:** `//input[@ng-reflect-name="labelLastName"]`
    - **text:** `${row.Last Name}`
  - Click Round Submit Button (`web.click`):
    - **selector:** `input[value="Submit"]`
```

---

### Rule 5: Variable Interpolation Syntax

Dynamic variables must use the standard expression format:

- **`${config.property}`**: Accesses configuration values loaded from `config/config.json`.
- **`${variable_name}`**: Accesses runtime variables initialized in flow or stored by `output_var`.
- **`${item.property}`**: Accesses fields of the current iteration object in `logic.loop`.
- **`${env.VAR_NAME}`**: Accesses operating system environment variables.
- **`${error.*}`** and **`${run.*}`**: The last failure and the current run (section 3.3).
- **`${__flow_dir__}`**: The absolute path of the flow's bundle folder. Relative paths in file actions already resolve against it; use it to build an absolute path, for example to pass a file location to a subflow: `"${__flow_dir__}/output/report.csv"`.

#### Expressions (Kinenix 0.3.0b1 and newer)

Inside `${...}`, a value can also be calculated: counted, joined, cleaned, picked from a list, or computed. Nothing written in a flow can run code; only the functions and operators below exist. Design: [design/expressions.md](design/expressions.md).

```markdown
- **subject:** ${len(packages)} packages for ${join(ok_ids, ', ')}
- **value:** ${number(row.premium) * 12}
- **name:** ${trim(upper(row.brand))}
- **first:** ${rows[0].request_id}
- **month:** ${part(row.due_date, '-', 1)}
```

| Function | Result | Example |
| :--- | :--- | :--- |
| `len(x)` | Number of items, keys, or characters; `0` when empty | `${len(rows)}` |
| `join(list, sep)` | The items as text, joined by `sep` (default `", "`) | `${join(ids, ', ')}` gives `R001, R002` |
| `number(x)` | The first number in the text, without thousands separators and units; `(1,200)` is `-1200`, `.5` is `0.5`; empty when empty. It stops at the first space or letter, so `12 345` is `12` and `1e5` is `1` | `${number('15,434.75 บาท/ปี')}` gives `15434.75` |
| `trim(x)`, `lower(x)`, `upper(x)` | Without surrounding spaces, lower case, upper case | `${trim(row.name)}` |
| `replace(x, old, new)` | Every `old` replaced by `new` | `${replace(row.price, ' บาท', '')}` |
| `default(x, fallback)` | `x`, or `fallback` when `x` is empty | `${default(row.note, '-')}` |
| `round(x, digits)` | Rounded number (`digits` defaults to 0). Halves go away from zero, as in Excel: `2.5` gives `3`, `-2.5` gives `-3`, and `round(2.675, 2)` gives `2.68` | `${round(total / count, 2)}` |
| `part(x, sep, n)` | Piece `n` (from 0; negative counts from the end) of the text split at `sep` | `${part('25-10-2019', '-', 1)}` gives `10` |
| `substring(x, start, length)` | `length` characters from position `start` (from 0), or to the end | `${substring('TH2026ABC', 2, 4)}` gives `2026` |

| Form | Example |
| :--- | :--- |
| Arithmetic on numbers: `+ - * / %` and parentheses | `${(count + 1) * 2}`, `${number(row.price) * 1.07}` |
| Index into a list (from 0; `-1` is the last) | `${rows[0]}`, `${rows[-1].id}` |
| Key with spaces or symbols | `${row['Unit Price (THB)']}` (or `${row.Unit Price (THB)}`, as before) |
| Text and numbers as values | `'abc'`, `"abc"`, `12`, `3.5` |

- **Values inside text read as written in a flow.** In `Total: ${x}`, `1200.0` gives `1200`, true gives `true`, and a list or object gives JSON, such as `[{"a": 1}]`. A value alone, such as `${x}`, keeps its type, so `excel.write` still gets a number. To control decimals, use `round`.
- **Arithmetic needs numbers.** Text that is a plain number (`"12"`, `"3.5"`, as read from CSV) counts as a number; other text is an error that suggests `number(...)`. A whole result is written without `.0`.
- **Missing values are empty**, as for variables: a missing key or an index past the end gives empty, and the functions treat empty as listed above.
- **A variable that exists is always read as before.** `${row.First Name}` and `${row.Role in Company}` are keys of `row`, not expressions. Text is evaluated as an expression only when it names no existing variable.
- **Comparisons and `and` / `or` / `not` belong in conditions**, not inside `${...}`: write `${count} > 3`, not `${count > 3}`.
- **Not allowed:** method calls (`x.upper()`; use `upper(x)`), names starting with `_`, `**`, slices (`[1:3]`; use `substring`), lambdas, comprehensions, and any function not in the table. Expressions are limited to 500 characters.
- **Errors stop the step** with the expression and the reason, for example `${lenn(rows)}: unknown function 'lenn'`. `kinenix validate` reports them before a run, with the line.

---

## 3. Failures: Retries, On Error, and Finally

### 3.1 Retries and `on_error` on a step

Any step can retry and then decide what happens:

```markdown
### 2. Open Portal (`web.open`)
- **url:** ${config.portal_url}
- **max_retries:** 2
- **retry_interval:** 5
- **on_error:** continue
```

`max_retries` always retries first (2 more attempts above). Only the last attempt counts in the run's record, also for a `flow.call`: a step that succeeds on a retry is not a failure, and the step's `retries` says how many it took. After the last attempt, `on_error` decides:

| `on_error` | After the last attempt |
| :--- | :--- |
| not set, `fail`, or `stop` | The flow fails: the remaining steps are skipped and `## On Error` runs |
| `retry` | Same as `fail`. Deprecated: removed in Kinenix 2.0; `kinenix validate` and every run warn. Delete the line, `max_retries` does the retrying |
| `continue` | The failure is recorded and the flow goes on with the next step |
| `next_item` | For a step inside a `logic.loop` (Kinenix 0.4.0b1): the failure is recorded, the rest of this item's sub-steps are skipped, and the loop goes on with its next item. The item counts as failed. Outside a loop it stops the flow like `fail`, and `kinenix validate` reports it |

`continue` inside a loop goes on with the next sub-step of the same item, which suits an optional step such as a screenshot. To give up on an item, for example when `flow.fail` finds bad data, use `next_item`:

```markdown
> Requires: kinenix>=0.4.0b1

### 1. Each Invoice (`logic.loop`)
- **items:** ${invoices}
- **item_var:** inv
- **item_label:** ${inv.no}
- **Sub-steps:**
  - No Amount (`flow.fail`):
    - **condition:** `${inv.amount} is empty`
    - **message:** Invoice ${inv.no} has no amount
    - **on_error:** next_item
  - Add To Summary (`logic.append`):
    - **target:** summary
    - **item:** {"no": "${inv.no}", "amount": "${number(inv.amount)}"}
```

With nested loops, `next_item` ends the item of the innermost loop. In a subflow called for each item, set `next_item` on the `flow.call` step in the loop; the subflow's own steps are not inside that loop.

**Where these keys go:** on the step that may fail. They have no effect on `logic.if`, `logic.loop`, or `flow.return`, and `kinenix validate` reports them there. Put them on the steps inside the block:

```markdown
### 3. Each Invoice (`logic.loop`)
- **items:** ${invoices}
- **item_var:** `inv`
- **Sub-steps:**
  - Upload (`http.request`):
    - **url:** ${config.api_url}
    - **max_retries:** 2
    - **on_error:** continue
```

For a failure anywhere in the flow, use `## On Error` (section 3.2). To go on after a whole block fails, put `on_error: continue` on each step inside it, or move the block to a subflow and set `on_error` on the `flow.call`, which does retry and continue.

`fallback_step_id` still runs a recovery step instead, but it is deprecated and removed in Kinenix 2.0: use `on_error: continue` and a next step with a `condition`, or `## On Error`. `max_retries` and `retry_interval` accept `${...}`, for example `${config.retries}`. Business errors (`flow.fail`) are not retried.

### 3.2 `## On Error` and `## Finally`

Steps that handle a failure for the whole flow go into two optional sections after `## Steps`:

```markdown
# TIPH Quotes
> Requires: kinenix>=0.2.0b4

## Steps
### 1. Open Portal (`web.open`)
- **url:** ${config.portal_url}

## On Error
### 1. Capture Screen (`web.screenshot`)
- **path:** ./output/error.png
### 2. Email Error (`email.send`)
- **to:** ${config.email.to}
- **subject:** TIPH failed at ${error.step_name}
- **body:** |
    ${error.message}

    Where: ${error.path} (line ${error.line})
    Item: ${error.loop.item}
- **attachments:** ["./output/error.png"]

## Finally
### 1. Close Browser (`web.close`)
```

Run order:

1. `## Steps` run in order.
2. When a step fails (after its retries, and its `on_error` is not `continue`), the remaining steps are skipped, `${error}` is set, and `## On Error` runs. A `flow.fail` runs it too.
3. `## Finally` runs every time: after success, after a failure, and after `flow.return`.
4. The run is **failed** when Steps failed; On Error does not turn a failure into a success. A step that fails in Finally also makes the run fail, and the log says `in Finally`; On Error does not run for it.

A failing step inside On Error or Finally is recorded and the rest of that section still runs. Steps in these sections are ordinary steps: parameters, `condition`, loops, and `flow.call` work the same. Their ids are `on_error_N` and `finally_N`. A subflow can have its own On Error and Finally; they run inside the subflow, then the failure continues to the caller.

`> Requires: kinenix>=0.2.0b4` under the title is needed for flows with On Error or Finally: Kinenix 0.2.0b3 and older would run their steps as ordinary steps on every run, while newer versions refuse a flow that needs a version they are not. `kinenix validate` reports a missing line.

**When a run is stopped:** Ctrl+C, `systemctl stop`, and `systemctl restart` ask the run to stop. The current step ends, the remaining steps are skipped, `## Finally` runs, the log is written, and the run reaches the Hub as `interrupted`, with exit code 130. `## On Error` does not run, because nothing failed. In a subflow, its own Finally runs first.

- A step that waits, such as a page that loads, ends at its timeout. `logic.delay` ends at once.
- A second Ctrl+C or SIGTERM stops the process at once: Finally is cut short and no final log is written.
- `kinenix-worker daemon` starts no new run and waits up to 60 seconds for the running flows.
- `systemctl stop` also ends the browser, so web steps in Finally may fail. Keep Finally to files, emails, and other work that needs no open page.
- SIGKILL, a power cut, and `taskkill /F` on Windows cannot be handled: only the live `.jsonl` log remains.

### 3.3 `${error}` and `${run}`

`${error}` describes the step that failed in `## Steps`, including one handled by `on_error: continue`. Failures inside On Error and Finally do not replace it. Values are redacted like logs ([logging.md](logging.md#redaction)).

| Field | Example |
| :--- | :--- |
| `${error.message}` | `Timeout 30000ms exceeded waiting for role=option[name='HONDA']` |
| `${error.type}` | `Technical` or `Business` |
| `${error.step_id}`, `${error.step_name}`, `${error.action}` | `sub_step_3_1`, `Choose Brand`, `web.click` |
| `${error.path}` | `TIPH Quotes > Each Request > process_one > Choose Brand` (loops, conditions, and subflows on the way) |
| `${error.subflow}` | `process_one`, or empty |
| `${error.line}` | Line of the step heading in its `flow.md` |
| `${error.loop.item}`, `${error.loop.index}`, `${error.loop.of}` | `R007 HONDA HR-V`, `7`, `12` (innermost loop; index starts at 1) |
| `${error.retries}` | `2` |
| `${error.root_cause}`, `${error.suggested_fix}` | Kinenix's diagnosis of the failure |
| `${error.screenshot}` | Path of the automatic failure screenshot, or empty |
| `${error.exception}`, `${error.section}` | `TimeoutError`; `steps` |

When a step inside a subflow fails, the caller's `${error}` describes that inner step.

`${run}` describes the run; subflows share it:

| Field | Meaning |
| :--- | :--- |
| `${run.id}` | Unique id of the run, such as `20261013T221502-qhzk`; use it in paths: `./output/${run.id}/`, or `"error_dir": "./output/errors/${run.id}"` in config |
| `${run.flow}`, `${run.started}` | Flow name, start time |
| `${run.status}` | `running` in Steps and On Error; `success`, `failed`, or `interrupted` in Finally |
| `${run.log_path}` | The run's live log (one JSON line per finished step), for attaching to an error e-mail ([logging.md](logging.md)) |

`error` and `run` are reserved variable names.

### 3.4 `item_label` on `logic.loop`

`item_label` names the item a loop is working on, so `${error.loop.item}` (and later the Hub's run records) say which one failed:

```markdown
### 2. Each Request (`logic.loop`)
- **items:** ${requests}
- **item_var:** req
- **item_label:** ${req.request_id} ${req.brand} ${req.model}
- **Sub-steps:**
  - Choose Brand (`web.click`):
    - **selector:** text=${req.brand}
```

Without `item_label`, the first three fields of the item are used. The label is built from a redacted copy of the item.

Loops with `item_label` are the flow's work items: the run log counts them as done or failed (`items` in [logging.md](logging.md)), so give it to the loop over the things the flow processes (requests, invoices, rows), not to loops that only pick options.

---

## 4. Complete Reference Example

Below is the complete `flow.md` specification for the **RPA Challenge Solver** benchmark:

```markdown
# RPA Challenge Solver
> Description: Self-Contained Project Bundle: Automate filling RPA Challenge form (10 rounds, 70 fields) from local bundle assets.
> Version: 1.0.0

## Variables
- `non_programmers`: []

## Steps

### 1. Open RPA Challenge Webpage (`web.open`)
- **url:** `${config.website}`
- **headless:** false

### 2. Read Challenge Excel File (`excel.read`)
- **file_path:** `${config.excel_path}`
- **clean_headers:** true
- **output_var:** `challenge_data`

### 3. Click START Button to Begin Timer (`web.click`)
- **selector:** `button:has-text('Start')`

### 4. Loop Through 10 Rows and Process Roles (`logic.loop`)
- **items:** `${challenge_data}`
- **item_var:** `row`
- **Sub-steps:**
  - Check If Role in Company is Programmer (`logic.if`):
    - **condition:** `${row.Role in Company} == 'Programmer'`
    - **Sub-steps:**
      - Fill First Name (`web.type`):
        - **selector:** `//input[@ng-reflect-name="labelFirstName"]`
        - **text:** `${row.First Name}`
      - Fill Last Name (`web.type`):
        - **selector:** `//input[@ng-reflect-name="labelLastName"]`
        - **text:** `${row.Last Name}`
    - **Else-steps:**
      - Record Non-Programmer Person (`logic.append`):
        - **target:** non_programmers
        - **item:** `{"First Name": "${row.First Name}", "Role in Company": "${row.Role in Company}"}`
  - Click Round Submit Button (`web.click`):
    - **selector:** `input[value="Submit"]`

### 5. Take Screenshot of Result (`web.screenshot`)
- **path:** `${config.screenshot_path}`

### 6. Close Browser (`web.close`)
```

---

## 5. Checking and Inspecting a Flow

1. **Validation of actions and parameters:**
   ```bash
   kinenix validate flows/examples/rpachallenge          # exit code 4 when problems are found
   ```
   Each action declares the parameters it reads. `kinenix validate`, `kinenix run`, and `kinenix-worker run` report unknown actions, parameters that no action reads (which would otherwise be ignored silently), lines the parser ignores, step headings without an action, and a flow without steps, and suggest the closest name (for example `timout` -> `timeout`). They also follow `flow.call` targets into subflows. `run` only warns, except that a flow without steps does not run. The `kinenix-core` test suite validates every flow under `flows/` and every example in `docs/`.
2. **Compiled form (for inspection):**
   ```bash
   kinenix compile flows/examples/rpachallenge                     # print the compiled flow as JSON
   kinenix compile flows/examples/rpachallenge -o /tmp/flow.json   # or write it to a file
   kinenix compile flows/examples/rpachallenge --strict            # also exit 1 when validation finds problems
   ```
   The result is validated against `kinenix.models.flow.FlowDefinition`; parsing errors name the line.
3. **Converting an old JSON flow (once):**
   ```bash
   kinenix export-md path/to/old_bundle      # writes flow.md next to the old flow.json
   ```

---

## 6. AI Prompting Template for Generating `flow.md`

When prompting an LLM or Small Language Model (SLM) to generate a new workflow, provide this system prompt:

```text
You are an expert RPA workflow architect for kinenix.
Generate a valid flow specification adhering strictly to the Flow Markdown Specification rules:
1. Title with Level 1 Heading (# Flow Name).
2. Level 3 Heading for each step with explicit action anchor: ### Step Name (`action.name`).
3. Parameters formatted as bullet points: - **param_name:** value.
4. Output variable formatted as: - **output_var:** var_name.
5. Indented sub-steps under - **Sub-steps:** for loops and conditions.
Only output the raw Markdown content.
```
