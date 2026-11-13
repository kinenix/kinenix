# Instructions for AI assistants: {{title}}

This folder is a Kinenix flow project. Kinenix runs automation flows written in Markdown (`flow.md`). Your job is to turn the requirements in `requirements.md` into a working `flow.md`.

## Workflow

1. Read `requirements.md`. If something needed to build the flow is missing or ambiguous, ask the user before writing it.
2. Write `flow.md` following the Flow Markdown specification. `flow.md` is the only flow file; do not create a `flow.json`.
3. Put every value the requirements say must be changeable (URLs, lists, dates, paths, recipients) in `config/config.json` and read it as `${config.name}`.
4. Put secrets (passwords, API keys, tokens) only in `.env` (see `.env.example`) and read them as `${env.NAME}`. Never write a secret in `flow.md` or `config/config.json`.
5. List in `"redact"` in `config/config.json` every field that holds personal or confidential data (names, ID numbers, policy or account numbers, addresses), so it is hidden in logs and on the Hub. Add `- **secret:** true` to a `web.type` that types a secret into a field that is not a password field.
6. Run `kinenix validate .` and fix every reported problem.
7. Run `kinenix run .`, read the log, and fix failures. Report what you verified.

When the requirements say what to do if the bot fails (send an e-mail, take a screenshot) or what must always happen at the end (close the browser, zip the output), put those steps in `## On Error` and `## Finally` after `## Steps`, use `${error.message}`, `${error.step_name}`, and `${error.loop.item}` in them, and add the `> Requires: kinenix>=...` line under the title that `kinenix validate` asks for. `validate` cannot see every new feature (for example a page saved in the project used as a `url` from `config.json`); when the flow uses something added recently, require the installed version (`kinenix --version`). Give every `logic.loop` an `item_label` that identifies the item, such as an order number.

## References

| Need | Where |
| :--- | :--- |
| Every action and the exact parameters it accepts | Run `kinenix actions` (or `kinenix actions web` for one group) |
| `flow.md` syntax: steps, parameters, loops, conditions, error handling | https://github.com/kinenix/kinenix/blob/main/docs/flow_markdown_spec.md |
| Action details and examples | https://github.com/kinenix/kinenix/blob/main/docs/actions_reference.md |
| Project layout, config, `.env`, subflows | https://github.com/kinenix/kinenix/blob/main/docs/project_bundles.md |
| Sending runs to a Hub, and why a run does not appear there | https://github.com/kinenix/kinenix/blob/main/docs/hub.md#8-how-machines-connect-and-troubleshooting |
| Complete working examples | `kinenix init --list`, then for example `kinenix init --example bot_fx_rate` in another folder |

## Rules

- **Web pages:** open the real page before choosing selectors; do not guess them. Prefer selectors based on visible text, labels, roles, or stable attributes over long CSS or XPath paths. If a page shows customer or other business data, ask the user to pick the selectors instead of sending the page content to a cloud service.
- **Web actions to prefer:** `web.goto` to return to a page in the same tab (in loops and subflows, instead of `web.open` every time); `web.choose` for dropdowns, including custom ones that are not a `<select>`; `web.get_list` for cards or repeated items and `web.get_table` for tables, with `next_selector` when they have several pages, and `on_item_error: skip` (Kinenix 1.1.0) when a few items may lack a field and the rest should still be kept. Cookie banners and menus often cover buttons: accept the banner (`web.click` with `optional: true`) and move the mouse off a menu before clicking under it.
- **Errors:** add `max_retries` (and `retry_interval` in seconds) to steps that touch the network or files. Put `on_error` and `max_retries` on the step that may fail, never on `logic.if`, `logic.loop`, or `flow.return`. In a loop, `on_error: next_item` gives up on the current item and goes on with the next one; `on_error: continue` goes on with the next step of the same item but still counts the failure (the run ends as partial). For a step whose failure does not matter, such as closing a popup that may not be there, use `on_error: ignore` (Kinenix 1.1.0). When the requirements ask for a message on a failure ("if the site cannot be opened, say so"), put `error_message` on that step, for example `- **error_message:** เปิดเว็บไม่ได้: ${error.message}`, instead of adding a `flow.fail` step. Stop on business problems (no data, invalid input) with a `flow.fail` step and a clear message. When a subflow returns a result through `output_var`, reset that variable before each call: a failed call does not set it.
- **Test before production:** for a web flow, save the pages it uses under `tests/pages/`, put a `config/test.json` that points the URLs to them (for example `"website_url": "tests/pages/quote.html"`), and run `kinenix run . --config config/test.json`. See "Testing against saved pages" in the project layout reference. For a site built with JavaScript (React, Vue) see rule 5 under Batch flows.
- **Text with several lines** (an email body, a message): write `- **body:** |` and indent the lines below it. Lines that are not indented are ignored, and `kinenix validate` reports them.
- **Conditions:** write them as a sentence, for example `${row.note} is empty`, `${brand} in ${config.brands}`, `${label} contains 5,000`, and join them with `and`, `or`, `not`. Parentheses cannot group conditions. Quote a value that is a code, such as `${branch} == '0012'`, so it compares as text; check a value that may be empty first, as in `${amount} is not empty and ${amount} > 0`. The operators are listed in the specification under Conditions.
- **Values:** count, join, clean, pick, and calculate inside `${...}` with the expression functions in the specification (`len`, `join`, `number`, `trim`, `replace`, `default`, `round`, `part`, `substring`, ...) and `+ - * /`, for example `${len(rows)}` or `${number(row.price) * 12}`, instead of extra steps.
- **Loops (Kinenix 1.1.0 and newer):** to repeat until something is found, such as reading page after page until there is no next page, use `logic.loop` with `times` as the most iterations (`- **times:** ${config.max_pages}`) and a `logic.break` step with a `condition` where the loop should end. Do not build a list such as `[1, 2, 3, ...]` only to loop over it, and do not wrap the loop's steps in a `logic.if` on a flag. To skip an item that does not need work (for example a book that is out of stock), put `logic.next` with a `condition` before its steps.
- **Lists (Kinenix 1.1.0 and newer):** sort, filter, count, and add up rows without a loop: `${sort_by(rows, 'category', '-price')}`, `${where(rows, 'price', '<', 20)}`, `${len(where(...))}`, `${sum(rows, 'amount')}`. Set true/false or either-or values without `logic.if`: `${price < 20}`, `${ifelse(qty > 0, 'In stock', 'Sold out')}`. Use `text(x)` to compare codes such as `0012` as text. Add `> Requires: kinenix>=1.1.0` when you use them.
- **Results:** write outputs under `output/`, which is not committed, in a folder of their own for each run (rule 1 under Batch flows).
- **Keep data local:** do not send flow data to third-party services unless the requirements ask for it.
- Keep `flow.md` readable: one action per step, descriptive step names.

## Batch flows

A flow that loops over many items (rows, requests, pages) runs unattended, and people judge it only by its files, e-mails, and the Hub. Follow these five rules; the reasons and longer examples are in https://github.com/kinenix/kinenix/blob/main/docs/batch_flows.md.

1. **Every file in `output/` belongs to this run.** Write to `./output/${run.id}/`, or delete `./output` as the first step (`file.delete`) when names must stay fixed. Write result files even when they have no rows (`csv.write` with `columns` writes the header), so no old file is mistaken for today's:
   ```markdown
   - **file_path:** ./output/${run.id}/packages.csv
   ```
2. **One bad item does not stop the batch.** Give every step in the loop that can fail for one item `on_error: next_item`, or put the item's steps in a subflow called with `on_error: continue` and append the failed item to a list:
   ```markdown
     - Note The Failure (`logic.append`):
       - **condition:** `${quote_result.status} != ok`
       - **target:** `failed`
       - **item:** {"id": "${req.id}", "reason": "${default(error.root_cause, error.message)}"}
   ```
3. **A run that produced nothing is not a success.** After the loop, stop it with `flow.fail`:
   ```markdown
   ### 6. Stop When Nothing Was Found (`flow.fail`)
   - **condition:** `${len(packages)} == 0`
   - **message:** Nothing was found for ${len(requests)} requests.
   ```
4. **The completion message says what happened:** the counts and the failed items, never a fixed "completed successfully". Fill every list it uses.
   ```markdown
   - **subject:** Quotes: ${len(requests)} requests, ${len(failed)} failed
   - **body:** Failed: ${default(join(column(failed, 'id'), ', '), 'none')}
   ```
5. **Test pages for JavaScript sites are written, not saved.** A page saved from a React or Vue site loses its scripts, so its dropdowns never open. Write a small page with only the parts the flow touches, the same selectors (`data-testid`, labels, roles), and a few lines of script for the dropdowns and buttons it uses, as `kinenix init --example quote_requests` does in `tests/pages/quote.html`:
   ```html
   <div class="dropdown" data-testid="model"></div>  <!-- a script fills it with role="option" items on click -->
   ```

## Mistakes to avoid

These are the mistakes AI assistants make most often in `flow.md`; `kinenix validate` reports each of them.

- **The action goes in the step heading**, in backticks and parentheses: `### 3. Open Page (`web.open`)`. A heading without it is not a step.
- **Sub-steps** of `logic.loop` and `logic.if` are bullets under `- **Sub-steps:**`, each with its action, and their parameters are indented below:
  ```markdown
  - **Sub-steps:**
    - Tick Currency (`web.check`):
      - **selector:** `input[value='${currency}']`
  ```
- **Only the parameters an action accepts** (`kinenix actions <prefix>` lists them); `on_error`, `max_retries`, `retry_interval`, `error_message`, `output_var`, and `condition` belong to every step.
- **Every `${name}` is set somewhere**: in `## Variables`, `config/config.json`, an `output_var`, or a loop's `item_var`. A misspelled name is empty and the run goes on. Declare the variables the flow takes from `--vars` under `## Variables`, empty if they have no default. Read the `Hint:` lines of `kinenix validate` too: they are not errors, but each one says what to check.
