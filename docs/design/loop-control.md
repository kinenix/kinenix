# Design: Stopping a loop early, and loops without a list (1.1.0)

Status: **approved** (2026-11-11). Milestone: [1.1.0: Flow data tools](https://github.com/kinenix/kinenix/milestone/8). Issue: #191. Related: #192 (error tolerance inside `web.get_list`, a separate change).

## 1. Goal

A flow can leave a loop as soon as its work is done, and repeat steps a number of times without a made-up list, so a page-by-page loop is as short as the task.

Found by an AI assistant building Example_extract_artbook ("if a page fails, go on with the next page"):

- It put `"max_pages": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]` in `config.json` only to have something to loop over.
- It kept a `has_more_pages` variable and wrapped every step of the loop in a `logic.if`, so when the last page was reached, the remaining iterations still ran as skipped steps and the run record counted them.

## 2. Before and after

Before:

```markdown
### 3. Each Page (`logic.loop`)
- **items:** ${config.max_pages}
- **item_var:** page
- **Sub-steps:**
  - While There Are Pages (`logic.if`):
    - **condition:** `${has_more_pages} == true`
    - **Sub-steps:**
      - Read The Books (`web.get_list`): ...
      - Is There A Next Page (`web.is_visible`): ...
      - No More Pages (`logic.set_variable`):
        - **condition:** `${next_visible} == false`
        - **name:** has_more_pages
        - **value:** false
      - Next Page (`web.click`): ...
```

After:

```markdown
> Requires: kinenix>=1.1.0

### 3. Each Page (`logic.loop`)
- **times:** ${config.max_pages}
- **item_var:** page
- **item_label:** Page ${page}
- **Sub-steps:**
  - Read The Books (`web.get_list`):
    - **on_error:** next_item
    ...
  - Is There A Next Page (`web.is_visible`):
    - **selector:** li.next a
    - **output_var:** next_visible
  - Last Page (`logic.break`):
    - **condition:** `${next_visible} == false`
  - Next Page (`web.click`):
    - **selector:** li.next a
```

`config.max_pages` is now a number (`10`), a limit rather than a list.

## 3. Decisions to make

| # | Topic | Options | Recommendation |
| :--- | :--- | :--- | :--- |
| C1 | Leaving a loop | (a) a `logic.break` action; (b) a `break_when` parameter on `logic.loop`, checked after each iteration | **Agreed: (a)**: it can stand anywhere in the loop, before or after the steps that should not run, and its `condition` is an ordinary step condition. It works in a loop over `items` and in a loop with `times` |
| C2 | Loops without a list | (a) `times: N` on `logic.loop`, instead of `items`; (b) a new `logic.while` action with a `condition` and `max_iterations`; (c) both | **Agreed: (a)**: with `logic.break`, "repeat until" is `times` plus a `logic.break` with a condition, so one loop action covers every case. `item_var` holds the iteration number, from 1 |
| C3 | Which loop `logic.break` leaves | (a) the innermost `logic.loop` of the same flow; (b) a loop named by the step | **Agreed: (a)**, as `on_error: next_item` does: only the innermost loop it is in. A subflow called inside a loop cannot leave the caller's loop; it returns a value and the caller's `logic.break` decides |
| C4 | Items not reached because of a break | (a) left out of the run's work items; (b) counted as done; (c) counted as failed | **Agreed: (a)**: a loop of 10 pages that ends on page 4 reports 4 items, not 10. With `times`, only iterations that start are items |
| C5 | A `times` loop that never breaks | (a) it simply ends after N; (b) it fails, because the end was not found | **Agreed: (a)**: `times` is a limit the author chose, and running out of it is not an error. Errors inside the loop are handled as anywhere else (`on_error`), and a flow that must find the end checks it itself, for example with `flow.fail` after the loop |
| C6 | `logic.next` (skip the rest of this item without a failure) | (a) add it now; (b) later, if a real flow needs it | **Agreed: (a)** (changed on 2026-11-11): `logic.break` and `logic.next` come together, as break and continue do in other tools. Without it, every remaining step of the item needs the same `condition`, or a `logic.if` around them. The item counts as done; a failure skips with `on_error: next_item` and counts as failed |

## 4. `logic.break`

| Parameter | Description |
| :--- | :--- |
| (none) | Leaves the innermost `logic.loop` now: the remaining steps of this iteration are skipped, and no further iteration starts. The flow goes on with the step after the loop |

- Any step may have a `condition`; on `logic.break` it says when to leave. Without one, it always leaves.
- In the run record the step is a success with the output `{"status": "loop stopped"}`, and the loop step's output says `"stopped_early": true` and how many iterations ran.
- Outside a loop it is an error: `kinenix validate` reports it, and a run stops at it with exit code 4, as an invalid flow.
- `on_error`, `max_retries`, and `error_message` have no effect on it; `kinenix validate` says so (#168).
- In `## On Error` and `## Finally`, it leaves a loop in that section the same way.

## 4.1 `logic.next`

Skips the rest of this iteration of the innermost `logic.loop` and goes on with the next item. It has no parameters; a `condition` says when. The item counts as done, unless a step of it failed earlier. Everything else is as for `logic.break`: only a loop of its own flow, an error outside a loop, and no effect of `on_error`.

```markdown
  - Skip Out Of Stock (`logic.next`):
    - **condition:** `${book.availability} contains Out of stock`
```

## 5. `times` on `logic.loop`

| Parameter | Description |
| :--- | :--- |
| `times` | A whole number from 0 to 10,000, or `${...}`: how many iterations to run, instead of `items`. `item_var` (default `item`) holds 1, 2, 3, ... and `${item_index}` holds 0, 1, 2, ... as for a list |

- A loop has `items` or `times`, not both; both, or neither, is an error that `kinenix validate` reports.
- `times` that is not a whole number, or is below 0 or above 10,000, stops the step and says which.
- `item_label` works as for a list: `Page ${page}`.

## 6. Compatibility

- Additions only. `logic.loop` with `items` behaves as before, except that a `logic.break` inside it now has an effect.
- An older Kinenix does not know `logic.break` and stops with "unknown action". It reads a loop with `times` and no `items` as a loop over nothing, without a warning, so both need `> Requires: kinenix>=1.1.0`; `kinenix validate` asks for it.
- `docs/compatibility.md`: `logic.break` and `times` join the 1.x promise when 1.1.0 is released.

## 7. Implementation

- `actions/logic.py`: `logic.break` (raises an internal signal, like `_NextItem`), and `times` in `logic.loop`'s `accepted_parameters`.
- `engine/interpreter.py`: `_handle_loop_step` builds the iterations from `items` or `times`, catches the break signal for its own loop, counts only the iterations that started, and records `stopped_early`.
- `engine/validation.py`: `logic.break` outside a loop, `items` with `times`, and both features in the newer-features list.
- Docs: `docs/actions_reference.md` (`logic.loop`, `logic.break`), `docs/flow_markdown_spec.md`, the new-project `AGENTS.md`, and the CHANGELOG.

## 8. Tests

- `times` with a number, `${...}`, 0, and invalid values; `item_var` and `item_index`.
- `logic.break` with and without a condition, at the start, middle, and end of an iteration; in nested loops (only the inner loop ends); in On Error and Finally.
- Work items after a break: 10 pages, break on 4, the run reports 4 done.
- `logic.break` outside a loop, and in a subflow called inside a loop, report and stop.
- The page loop of section 2 against saved pages (`tests/pages`), run with Chromium in CI.

## 9. Out of scope

`logic.while`; error tolerance inside `web.get_list` and `web.get_table` (#192, a separate change).
