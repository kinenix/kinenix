# Changelog

`kinenix`, `kinenix-hub`, and `kinenix-worker` are released together with one version. How to release: [docs/releasing.md](docs/releasing.md).

## 1.0.1 (2026-11-11)

Fixes for 1.0.0, found in its soak on a Raspberry Pi and in the issues left from the release candidates. Nothing changes for flows. Upgrade all three packages together: kinenix-hub 1.0.1 needs kinenix 1.0.1.

### Added

- `"run_at_start": false` on an interval scheduler in `triggers.json` waits one interval before the first run, so restarting the worker does not run the flow again (#171). Without it, an interval scheduler still runs once when the daemon starts.

### Fixed

- `kinenix-worker daemon` did not log which triggers it started or when each one fired, so `journalctl` could not show the schedule (#156). `watch`, `schedule`, and `daemon` now log each trigger at start, with its next run, and each firing, in the same format as a run; `KINENIX_WORKER_LOG_LEVEL=WARNING` keeps them quiet.
- The Hub answered HTTP 500 "database is locked" now and then when a heartbeat and a run from the same worker arrived together, so the worker reported a failed send for a run that was stored (#201). Writes to a SQLite `hub.db` now take the write lock at their start and wait for each other, the failure analysis no longer holds the lock while the central LLM answers, and a failed update of the worker's status after a run is stored is logged instead of answered with an error.
- A bundle's `.env` read `export NAME=value` as a variable named `export NAME`, and kept ` # note` after a value as part of it (#171). One reader now handles `.env` and the settings files in `~/.kinenix`: `export` is accepted, a value in quotes is taken as written, and in `.env` a `#` after a space or tab starts a comment.
- The Hub suggested `ai_match: true` for any selector that was not found, but only `web.select_option` accepts it (#171).

## 1.0.0 (2026-11-10)

The stable core. From this version, the `flow.md` format, action names and parameters, CLI commands, exit codes, the log format, and the Hub's API and views stay compatible for all of 1.x ([docs/compatibility.md](docs/compatibility.md)). It is 1.0.0rc4 after a 24-hour soak on a Raspberry Pi and an install as a new Linux user, with the changes below.

### Upgrading from 0.2.0b4

The notes of each release since 0.2.0b4, in one place. The release notes below have the details.

- **Python 3.12 or newer** (1.0.0rc1). On 3.10 or 3.11, pip keeps installing 0.5.0b1: create a new virtual environment with Python 3.12 or newer first.
- **Back up `hub.db` before the first start of the new Hub;** it adds columns. A `hub.db` from Hub 0.2.0b3 or older that holds runs must be started once with Hub 1.0.0rc2 first ([docs/hub.md](docs/hub.md), section 6.1).
- **Upgrade every worker before deploying flows that use newer features,** and add `> Requires: kinenix>=1.0.0` to them; older versions run expressions and `on_error: next_item` wrongly without an error.
- **Exit codes:** 0 success, 1 technical failure, 2 wrong use, 3 business rule, 4 invalid flow, 5 newer Kinenix needed, 6 Hub unreachable, 7 not found, 8 partial run (finished with failed items or steps), 130 stopped. A script that treats every code other than 0 as a failure now also stops on partial runs.
- **Output:** the first line of `kinenix run` is `Run <run_id>`. Logs go to the flow's project folder (or the git repository that holds it), not the current folder.
- **Conditions** compare numbers as numbers, so `0012` without quotes also matches `12`: quote codes, as in `${branch} == '0012'`. A comparison with an empty or non-number side, and parentheses that group a condition, stop the run with exit code 4.
- **Values in text** read `1200`, `true`, and JSON instead of Python's `1200.0`, `True`, and list format.
- **`http.request`** fails on status 400 or higher; add `fail_on_error: false` to a step that checks `status_code` itself. **`round()`** rounds halves away from zero, like Excel.
- **`kinenix validate`** ends with exit code 4 when `on_error`, `max_retries`, or `retry_interval` is on `logic.if`, `logic.loop`, or `flow.return`; move them to the steps inside.
- **Subflows:** a parent flow continues on the page its subflow left (`propagate_sessions: false` keeps the old behavior), and a `flow.call` to `./` or `../` must name a file in the bundle.
- **Stopping a run:** Ctrl+C or `systemctl stop` ends the current step and runs `## Finally`; press Ctrl+C twice to stop at once.
- **A Hub without a key or password** answers only requests addressed to the machine itself; open the dashboard as `http://localhost:8080`.
- **Deprecated** and removed in 2.0: `on_error: retry`, `fallback_step_id`, `kinenix export-md`, and the Orchestrator names. They warn when used.

### Changed

- **The RPA Challenge examples moved to [kinenix/examples](https://github.com/kinenix/examples):** `rpachallenge` and `rpachallenge_ocr` need a third-party website, so they cannot run offline in CI with Kinenix. `kinenix init --example rpachallenge` no longer exists; clone kinenix/examples instead. The Excel file of the challenge is no longer shipped: the flow downloads it from the website when it runs, and it now fills the form for all ten people.

### Fixed

- A project made with `kinenix init` had no `> Requires:` line, so `kinenix validate` reported a problem as soon as the flow used `## Finally`, expressions, or `on_error: next_item` (#196). The new `flow.md` names the Kinenix version that made it.
- The link from `flow_markdown_spec.md` to the error handling section of `actions_reference.md` was broken on the website.

### Documentation

- `docs/examples.md`: how fast the engine is on a Raspberry Pi 4 and a laptop, with the flow that measures it.
- `kinenix-worker/README.md`: the systemd unit to write for a worker installed with pip, until #153.
- `docs/roadmap.md`: the releases after 1.0.0 as their milestones are now; the agent interface moved from 1.1.0 to 1.5.0.

## 1.0.0rc4 (2026-11-09)

The last fix planned for 1.0.0. Upgrading from 1.0.0rc3: read the note marked Upgrading below. Upgrading from 1.0.0rc2 or older: read the notes of 1.0.0rc3 too.

### Changed

- **A stopped run ends cleanly (#166):** Ctrl+C, `systemctl stop`, and `systemctl restart` used to end a run at once, with no `## Finally`, no final log, and nothing on the Hub. Now the current step ends, the remaining steps are skipped, `## Finally` runs, the log ends with `_interrupted.json`, and the Hub shows the status `interrupted`, which is not a failure. `## On Error` does not run. The exit code is 130, now also for SIGTERM. A second signal stops at once, and `kinenix-worker daemon` waits up to 60 seconds for running flows. Upgrading: Ctrl+C no longer stops at once; press it twice for that.

## 1.0.0rc3 (2026-11-06)

Fixes from a review of 1.0.0rc2. Many of them change behavior that stays the same for all of 1.x, so they come before 1.0.0, and some flows need a small change: read the notes marked Upgrading below. Before upgrading a Hub, back up `hub.db`; the first start adds a column. `## Finally` when a run is stopped (#166) is not in this release.

### Changed

- **Exit code 8 for partial runs (#172):** a run that finishes with failed items or steps (`on_error: continue` or `next_item`) now ends with 8 instead of 0, so a scheduler, a CI job, or an AI agent can tell it from a run where everything worked, also without a Hub. A script that treats every code other than 0 as a failure now stops on these runs; check for 8 if failed items are expected.
- `kinenix-worker run` shows these runs as `PARTIAL`, the console summary has a `Result: PARTIAL` line, and their log file ends with `_partial.json` instead of `_success.json`.

- **Conditions compare numbers as numbers (#160):** `==` and `!=` treat `100`, `100.0`, and `100.00` as equal, and `>`, `>=`, `<`, `<=` read `1,200` and `฿1200`. A side in quotes compares as text, so write codes as `${branch} == '0012'`. Upgrading: a flow that compares codes such as `0012` without quotes now also matches `12`.
- **A condition that cannot compare numbers stops the run (#160):** `>`, `>=`, `<`, `<=` with an empty side or other text were false without a warning, so `not ${missing} > 5` was true and a rule such as `flow.fail` never fired. The run now stops with exit code 4 and says which value is the problem. Upgrading: check a value that may be empty first, as in `${amount} is not empty and ${amount} > 0`.
- **Parentheses that group a condition are reported (#161):** `(${a} == 1 or ${b} == 2) and ${c} == 3` was split wrongly and gave the wrong result. `kinenix validate` and the run now report it; a value such as `Acme (Thailand)` is fine.

- **`http.request` fails on HTTP errors (#163):** a response with status 400 or higher now fails the step, so a server error no longer passes as a success. Upgrading: a flow that checks `status_code` itself needs `fail_on_error: false`.
- **`round()` rounds like Excel (#164):** halves go away from zero, on the number as written, so `round(2.5)` is 3 and `round(2.675, 2)` is 2.68. They were 2 and 2.67.

- **Values inside text no longer use Python's format (#174):** `Total: ${x}` gives `1200` for 1200.0, `Flag: ${x}` gives `true`, and a list or object gives JSON, in emails, files, and messages. A value alone keeps its type. Upgrading: text that depends on `True`, `False`, or Python's list format changes.

- **`kinenix validate` reports error keys that have no effect (#168):** `on_error`, `max_retries`, and `retry_interval` on `logic.if`, `logic.loop`, and `flow.return` were ignored without a warning, so a run stopped where the author expected it to go on. Upgrading: `kinenix validate` now ends with exit code 4 for such a flow; move the keys to the steps inside the block. The run itself behaves as before and prints the same problem.

### Fixed

- A null or out-of-range score from the central LLM, or a bad duration in telemetry, returned HTTP 500 and lost the run, and a score of 92 showed as 9200% (#169). The Hub now falls back to rule-based triage and keeps the run. Thanks to @mikemikimike.
- A run sent to the Hub twice was stored twice (#165). The Hub now keeps one record for each `run_id` of a worker and answers a repeat with that record, which also makes it safe to send a run again. `executions` has a new `run_id` column, filled in at the first start of the new Hub; rows that already share a run id are kept. Upgrading: a `hub.db` from Hub 0.2.0b3 or older that holds runs must be started once with Hub 1.0.0rc2 first ([docs/hub.md](docs/hub.md), section 6.1).
- `http.request` sent an empty body for a list payload; a list is now sent as JSON (#163).
- `number('.5')` gave 5; it now gives 0.5 (#164).
- An apostrophe in a value, such as `don't`, was read as the start of quoted text, which hid an `and` or `or` after it (#161).
- `output_var` kept the previous loop item's value when an action returned nothing or a step failed with `on_error: continue` or `next_item`, so the next steps used the wrong item's data without an error (#159). It is now empty; a step skipped by its `condition` still leaves it as it was.
- A `flow.call` that succeeded on a retry was counted as a failed item and failed steps, so the run showed as partial (#167). Only the last attempt now counts, as for any other step, and the step's `retries` says how many it took.
- Every value in a bundle's `.env` was hidden in logs and on the Hub, so `REGION=sales` turned a flow named `sales report` into `**** report` and broke `--flow` filters (#170). A `.env` value is now hidden when its name looks secret or the flow reads it, and `flow_name` is never changed. Values read inside expressions, such as `${upper(env.NAME)}`, are now found too.

## 1.0.0rc2 (2026-11-02)

Fixes found while testing 1.0.0rc1, which was published only on TestPyPI. Upgrading from 0.5.0b1: read the notes of 1.0.0rc1 below; they apply to 1.0.0rc2.

### Fixed

- A loop whose `item_label` calculates with the loop variable, such as `${row_index + 1}`, stopped the run before its first item; a step whose `condition` was false still evaluated its parameters, so the condition could not guard an expression such as `${total + 1}` (#145).
- Logs were written to `logs/` of the folder a command was started from when the flow was not in a git repository, so `kinenix run demo` from the home folder left `~/logs` behind. They now go to the flow's project folder (or the git repository that holds it), for `kinenix run` and `kinenix-worker`; a `--sandbox` run logs next to the original bundle.
- A constant in `connect.py` that holds the name of the key setting was taken for a secret by CodeQL; renamed.

## 1.0.0rc1 (2026-11-01, TestPyPI only)

The stable core: what stays the same for all of 1.x is written down in [docs/compatibility.md](docs/compatibility.md), commands end with exit codes that say what happened, and the code went through a threat model, a security review, and security checks in CI. Flows written for 0.5.0b1 run unchanged.

### Upgrading from 0.5.0b1

- **Python 3.12 or newer is required.** Python 3.10 reached its end of life in October 2026, and 3.12 is supported until October 2028, so 1.x does not start on a version that is about to end. On Python 3.10 or 3.11, `pip` keeps installing 0.5.0b1; install Python 3.12 or newer and create a new virtual environment before upgrading (Ubuntu 24.04 and Raspberry Pi OS based on Debian 13 already have it).
- **Exit codes:** a script or scheduler that treated every failure as 1 now gets a code that says why: 1 technical, 2 wrong use of the command, 3 a business rule (`flow.fail`), 4 an invalid flow, 5 a newer Kinenix needed, 6 the Hub cannot be reached, 7 not found, 130 Ctrl+C. Success is still 0, also when every failure was handled ([docs/cli_guide.md](docs/cli_guide.md#28-exit-codes)).
- **First line of `kinenix run`:** it is now `Run <run_id>`. A script that reads the output should skip it or use the id.
- **A Hub without a key or password** answers only requests addressed to `localhost`, `127.0.0.1`, or the machine's own name. Open the dashboard as `http://localhost:8080`.
- **`flow.call` with `./` or `../`:** the target must exist in the bundle. Before, a missing file was looked for in the current folder and among flows by name.
- **`kinenix-worker --sandbox`** deletes the `.env` files of its copy when the run ends; the flow's outputs in the copy stay.
- **Logs hide more:** values under names with `pin` or `otp` as a word (`BANK_PIN`), or with `passcode`.

### Added

- Exit codes with a meaning for `kinenix`, `kinenix hub`, and `kinenix-worker`, and `Run <run_id>` as the first line of `kinenix run`; `kinenix hub logs` accepts that run id, and the worker's result carries `exit_code` and `run_id` (#128).
- [docs/compatibility.md](docs/compatibility.md): what stays stable for all of 1.x, what may change, what is experimental, how deprecation works, and how to upgrade (#135).
- [docs/design/threat-model.md](docs/design/threat-model.md): what Kinenix protects, how the parts trust each other, twelve threats with their milestone, and the review findings (#137, #138).
- Security checks on every pull request and weekly: pip-audit, bandit, zizmor, and CodeQL; Dependabot keeps the pinned GitHub Actions current (#133).
- Failure-injection tests: a Hub that is down, slow, or answers with an error; a missing input file; a browser that dies in the middle of a loop. Each run finishes on its own, keeps its log, and leaves no browser process (#136).

### Security

- `SECURITY.md`: supported versions, and reporting a vulnerability privately through GitHub instead of a public issue.
- A Hub without a key or password could be read by a web page through DNS rebinding; it now checks the `Host` header on that path (#137).
- `--sandbox` copies kept the bundle's `.env` with its passwords forever (#137).
- `PIN`, `OTP`, and `PASSCODE` values reached logs and the Hub (#137).
- A missing `./subflows/...` target could run another flow that shared its path or name (#138).
- The release workflow passes the tag name through the environment instead of the script text, pins every action to a commit, and keeps no token on the runner (#133).
- Studio's frontend (not published) moves to vite 6.4 for known vulnerabilities in its development server (#134).

### Fixed

- A Hub that accepts the connection but does not answer was reported as a possible firewall; it now says the Hub may be busy or stuck (#136).
- `kinenix hub query` builds SQL only from table and view names that the database returns (#133).

### Deprecated

These still work in 1.x and warn when used; Kinenix 2.0 removes them.

- `on_error: retry`: it already works like `fail`. Delete the line; `max_retries` does the retrying.
- `fallback_step_id`: use `on_error: continue` and a next step with a `condition`, or `## On Error`.
- `kinenix export-md`: convert any `flow.json` from 0.2.0b3 or older with Kinenix 1.x.
- The Orchestrator names: `kinenix orchestrator`, `kinenix run --orchestrator`, the `ORCHESTRATOR_*` and `KINENIX_ORCHESTRATOR_*` variables, and `~/.kinenix/orchestrator.env` ([docs/hub.md](docs/hub.md), section 5).

`kinenix validate` prints the deprecated parts of a flow without failing, and every run logs them.

## 0.5.0b1 (2026-10-28)

Learn and test: a tutorial from requirements to a running flow, a business example, testing a flow against saved pages, and documentation for AI assistants.

Nothing changes for existing flows. A flow that uses `match: loose` on `web.choose`, or a page saved in its folder as the `url` of `web.open` or `web.goto`, should say `> Requires: kinenix>=0.5.0b1`: older versions do not know them.

### Learn

- A tutorial, `docs/tutorial.md` (https://www.kinenix.com/tutorial/): `kinenix init my-first-flow --example first_flow` gives a finished `requirements.md`, an empty `flow.md` for your AI assistant to build, a made-up shop's catalog saved in the project, and a solution; it goes through validate, run, and breaking the flow on purpose (#117).
- `quote_requests`, a business example: quote requests from a CSV entered into a made-up insurer's form, the packages collected, and the failed requests listed with their reasons, offline.
- `docs/examples.md`: every example and the patterns it shows. Every example has the `requirements.md` it implements.
- `llms.txt` for AI assistants, served as https://www.kinenix.com/llms.txt (#119).

### Flows

- Test a flow against saved pages: `kinenix run FLOW --config config/test.json` replaces settings for one run, and `web.open` and `web.goto` open a page saved in the flow's folder, such as `tests/pages/form.html` (#106).
- `web.choose` with `match: loose` ignores spaces, hyphens, and case (`HRV` picks `HR-V`); several loose matches fail instead of guessing. `match: contains` replaces `exact: false`, which still works. `search_text` sets what is typed into the search box (#107).
- `kinenix validate` reports a `flow.json` or a subflow `.json` next to its `.md`; `kinenix init --update-agents` refreshes `AGENTS.md` and `CLAUDE.md` of an older project from the current template (#105).
- The `AGENTS.md` given to new projects teaches `on_error: next_item` in loops, the web actions of 0.4.0b1, cookie banners and menus, resetting a subflow's result before each call, and testing against saved pages.

### Also

- `kinenix init --example` also copies `.env.example`, input files, saved test pages, and a tutorial's solution; `kinenix list` no longer lists a `solution` folder as a flow.
- CI runs the offline examples end to end in Chromium, with their outputs checked.

## 0.4.0b1 (2026-10-23)

Web actions: modern pages (cards instead of tables, custom dropdowns, paged tables, single-page apps) in one step each.

**A parent flow now continues on the page its subflow left** (a page the subflow went to, switched to, or opened). Before, it kept its own page. Set `propagate_sessions: false` on the `flow.call` to keep the old behavior. **Add `> Requires: kinenix>=0.4.0b1` to a flow that uses `on_error: next_item`** (`kinenix validate` says when): Kinenix 0.3.0b1 and older stop the flow at that step.

### Web

- `web.goto` goes to a URL in the current tab, and opens a browser when none is open (#58).
- `web.choose` picks an option by name in custom dropdowns (Radix and shadcn Select, cmdk combobox, Headless UI, MUI) or a native `<select>`, optionally typing into its search box. A missing option fails with the list of options that are there (#57).
- `web.get_list` reads repeated elements such as cards into rows, with `fields` (text, `@attribute`, or the element itself), `numeric_fields`, `required_fields`, `add_columns`, and `min_rows` (#55).
- `web.get_table` and `web.get_list` read every page of a paged table or list with `next_selector`; more pages than `max_pages` fails instead of leaving pages out.
- A browser a subflow opened is closed at the end of the run; a subflow with `propagate_sessions: false` uses its own browser, which is closed when it ends.
- A failed web step says in one line what went wrong and how to fix it, instead of only Playwright's call log: what covered the element (named as a cookie banner, popup, or menu when it looks like one), a selector that never appeared or matches several elements, a hidden or disabled element, a site that could not be reached. A failed subflow passes its step's cause up to the caller. No AI is involved; unknown messages keep the general wording (#111).

### Flows

- `on_error: next_item` for steps inside a `logic.loop`: the failure is recorded, the rest of the item is skipped, and the loop goes on with its next item. The item counts as failed (#102).
- A value with a leading zero, such as `0012`, stays text. `kinenix validate` reports a `{...}` or `[...]` value that is not valid JSON, which would be read as text (#103).
- A run that succeeds no longer carries `failure_details` from a failure handled by `on_error: continue` (#102).

### Hub

- A run that finished, but with failed work items or failures it went on after, is **partial** instead of success: an amber "สำเร็จบางส่วน · 1 จาก 2 รายการไม่สำเร็จ" on the dashboard, with a filter, and `partial` in `hub status`, `logs`, `report`, and `hub query`. Runs already stored are updated when the Hub starts (#110).
- The steps view and `kinenix hub logs` show a failed step's cause, how to fix it, and the work item it failed on; the full message is one click away.
- The startup banner shows the dashboard's LAN address when other machines may log in; `http://127.0.0.1:8080` opened over ssh is the viewer's own machine.

### Also

- `kinenix list` names a flow by its folder also when run inside it (it showed `.`), and no longer lists the old flat flows from `kinenix-core/examples`, which were removed (#108).
- `PWD` and `OLDPWD` are no longer hidden as secrets, so paths in logs stay readable on Linux and macOS (#101).
- Every action declares what it can do outside the run (`email`, `files`, `web`, `network`); `kinenix actions` shows it.
- CI runs the browser tests in Chromium on Linux and Windows.

## 0.3.0b1 (2026-10-16)

Expressions: count, join, clean, pick, and calculate values inside `${...}`, safely. Design: [docs/design/expressions.md](docs/design/expressions.md).

**Add `> Requires: kinenix>=0.3.0b1` to a flow that uses expressions or `and` / `or` / `not`** (`kinenix validate` says when). Kinenix 0.2.0b4 and older turn `${len(rows)}` into empty text and read `and` as part of a value, without an error. Upgrade every worker first.

### Flows

- Functions in `${...}`: `len`, `join`, `number`, `trim`, `lower`, `upper`, `replace`, `default`, `round`, `part`, `substring`; `+ - * / %` on numbers; indexing such as `${rows[0].id}` and `${row['Unit Price (THB)']}` (#56).
- Conditions join comparisons with `and`, `or`, and `not`; a value such as `Johnson and Johnson` is not split.
- Nothing written in a flow can run code: expressions are parsed and checked against a fixed list, without `eval`. `${x.__class__}`, which read Python internals before, now gives empty.
- A variable that exists is read as before, so keys such as `First Name` or `Role in Company` keep working. A missing key written with clear expression syntax (a function call, brackets, quotes, or `+ * / % < > = !`) now reports an error instead of giving empty.
- `kinenix validate` reports expression errors and unknown functions with their line.

### Also

- When a run cannot reach the Hub, the log says why in plain words (name not found, Hub not running, firewall), as `kinenix connect` does.
- The copyright owner is named in every LICENSE and NOTICE file.
- www.kinenix.com is rebuilt when the documentation on `main` changes.

## 0.2.0b4 (2026-10-16)

Phase 2: subflows, error handling, and run records that people and AI can query.

**Upgrade every worker before you deploy a flow that uses `## On Error` or `## Finally`.** Kinenix 0.2.0b3 and older read the steps under those headings as ordinary steps, so an older worker would, for example, send the error e-mail on every successful run. Add `> Requires: kinenix>=0.2.0b4` under a flow's title; 0.2.0b4 and newer refuse a flow that needs a newer version. Upgrading: [docs/releasing.md, section 3](docs/releasing.md#3-upgrading-an-installation).

### Flows

- `## On Error` and `## Finally` sections, `${error}` (message, step, path, subflow, line, loop item, retries, root cause, screenshot), and `${run}` (id, flow, started, status, log path) (#50, #51).
- `max_retries` always retries first; `on_error: continue` then records the failure and goes on; `max_retries`, `retry_interval`, and `config.error_dir` accept `${...}` (#52).
- `logic.loop` takes `item_label`, which names each item in logs and on the Hub and counts work items.
- Subflows are written as `.md`, share the bundle's config and folder (`@shared/` subflows keep their own unless `inherit_config: true`), and `kinenix validate` follows them (#49, #60).
- `> Requires: kinenix>=VERSION` under a flow's title.

### Run records

- One record per run: every step, including subflow steps, with its line, path, subflow, loop item, retries, and for failures how they were handled (`stopped`, `continued`, `fallback`). Subflows no longer write their own logs or send their own runs (#62).
- A live log (`.jsonl`) written while the flow runs, available as `${run.log_path}`; one screenshot per failure (#54).
- Secrets and personal data are redacted on the worker before logs, `${error}`, and the Hub.

### Hub

- Tables `step_results` and `failures`, `executions.details` with a Markdown run report, views `v_runs`, `v_failures`, and `v_steps`, and a data dictionary ([docs/hub_data.md](docs/hub_data.md)). An existing `hub.db` is upgraded in place, and its runs get their records at the first start.
- `kinenix hub query` (read-only questions, on the Hub machine or with `--url`), user views from `~/.kinenix/hub_views/`, `kinenix hub report --flow NAME`, and `kinenix hub logs --flow NAME`.
- `kinenix connect URL` saves the Hub a machine reports to, after checking the key; `kinenix hub setup` offers it for runs on the Hub machine.
- Failure summaries name a Business error as a business rule that was not met, and report an unrecognized error as unknown instead of guessing.

### Also

- License changed to Apache-2.0.
- The repository is now `arttopix/kinenix`.
