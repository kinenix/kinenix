# Roadmap

This is the single source for delivery status and priorities. Statuses reflect the code in the repository, not intentions. Architecture details live in [architecture.md](architecture.md).

Legend: `[x]` done, `[~]` partially done, `[ ]` not started.

---

## 0. Releases

Each GitHub milestone is one release and has the same title as its heading here. A milestone lists its issues; this section holds its goal, exit criteria, compatibility notes, and what is out of scope. Each open milestone also has a release checklist issue (label `release`) whose boxes are the exit criteria; the milestone closes when the checklist is done and the version is on PyPI.

Toward 1.0.0, a `flow.md` written for 1.0 keeps running on every 1.x version.

| Milestone | Goal | Due | Status |
| :--- | :--- | :--- | :--- |
| 0.2.0b3: Silent bugs and docs | No silent wrong results; documentation examples that work | 2026-10-10 | Released |
| 0.2.0b4: Subflows, error handling, and run records | Failures handled in one place and recorded as facts the Hub can answer questions from | 2026-10-16 | Released |
| 0.3.0b1: Expressions | Count, join, clean, and calculate values in `${...}`, safely | 2026-10-20 | Released |
| 0.4.0b1: Web actions | Modern web pages without multi-step workarounds | 2026-10-23 | Released |
| 0.5.0b1: Proven on business flows | A tutorial and a business example, run by CI with a real browser, and testing flows against saved pages | 2026-10-28 | Released |
| 1.0.0: Stable core | A core that can be trusted, with a written stability promise | 2026-11-10 | Released |
| 1.0.1: Fixes | Bugs found after 1.0.0: Hub writes that met (#201), `.env` parsing and interval triggers (#171), worker trigger logs (#156) | 2026-11-11 | Released |
| 1.1.0: Flow data tools | Fix what real flows written by AI assistants ran into: sorting, filtering, and totals on lists, shorter conditions, loops that stop early, clearer errors | After 1.0.0 | Planned |
| 1.2.0: Developer tools | See and check flows in the editor | After 1.1.0 | Planned |
| 1.3.0: Hardening and docs | Close the open findings of the threat model, a security guide, and the website organized by purpose | After 1.2.0 | Planned |
| 1.4.0: Daily results you can trust | Kinenix knows whether each day's work really succeeded: expected outputs, missed runs, schedules managed by command | After 1.3.0 | Planned |
| 1.5.0: Works with AI agents | AI agents use Kinenix like an employee: build a flow for a person to review, run the day's flows, and report what failed or did not run | After 1.4.0 | Planned |

### 0.2.0b3: Silent bugs and docs

**Goal:** a flow never does the wrong thing without a warning, and the documentation examples work as written. Released 2026-10-10.

**Scope:** #46, #47, #48, #53, #59, #61, #63 and the other issues of the milestone.

### 0.2.0b4: Subflows, error handling, and run records

**Goal:** a flow handles failures in one place (`## On Error`, `## Finally`), every run is recorded with complete failure facts, and the Hub answers "what failed, and where?". Released 2026-10-16. Design: [design/phase-2.md](design/phase-2.md). Changes: [CHANGELOG.md](../CHANGELOG.md).

**Scope:** #49, #50, #51, #52, #54, #60, #62.

### 0.3.0b1: Expressions

**Goal:** a flow can count, join, clean, and calculate values in `${...}` without workarounds, and nothing written in a flow can run code.

**Scope:** #56.

**Exit criteria**

Automated:
- [x] Functions `len`, `join`, `number`, `trim`, `lower`, `upper`, `replace`, `default`, `round`, `part`, `substring`; `+ - * / %` on numbers; indexing `rows[0]` and `row['name']`; each with tests, including bad input (design: docs/design/expressions.md)
- [x] Conditions combine comparisons with `and`, `or`, and `not`, and a value such as `Johnson and Johnson` is not split
- [x] `kinenix validate` reports expression syntax errors and unknown functions with their line
- [x] Unknown functions, attribute access such as `__class__`, and anything outside the list are refused with a clear message (security tests)
- [x] Fuzz test: thousands of random and malformed expressions never crash the parser, never hang, and never run code
- [x] Every existing example and test flow compiles and runs unchanged
- [x] All four test suites pass, and CI is green

Field test:
- [x] A demo flow with `len`, `join`, `number`, `part`, and `and` runs on the Raspberry Pi worker; the real insurance-quote flow is tested in 0.4.0b1 together with the new web actions

Docs and release:
- [x] `docs/flow_markdown_spec.md` documents every function with an example
- [x] CHANGELOG entry; TestPyPI checked; tag `v0.3.0b1`; PyPI checked

**Compatibility:** `${a.b}` and existing conditions behave as before. Text inside `${...}` that looks like a function call, such as `${len(x)}`, is now evaluated.

**Out of scope:** user-defined functions, loops, or lambdas in `${...}` (never, for safety); date arithmetic (stays in `date.calc`); regular expressions (1.1.0 if a real flow needs them).

### 0.4.0b1: Web actions

**Goal:** a flow works with modern web pages (cards instead of tables, custom dropdowns, single-page apps) in one step each, instead of multi-step workarounds.

**Scope:** #55 `web.get_list`, #57 `web.choose`, #58 `web.goto`, and reading paged tables and lists.

**Exit criteria**

Automated:
- [x] `web.goto` navigates the current tab; a page that a subflow opens or switches to is the parent's page afterwards, so screenshots show the right page
- [x] `web.choose` picks an option in a custom dropdown (with and without a search box) and, when the option is missing, lists the visible options in the error
- [x] `web.get_list` reads repeated elements into rows, with `fields`, `add_columns`, `numeric_fields`, `required_fields`, and `min_rows`
- [x] `web.get_table` and `web.get_list` read every page of a paged list or table: `next_selector` is clicked until it is disabled or gone, `max_pages` limits the pages, and the rows of all pages are returned in order
- [x] Each action has tests against local HTML pages (no internet), declares `accepted_parameters`, and passes `kinenix validate`
- [x] Agent-interface foundation ([design/agent-interface.md](design/agent-interface.md), section 10): every action declares its side-effect kind (`email`, `files`, `web`, `network`, `none`), the existing ones included; new commands keep their logic in functions that return data, and `cli.py` only parses and prints
- [x] All four test suites pass, and CI is green

Field test:
- [x] The real insurance-quote flow uses `web.goto`, `web.choose`, `web.get_list`, and expressions (`len`, `join`, `number` instead of its workarounds) and runs on the Raspberry Pi worker

Docs and release:
- [x] `docs/actions_reference.md` documents each action with a `flow.md` example
- [x] CHANGELOG entry; TestPyPI checked; tag `v0.4.0b1`; PyPI checked (released 2026-10-24)

**Compatibility:** new actions only. `web.open` still opens a new tab. A parent flow now sees the page its subflow left open (before, it kept its own page).

**Out of scope:** multi-select dropdowns (1.1.0); clearing cookies and storage on `web.goto` (`reset: true`), unless the field test needs it.

### 0.5.0b1: Proven on business flows

**Goal:** show and prove that Kinenix does real business work end to end. Each example is a complete project someone can copy and adapt, runs without internet against sample data and local pages, and is run by CI and on real machines for days. These examples are the gate that 1.0.0 must keep passing.

**Scope** (narrowed on 2026-10-26 to keep 1.0.0 on 2026-11-03): the first-flow tutorial (#117), one business example (`quote_requests`), and an end-to-end CI job with a real browser. From the 0.4.0b1 field test: #105 (leftover JSON flows, refreshing a project's AGENTS.md), #106 (testing a flow against saved pages with `kinenix run --config`), #107 (`web.choose` with `match: loose`), and #119 (`llms.txt`). The other two examples, the failure-injection tests, and the 48-hour soak moved to 1.0.0.

| Example | Story | Patterns it proves |
| :--- | :--- | :--- |
| `first_flow` (tutorial) | A made-up shop's catalog (saved pages) is read into CSV, and the products over a budget are listed. The project starts with `requirements.md` and an empty `flow.md`; the reader's AI assistant builds the flow, following `docs/tutorial.md` | The Kinenix way of working: requirements, assistant, `validate`, `run`, a failure read on purpose; `web.get_list` with paging, expressions, `flow.fail`, Finally |
| `quote_requests` | Requests from a CSV are entered one by one into a quote form (a local copy of a modern insurance site), the offered packages are read, and a results file plus a list of failed requests is e-mailed | subflow per item, `web.goto`, `web.choose`, `web.get_list`, `on_error: next_item`, `${error.loop.item}`, screenshots on failure |

**Exit criteria**

Examples:
- [x] `docs/tutorial.md` and the `first_flow` example: a reader with an AI assistant gets from `kinenix init --example first_flow` to a passing run and a failure read on purpose; tried with two different assistants (Claude Code and Google Antigravity; details in #88)
- [x] `quote_requests` has the `requirements.md` it was built from (a test checks every example has one), a README (the business story, input, output, how to run, how long it takes), fake sample data only, `> Requires:`, `redact` for personal fields, `## On Error` and `## Finally`, and passes `kinenix validate`
- [x] Both ship with the package (`kinenix init --example`) and appear in a new `docs/examples.md` that says which patterns each shows

Automated:
- [x] CI runs every offline example end to end in Chromium, headless, and checks its outputs (rows written, items failed); the tutorial's solution included (in the kinenix-core test suite: `test_tutorial.py`, `test_quote_requests_example.py`, and `hello` in `test_scaffold.py`)

Release:
- [x] CHANGELOG entry; TestPyPI checked; tag `v0.5.0b1`; PyPI checked; then the kinenix-web branch that links `llms.txt` is merged (released 2026-10-28)

**Compatibility:** nothing changes for existing flows; this milestone adds examples and tests. Bugs found by the examples are fixed here.

**Out of scope:** desktop applications and OCR; reading e-mail (IMAP); an AI extraction example (needs a local model on the machine, 1.1.0); examples that depend on real company websites (only local pages and the existing public examples).

### 1.0.0: Stable core

**Goal:** a core that can be trusted: what 1.0 keeps stable is written down, old names that will go are announced, and the release candidate has run on real machines before the final release.

**Scope:** the release checklist issue, and issues found while testing the release candidate. Moved from 2026-11-03 to 2026-11-06 (decided 2026-11-01) so the 48-hour soak runs in full and leaves time for fixes: the release candidate on 2026-11-02, the soak until 2026-11-04, only bug fixes after the candidate. Moved to 1.1.0: the `invoice_check` and `daily_sales_report` examples, #118 (docs structure), and #125 (AI assistant benchmark).

**Exit criteria**

Before the release candidate:
- [x] `docs/compatibility.md`: what stays stable for all of 1.x (`flow.md` syntax, action names and parameters, CLI commands, exit codes, `--json` output and its JSON Schemas once they exist, Hub API and views, settings files) and what may still change (text meant for people, Studio, ask router)
- [x] Exit codes with a meaning ([design/agent-interface.md](design/agent-interface.md), section 4) for `kinenix run`, `validate`, `connect`, and `kinenix hub ...`: technical failure, wrong use, business rule, invalid flow, newer Kinenix needed, Hub unreachable, not found, partial run
- [x] `kinenix run` prints `Run <run_id>` as its first line, and every command that takes a run accepts its `run_id`
- [x] Deprecations announced for 2.0, with a warning when used: the `orchestrator` names and `ORCHESTRATOR_*` variables, `on_error: retry`, `fallback_step_id`, `kinenix export-md`
- [x] Threat model of kinenix-core, kinenix-worker, and kinenix-hub (flows from others running code, secrets in logs and on the Hub, access to the Hub on the LAN without HTTPS, `hub query` changing data, file paths leaving their folder, dashboard XSS), and a code and security review against it, with every finding fixed or moved to a milestone
- [x] Security checks in CI on every pull request: `pip-audit` (no dependency with a known vulnerability) and `bandit` (every finding fixed or explained in the code)
- [x] Failure-injection tests: the Hub is down or slow during a run (the run completes, the log is kept, one warning); an input file is missing; the browser closes in the middle of a loop (Finally still runs, no browser process is left)
- [x] `docs/releasing.md` installs from TestPyPI without its broken copies of other packages
- [x] Release `1.0.0rc2` (2026-11-02). `1.0.0rc1` went only to TestPyPI: testing it on a clean Ubuntu user and with a flow built by an AI assistant found #145 and logs written to the current folder, fixed in rc2
- [x] Release `1.0.0rc3` (2026-11-06) with the fixes from the review of rc2 (#159 to #174), which settle behavior that is frozen for 1.x. Soak on the Raspberry Pi, 2026-11-06 to 2026-11-08: every run on time and recorded, no crash, worker memory steady at about 109 MB
- [x] Release `1.0.0rc4` (2026-11-09) with #166: a stopped run finishes its step and runs Finally

Check of 1.0.0rc4 (2026-11-09 to 2026-11-10):
- [x] Soak: the Raspberry Pi worker runs the offline examples (`hello`, `quote_requests`, the tutorial solution) every 30 minutes and reports to a Hub on the same Pi, 48 hours for 1.0.0rc3 and 24 hours for 1.0.0rc4: no failure caused by Kinenix, memory does not grow (worker at about 108 MB), no browser process is left behind; a baseline (time and memory of a 100-item loop on the Raspberry Pi) is written in `docs/examples.md`. In the rc4 soak, 148 runs, every one recorded on the Hub; a restart of the worker during a run ended it as `interrupted` with Finally run. The Hub answered HTTP 500 twice when two writes met, without losing a run (#201, after 1.0.0)
- [x] `bot_fx_rate` runs on its cron schedule on the worker
- [ ] Hub: every run and failure is recorded, and `report`, `logs`, and `query` answer correctly
- [x] A new Linux user on the Raspberry Pi: `.github/scripts/fresh_user_test.sh 1.0.0rc4` passed all 15 checks
- [x] Windows: a Hub database from 0.2.0b3 upgrades through Hub 1.0.0rc2 with no data lost
- [x] Only bug fixes after the release candidate

Release:
- [x] Version `1.0.0`, package classifier `Development Status :: 5 - Production/Stable`, CHANGELOG with upgrade notes from 0.2.0b4
- [ ] TestPyPI checked; tag `v1.0.0`; PyPI checked

**Compatibility:** no breaking change from 0.5.0b1. Deprecated names keep working, with a warning, until 2.0.

**Out of scope (after 1.0.0):** the agent interface, MCP server, and job dispatch (1.5.0); developer tools (1.2.0); a Hub service installer and a Docker image; `kinenix connect --name` and finding the Hub on the LAN automatically; `kinenix record`; PostgreSQL; Studio (paused).

### Later: measured limits

Noted on 2026-10-16 and not scheduled yet; correctness comes first (0.3.0b1 to 0.5.0b1), then security (1.0.0).

- Resource use measured on each platform (RAM and CPU of a worker with and without a browser, and of the Hub; startup time; time per step), published as system requirements
- Several flows running at the same time on one worker: no clash of log files, output files, or settings, and the Hub receives every run
- Hub load: many workers sending runs at once, a large `hub.db`, and the time `query` and `report` take
- macOS in CI

### 1.1.0: Flow data tools

**Goal:** fix what real flows written by AI assistants ran into after the release candidates: sorting, filtering, and totals on lists (#142, #143); shorter conditions (#144); loops that stop early and paging with per-page error tolerance (#191, #192); text-to-value lookups (#194); a custom error message on any step (#193) and `on_error: ignore` for steps whose failure does not matter (#197); clearer business errors on web lists (#146); plain causes and fixes for the errors of Kinenix's own actions (#219); template guidance (#150) and a validate hint for loops (#151); `kinenix-worker service install` after `pip install` (#153); worker logs of its triggers (#156); and `> Requires:` detection for features newer than 0.4.0b1 (#198).

**Compatibility:** additions only; nothing promised in 1.0.0 changes.

- [ ] Release `1.1.0rc1` (2026-11-12) with #142, #143, #144, #173, #191, #192, #193, and #197, to test them on real flows (books.toscrape)

### 1.3.0: Hardening and docs

**Goal:** close the open findings of the threat model ([design/threat-model.md](design/threat-model.md)), add a security guide for security teams, and organize the website as tutorial, how-to, reference, and explanation (#118).

### 1.4.0: Daily results you can trust

**Goal:** Kinenix itself knows whether each day's work really succeeded: expected outputs per flow, so missing, empty, or old files fail the run (#152); missed runs shown on the Hub (#154); and triggers managed by command instead of editing `triggers.json` (#155).

### 1.5.0: Works with AI agents

Until 2026-11-03 this section was 1.1.0, "Agent interface". The goal grew: an agent works like an employee who builds a flow from a requirements file for a person to review, runs the flows a person schedules, and says when a flow failed, did not run, or did not produce its file. The checklist is #97; #125 is the benchmark.

**Goal:** an AI agent (OpenClaw, Hermes, and Nanobot are tested), with a small local model first, can use Kinenix the way a careful person does: find out what it can do, build a flow for a person to review, answer questions about runs ("did hello fail at 11 pm?") from the Hub, start a run on a worker ("run hello on the Raspberry Pi") after a person confirms, and read and explain the result. Kinenix keeps working without any agent. Design: [design/agent-interface.md](design/agent-interface.md).

The setup this milestone is tested on: the Ubuntu machine runs the Hub, a local model (Ollama), and the agent; the Raspberry Pi stays a worker without AI.

**Scope:** the tools with a contract (design sections 3 to 9), flow approval (section 12), the MCP server `kinenix mcp` (section 13), and job dispatch from the Hub to a worker (section 14). `kinenix ask` is left out (decided 2026-11-12): the agent talks to the person.

**Exit criteria**

Automated:
- [ ] `--json` with the shared envelope on every command; JSON Schemas in `schemas/` for Run, Step, Failure, Issue, and Flow; contract tests in CI check every `--json` answer against them
- [ ] `kinenix capabilities`, `kinenix describe FLOW` (inputs and side effects), `kinenix runs status RUN_ID`, `--var`, `--dry-run` with a confirmation token, `--detach` (a local process), and `--yes`; stable error codes with `retryable`
- [ ] `kinenix approve FLOW`: a run started by an agent refuses a flow that changed since a person approved it
- [ ] Job dispatch: the worker long-polls the Hub for jobs, runs only flows already in its flows folder that its owner allowed, and reports as today; a person confirms every job on the Hub dashboard
- [ ] `kinenix mcp` over standard input and output with a short list of tools (read-only ones free, runs only after confirmation by MCP elicitation or a token), using the same functions as the CLI
- [ ] An evaluation set of agent tasks (build a flow for review, run after confirmation, explain a failure, say what did not run) with a success rate measured for at least one small local model and one cloud model, through OpenClaw, Hermes, and Nanobot
- [ ] A benchmark of how well popular AI assistants build flows from `requirements.md`, with a fixed method and a hidden task, published as `docs/benchmarks/assistants.md` (#125)
- [ ] Two more business examples, each with its `requirements.md`: `invoice_check` (supplier invoices in Excel checked for totals, duplicates, and missing PO numbers; `file.list` with `item_label`, `on_error: next_item`, `file.zip`, `email.send`) and `daily_sales_report` (a sales table from a portal compared with targets; `web.get_table`, a worker schedule, `kinenix hub report`)
- [ ] The website organized as tutorial, how-to, reference, and explanation (#118)

Field test:
- [ ] On the Ubuntu machine, a local model answers "did this flow fail last night, and where?" correctly from the Hub, and starts a flow on the Raspberry Pi worker after confirmation

Docs and release:
- [ ] An agent guide shipped in the package (`kinenix agent-guide`), usable as a skill by OpenClaw, Hermes, Nanobot, and Claude
- [ ] CHANGELOG entry; TestPyPI checked; tag `v1.5.0`; PyPI checked

**Compatibility:** additions only; nothing promised in 1.0.0 changes.

**Out of scope:** agents changing flows and running them without a person seeing the change; general conversation inside Kinenix beyond `kinenix ask`; sending flow data to a cloud model from Kinenix itself.

### 1.2.0: Developer tools

**Goal:** see and check flows in the editor: a flow diagram from `flow.md`, then a VS Code extension with problems, completion, and a live diagram. `flow.md` stays the source; diagrams are read-only views.

**Scope:** #68, #69, #70. Candidates from 1.0.0's out-of-scope list are decided when this milestone starts.

## 1. Next Priorities

Ordered so that safety and predictable runtime behavior come before new distributed features.

| # | Item | Status |
| :--- | :--- | :--- |
| 1 | Studio path containment and CORS restriction | Done |
| 2 | Retry and fallback runtime behavior with tests | Done |
| 3 | Hub worker authentication (API key) | Done |
| 4 | Continuous integration for Python tests and the Studio frontend build | Done |
| 5 | Hub dashboard authentication, CORS, and safe default host | Done |
| 6 | Date actions for scheduled flows (`date.calc`) | Done |
| 7 | `kinenix record` (record browser steps) and `kinenix inspect` (list page elements, test a selector), with an `## Elements` section in `flow.md` that names each selector once; replaces the Studio element picker | Planned |
| 8 | Worker WebSocket protocol and job dispatch from the Hub | Not started |
| - | Persistent Studio sessions, single-step execution, and live telemetry | Paused with Studio |

### 1.4 Continuous Integration

GitHub Actions workflow `.github/workflows/ci.yml` runs on pushes and pull requests to `main` and `dev`:

- [x] Python 3.12 and 3.14 on Ubuntu, and Python 3.12 on Windows.
- [x] Installs `kinenix-core`, `kinenix-worker`, `kinenix-studio`, and `kinenix-hub` with development dependencies.
- [x] Runs every pytest suite, including `kinenix-hub/tests`.
- [x] Builds the Studio frontend with `npm ci` and `npm run build`.
- [x] CI status badge in the README.
- [x] Repository rules checked by tests: every flow validates, documented action parameters match the code, and no emojis anywhere.
- [ ] Formatting, linting, type checking, dependency vulnerability checks, and JSON schema validation of the flows in `flows/`.
- [~] Publish `kinenix`, `kinenix-hub`, and `kinenix-worker` from a tagged release with Trusted Publishing (`release.yml`, `docs/releasing.md`); CI builds, checks, and installs the packages on every pull request. Waiting for the first release.

### 1.5 Hub Hardening

- [x] Protect the dashboard page and read endpoints (HTTP Basic Auth, localhost-only when unset).
- [x] Remove the permissive CORS policy; the dashboard is served same-origin.
- [x] Default the bind host to `127.0.0.1`, requiring an explicit opt-in to listen on the network.
- [x] Escape all worker-provided text in the dashboard (XSS), with a static check and a real-browser test.
- [ ] Content-Security-Policy header for the dashboard (needs the inline `onclick` handlers moved to script).
- [ ] Run AI failure analysis in the background so telemetry ingestion does not wait on the LLM.
- [ ] Document an HTTPS reverse proxy setup (e.g. Caddy or nginx).

### 1.6 Persistent Studio Sessions and Debugging

- Maintain one Playwright browser and context per explicit Studio session.
- Add a "run this step" API that executes against the retained browser state.
- Stream interpreter events: step state, logs, errors, variable snapshots, screenshots.
- Add breakpoints and an element picker that returns robust selector candidates.
- Define session ownership, expiration, cleanup, and isolation so sessions do not leak browser processes.

### 1.7 Worker WebSocket Protocol and Hub Dispatch

```text
Hub -> versioned job bundle -> Worker (WebSocket) -> kinenix-core executes flow
                                              |
                                              +-> status, logs, metrics, screenshots -> Hub
```

- Authenticate workers and authorize job delivery (per-worker credentials).
- Require job acknowledgement and use idempotency keys to prevent duplicate execution after reconnects.
- Support reconnects, cancellation, timeouts, heartbeats, and clear job state transitions.
- Package and version bundles so a worker runs the intended immutable artifact.
- Upload execution artifacts safely and retain structured audit logs.
- Follow the Hybrid Protocol in [architecture.md](architecture.md#5-agent-to-agent-hybrid-protocol-planned).

---

## 2. Status by Module

### Core Engine (`kinenix-core`) - Done
- [x] Flow JSON schema and Pydantic v2 models
- [x] Interpreter, execution context, and `${var}` evaluator (no `eval`)
- [x] Actions: Web (Playwright), Excel/CSV, file system, HTTP, email, logic, flow control
- [x] Error handling: `on_error` with `continue`, `retry`, and `fallback_step_id`; failure screenshots
- [x] Hierarchical structured logging (`logs/<flow>/<date>/<HHMMSS>_<status>.json`)
- [x] CLI and smart flow resolver (`kinenix list`, `kinenix run <flow>`)
- [x] Project bundles (`flow.call`, `@shared/`, `config.json`, `.env`)
- [x] `flow.md` authoring format
- [x] Local AI actions: `ai.prompt`, `ai.extract` (Ollama), `ai.decide` (OpenThai-SystemOne)
- [x] `flow.md` is the only flow file: `kinenix run` and the worker read it directly, `kinenix compile` prints the compiled form, `kinenix export-md` converts old JSON flows; step headings without an action and flows without steps are reported (`flow.json` dropped after a comparison with YAML on `bot_fx_rate`)
- [x] Flow validation (`kinenix validate`): unknown actions and ignored parameters, with suggestions
- [x] Business exceptions with `flow.fail` (recorded as Business, never retried); `web.click` waits for a response; `web.get_table`
- [x] `email.send` through any SMTP provider (Gmail, Microsoft 365, company servers), tested with a local fake SMTP server
- [x] Example flow `bot_fx_rate`: Bank of Thailand transfer rates to CSV and email, verified against the BOT data
- [x] `file.zip` and `file.unzip`: pack a run's output for an email attachment; extraction refuses entries that point outside the destination
- [x] `file.list` (loop over the files in a folder, newest first), `file.read_text` and `file.write_text` (text, lines, JSON, append, Thai legacy encodings), `file.create_folder`; boolean parameters given as text in config ("false") are read correctly by all file actions
- [x] Subflows written as `.md` (compiled when called), sharing the bundle's config and folder; `@shared` components keep their own unless `inherit_config: true`; `kinenix validate` follows subflows and checks `inputs` names; the `hello` example calls a subflow
- [x] `date.calc`: today or a given date, shifted by days, weeks, months, or years and snapped to the start or end of a week, month, or year; `bot_fx_rate` reports the previous month by default instead of fixed dates

### Studio (`kinenix-studio`) - Paused

Paused on 2026-10-08. Flows are written as `flow.md` from a `requirements.md` with an AI assistant (`kinenix init`), so a visual flow editor duplicates that work while adding a React and FastAPI application to maintain. The hardest part of authoring, finding selectors on real pages, moves to a `kinenix record` command built on Playwright's recorder (priority 7 above). The code stays in the repository and in CI, is not published, and receives no new features until this decision is revisited.

- [x] FastAPI backend: flow discovery, read/save with schema validation, step update, action metadata, run
- [x] Path containment to `flows/` and restricted CORS
- [x] React/Vite 3-column UI (step timeline, inspector, context panel) served by the backend
- [ ] Persistent browser session and single-step execution (`POST /api/session/step`)
- [ ] Element picker with multi-layer selectors (role/text, CSS, XPath)
- [ ] Live debugger over WebSocket: step highlighting, variable watcher, error screenshot viewer
- [ ] AI prompt bar for natural-language flow generation
- [ ] Tauri desktop shell

### Hub (`kinenix-hub`) - In progress
- [x] Renamed from Orchestrator to Hub; old command, flags, environment variables, and settings file still work (see [hub.md](hub.md#5-renamed-from-orchestrator))
- [x] FastAPI service with heartbeat and telemetry ingestion over HTTP
- [x] Execution and worker storage via SQLAlchemy (SQLite default, `DATABASE_URL` for others)
- [x] Web dashboard for workers and executions, with per-execution step details
- [x] Command line: first-run setup saved to `~/.kinenix/hub.env`, `kinenix hub status`, `logs`, `setup`, `show-key`, and `rich` output
- [x] Default database in `~/.kinenix/hub.db`, outside the source tree
- [x] Schema migrations applied at start (built-in runner, `schema_version` table, no extra dependency) and SQLite WAL mode, so existing databases upgrade in place and readers do not block workers
- [x] Run records for people and AI: every step (`step_results`) and every failure (`failures`, also continued ones) with path, subflow, line, loop item, retries, and how it was handled; a Markdown run report per run; views `v_runs`, `v_failures`, `v_steps`; runs stored earlier are filled in from their logs; data dictionary in [hub_data.md](hub_data.md), checked by a test
- [x] `kinenix connect URL`: asks for the worker key, checks it against the Hub, and saves the Hub in `~/.kinenix/kinenix.env` for `kinenix run` and kinenix-worker; `kinenix hub setup` offers the same for runs on the Hub machine, so no environment variables are needed
- [x] `kinenix hub report [ID] --flow NAME`: the run report of a flow's latest run (name or part of it, `--limit N` for more), and `kinenix hub logs --flow NAME` for its steps
- [x] `kinenix hub query`: read-only questions to the Hub database from the terminal, on the Hub machine or over HTTP (`--url`): views or tables with `--since`, `--flow`, `--worker`, `--status`, `--filter`, or one SQL `SELECT`; `--list` and `--describe` from the data dictionary; table, JSON, CSV, and Markdown output; user views from `~/.kinenix/hub_views/custom_*.sql`
- [x] AI failure classification with rule-based fallback
- [x] Worker API key authentication
- [x] Dashboard authentication (HTTP Basic Auth)
- [x] No CORS policy and localhost-only default bind address
- [ ] Background AI analysis and HTTPS deployment guide (see 1.5)
- [ ] PostgreSQL + Redis job queue
- [ ] Business ROI dashboard: hours saved, cost saved, transaction audit trail
- [ ] Alerts and daily digests (LINE Messaging API first, then Teams and Email)
- [~] Natural-language questions about jobs and workers with a local model (see [ask_router.md](ask_router.md))

### Worker (`kinenix-worker`) - In progress
- [x] `kinenix-worker run`, `watch` (file trigger), `schedule` (interval), `daemon` (multi-trigger config)
- [x] Optional per-job sandbox workspace (`~/.kinenix/workspaces/<job_id>`)
- [x] Verified on Raspberry Pi 4 (ARM64) with setup script; re-verified on 2026-10-05 after the rename to Hub: heartbeats as a systemd service and the `bot_fx_rate` flow run by a cron trigger, reported to the Hub
- [x] Heartbeat sender to the Hub (`kinenix-worker ping`, busy/online/offline status), with `rich` output
- [x] systemd service installed by the setup script (`install_service.sh`), starts the daemon at boot
- [x] Cron schedules (`"cron": "0 8 1 * *"` in `triggers.json`, `kinenix-worker schedule --cron`)
- [ ] WebSocket job client (see 1.7)
- [ ] Bundle packaging (`.kinpkg`), download, and local cache
- [ ] Real-time log and screenshot streaming

### Desktop Automation and Public Release - Not started
- [ ] Windows desktop automation (`uiautomation` / UIA)
- [ ] Credential vault for flow secrets
- [ ] Docker Compose one-command deployment
- [x] Community quickstart documentation ([quickstart.md](quickstart.md))
- [x] `kinenix init "Task name"`: new project for the requirements-to-AI-to-`flow.md` workflow (`requirements.md`, `AGENTS.md` for the assistant, `.env.example`); `kinenix init --example` with packaged examples (`hello`, `bot_fx_rate`, `rpachallenge`); `kinenix actions` lists actions and their parameters
- [x] User flows live in a flows folder outside the Kinenix repository (default `~/kinenix-flows`, asked on the first `kinenix init`, optional git repository, `kinenix flows-dir`, `KINENIX_FLOWS_DIR`); `kinenix run NAME` and worker triggers find flows there by name

### Advanced Local Agentic Capabilities - Not started
- [ ] Self-healing UI selectors with DOM fallback matching
- [ ] Studio copilot for natural-language flow generation and error diagnosis
- [ ] GitOps release pipeline to Hub and workers
