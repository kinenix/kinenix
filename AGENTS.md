# AGENTS.md

Entry point for AI coding assistants (any vendor) working on **Kinenix**, a local AI-native RPA framework in Python. Read this file first, then open the rule or doc files relevant to your task. Detailed rules live in `.agents/rules/`; this file does not duplicate them.

## Repository Map

| Path | What it is | State |
| :--- | :--- | :--- |
| `kinenix-core/` | Flow interpreter, variable evaluator, action plugins, `kinenix` CLI | Implemented |
| `kinenix-worker/` | Unattended runner with schedule and file-watch triggers | Implemented |
| `kinenix-studio/` | FastAPI server + React/Vite web UI for viewing and editing flows | Paused: kept and tested, no new features (`docs/roadmap.md`) |
| `kinenix-hub/` | FastAPI + SQLAlchemy telemetry receiver and dashboard | Early (HTTP push, SQLite default) |
| `flows/` | Project bundles (`flow.md`, `config/`, `assets/`, `subflows/`); `@shared/` holds reusable subflows | |
| `schemas/` | JSON schemas for flows and execution logs | |
| `docs/` | Human and AI reference documentation | |
| `.agents/rules/` | Detailed engineering rules | |

Key code locations:
- Interpreter and retry/fallback logic: `kinenix-core/kinenix/engine/interpreter.py`
- `${var}` expression resolution (no `eval`): `kinenix-core/kinenix/engine/evaluator.py`
- `flow.md` parser (compiles to the in-memory `FlowDefinition` on every run): `kinenix-core/kinenix/engine/markdown.py`
- Action base class and registry: `kinenix-core/kinenix/actions/base.py`, `registry.py`
- Hub auth (worker API key, dashboard Basic Auth): `kinenix-hub/kinenix_hub/security.py`

## Setup and Commands

The project uses a virtual environment at `.venv/` in the repository root. On Windows, the interpreter is `.venv/Scripts/python.exe`; the system Python does not have the dependencies installed.

```powershell
# Install (editable)
.venv/Scripts/python.exe -m pip install -e "kinenix-core[dev]" -e "kinenix-worker[dev]" -e "kinenix-studio[dev]" -e "kinenix-hub[dev]"

# Tests: run kinenix-core from its own directory, the others from the repo root
cd kinenix-core; ../.venv/Scripts/python.exe -m pytest -q; cd ..
.venv/Scripts/python.exe -m pytest -q kinenix-worker/tests
.venv/Scripts/python.exe -m pytest -q kinenix-studio/tests
.venv/Scripts/python.exe -m pytest -q kinenix-hub/tests

# Security checks (CI job "Security checks"; .agents/rules/security.md)
.venv/Scripts/python.exe -m pip install pip-audit bandit zizmor
.venv/Scripts/python.exe -m bandit -q -r kinenix-core/kinenix kinenix-hub/kinenix_hub kinenix-worker/kinenix_worker -x "*/build/*"
.venv/Scripts/zizmor.exe --offline --min-severity medium .github/workflows

# Studio frontend
cd kinenix-studio/frontend; npm ci; npm run build

# Create, run, or check a flow / start the hub
kinenix init "Get stock data"                     # new task project: requirements.md, AGENTS.md, flow.md skeleton
kinenix init demo --example hello                 # copy of a flows/examples bundle shipped in the package
kinenix actions [web]                             # actions and the parameters each accepts
kinenix run flows/examples/quote_requests
kinenix validate flows/examples/quote_requests   # unknown actions and ignored parameters
kinenix connect http://<hub-ip>:8080   # send this machine's runs to a Hub (asks for and checks the key)
kinenix hub            # first run asks setup questions and saves them
kinenix hub status     # workers and recent executions of a running server
kinenix hub logs [ID]  # steps of one execution or run id (latest when ID is omitted; --flow NAME for a flow's latest)
kinenix hub report --flow NAME   # short report of a flow's latest run (--limit N for more)
kinenix hub query v_failures --since yesterday   # read-only questions to hub.db (--list, --describe, SQL)
```

CLI output in `kinenix-worker` and `kinenix hub` is rendered with `rich` (`kinenix_worker/display.py`, `kinenix_hub/console.py`); `kinenix-core` itself does not depend on it.

Run the test suites for every module you touch before reporting work as done. GitHub Actions (`.github/workflows/ci.yml`) runs the same commands on every push and pull request to `main` and `dev`, and weekly; `codeql.yml` adds code scanning; keep the workflow in sync when these commands change.

The website www.kinenix.com is a separate repository (`kinenix/kinenix-web`, MkDocs on Cloudflare Pages) that copies `docs/` from `main` at every build; `.github/workflows/website.yml` asks it to rebuild when `docs/` changes on `main` (`docs/releasing.md`, section 5). Write documentation here, in `docs/`; do not edit the copies in kinenix-web.

A flow is one `flow.md` file; there is no `flow.json` (the runner and the worker read `flow.md` directly, `kinenix compile` prints the compiled form, and `kinenix export-md` converts old JSON flows). Do not create `flow.json` files.

Users keep their own flows in a flows folder outside this repository (`workspace.py`, default `~/kinenix-flows`). `flows/` here holds only the examples shipped with Kinenix and shared subflows; do not add user or business flows to it. Examples that need a real website or other services live in [kinenix/examples](https://github.com/kinenix/examples).

After editing `flows/examples/hello`, `bot_fx_rate`, `first_flow` (the tutorial, `docs/tutorial.md`), or `quote_requests`, run `python .github/scripts/sync_examples.py`: the package ships copies of them for `kinenix init --example`, and a test fails when the copies differ. The new-project template (`requirements.md`, an `AGENTS.md` for the user's AI assistant, and the rest) lives in `kinenix-core/kinenix/templates/new_project/`.

`kinenix`, `kinenix-hub`, and `kinenix-worker` are published to PyPI together with one version (`pip install "kinenix[hub]"`, `"kinenix[worker]"`); the version lives in each package's `__version__`. Releases are tag-driven through `.github/workflows/release.yml`; follow [docs/releasing.md](docs/releasing.md) and never reuse a released version number. `kinenix-studio` is not published.

## Rules Index

Read the matching file before working in that area:

| Task | Read |
| :--- | :--- |
| Adding or changing an action | `.agents/rules/action_documentation.md`, `docs/actions_reference.md` |
| Writing or compiling flows | `docs/flow_markdown_spec.md`, `docs/project_bundles.md`, `schemas/flow.schema.json` |
| Errors, retries, failure telemetry | `.agents/rules/error_handling.md` |
| Logs and telemetry format | `.agents/rules/logging.md`, `docs/logging.md` |
| Secrets, credentials, data privacy | `.agents/rules/security.md` |
| Hub setup and API keys; connecting machines and troubleshooting | `docs/hub.md` (section 8 for connections) |
| Hub tables, views, run records, queries | `docs/hub_data.md` (update it with any column, view, or `details` key, then copy it to `kinenix-hub/kinenix_hub/hub_data.md`; tests check both), `docs/hub.md` section 7 |
| Code style | `.agents/rules/coding_standards.md` |
| Tests | `.agents/rules/testing_standards.md` |
| Commits and branches | `.agents/rules/git_workflow.md` |
| Module boundaries and design principles | `.agents/rules/architecture.md`, `docs/architecture.md` |
| What is built vs. planned, next priorities | `docs/roadmap.md` |
| Finding any other document | `docs/README.md` |

## Non-Negotiable Rules

1. **Never commit or push without an explicit instruction from the user.** Finish the work, summarize it, and wait. (`collaboration.md`, `git_workflow.md`)
2. **Present a plan before large changes.** (`collaboration.md`)
3. **No secrets in code, `flow.md`, or `config.json`.** Read them from environment variables. (`security.md`)
4. **No `eval()` or arbitrary code execution** when evaluating flow expressions.
5. **Update `docs/actions_reference.md` in the same change** whenever an action is added or modified, with a `flow.md` example.
6. **No emojis anywhere:** code, comments, UI text, commits, pull requests, issues, release notes, and documentation.
7. **Keep business data local.** Do not send flow data to third-party cloud APIs unless an action is explicitly designed for it.
8. **Use Conventional Commits** (`feat:`, `fix:`, `docs:`, `test:`, ...).
9. **No AI attribution trailers in commits** (no `Co-Authored-By` for AI assistants). AI help is credited in the README. Pull request descriptions may end with the plain line `Generated with Claude Code`. (`git_workflow.md`)

## Current State vs. Target Architecture

Some rule files and the README describe the target architecture, not what exists today. Follow the existing code for anything listed below, and ask before introducing the target technology.

| Topic | Target (in rules/README) | Current code |
| :--- | :--- | :--- |
| Action parameters | Pydantic model per action | Actions receive a plain `Dict[str, Any]` and declare their parameter names in `accepted_parameters` for flow validation |
| Action tests | `kinenix-core/tests/actions/` | Tests live directly in `kinenix-core/tests/` |
| Studio | Tauri desktop app | FastAPI + React/Vite in the browser; paused, do not extend without asking |
| Hub backend | Async handlers, PostgreSQL, Redis/Celery | Sync handlers, SQLite by default, no queue |
| Worker communication | WebSocket job dispatch and log streaming | Workers push telemetry and heartbeats over HTTP; no dispatch |

When you change code so that it matches a target, update this table and `docs/roadmap.md`.

## Environment Variables

| Variable | Used by | Purpose |
| :--- | :--- | :--- |
| `KINENIX_HUB_URL` | kinenix-core, kinenix-worker | Hub URL for telemetry and heartbeats; when unset, the one saved by `kinenix connect` or `kinenix hub setup` in `~/.kinenix/kinenix.env` |
| `KINENIX_HUB_API_KEY` | kinenix-core, kinenix-worker, kinenix-hub | Shared worker key: workers send it as `X-API-Key`, the Hub requires it on write endpoints (unset on the Hub means localhost-only). Same value on both sides |
| `KINENIX_SETTINGS_FILE` | kinenix-core, kinenix-worker, kinenix-hub | Saved client settings (default `~/.kinenix/kinenix.env`: flows folder, Hub URL and key); test suites point it to a temporary file |
| `KINENIX_FLOWS_DIR` | kinenix-core, kinenix-worker | The user's flows folder (default `~/kinenix-flows`, or the setting saved in `~/.kinenix/kinenix.env`); `kinenix init` creates projects there and `kinenix run NAME` finds them |
| `KINENIX_WORKER_ID` | kinenix-core, kinenix-worker | Worker identifier in telemetry and heartbeats; kinenix-worker defaults to the host name |
| `KINENIX_HEARTBEAT_INTERVAL` | kinenix-worker | Seconds between heartbeats while a worker command runs (default 30) |
| `KINENIX_HUB_DASHBOARD_USER` / `KINENIX_HUB_DASHBOARD_PASSWORD` | kinenix-hub | Basic Auth for the dashboard and read endpoints; unset password means localhost-only |
| `KINENIX_HUB_HOST` / `KINENIX_HUB_PORT` | kinenix-hub | Bind address (default `127.0.0.1`, localhost only) and port |
| `KINENIX_HUB_SETTINGS_FILE` | kinenix-hub | Saved settings from `kinenix hub setup` (default `~/.kinenix/hub.env`); environment variables override it |
| `KINENIX_HUB_VIEWS_DIR` | kinenix-hub | Folder of user views (`custom_*.sql`) created at every Hub start (default `~/.kinenix/hub_views`) |
| `KINENIX_HUB_WORKER_OFFLINE_SECONDS` | kinenix-hub | Seconds without a heartbeat before a worker shows as offline (default 90) |
| `DATABASE_URL` | kinenix-hub | SQLAlchemy connection string |
| `CENTRAL_LLM_URL` | kinenix-hub | LLM endpoint for failure analysis |

## Keeping This File Accurate

This file is read by AI tools as ground truth. If you change a command, path, module state, or rule referenced here, update it in the same change. Keep it short: put details in `docs/` or `.agents/rules/` and link to them.

Documentation layout: each topic has one owning file (index in `docs/README.md`). `docs/` describes how the system works; `.agents/rules/` states only what must or must not be done. Link between them instead of copying content.
