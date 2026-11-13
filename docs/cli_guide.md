# CLI Execution Guide (kinenix)

This guide documents the Command Line Interface (CLI) for kinenix, powered by the `kinenix` runner in `kinenix-core`.

---

## 1. Installation

From PyPI (see the [Quickstart](quickstart.md)):

```powershell
pip install kinenix
```

From a clone of the repository, for development, in editable mode:

```powershell
cd kinenix-core
pip install -e .
```

Verify that the CLI is accessible:

```powershell
kinenix --version
# or
kinenix version
```

---

## 2. Core Commands

### 2.1 Check Version and Environment (`version`)
Outputs runtime details including kinenix version, Python runtime, operating system, and architecture:

```powershell
kinenix version
```

### 2.2 Install Playwright Browsers (`install-browsers`)
Downloads the Chromium browser binary required for Web automation tasks:

```powershell
kinenix install-browsers
```
*(Note: kinenix also detects missing browser binaries and automatically downloads Chromium on the first web flow execution).*

### 2.3 Start a Project (`init`)
Projects are created in your **flows folder**, separate from the Kinenix source code (default `~/kinenix-flows`; see [Where your flows live](quickstart.md#2-where-your-flows-live)). The first `kinenix init` at a terminal asks where it should be and whether to make it a git repository; scripts and CI use the default without asking. Every project in it runs by name from any folder.

**For a new task**, give it a name. The folder is derived from the name (`Get stock data` becomes `get_stock_data`; Thai names work):

```powershell
kinenix init "Get stock data"
kinenix init "Get stock data" --dir C:\bots\stocks     # choose the folder yourself
```

| Created file | Purpose |
| :--- | :--- |
| `requirements.md` | The requirements (RQ), with sections to fill in: goal, steps, changeable settings, secrets, output, errors, schedule |
| `AGENTS.md`, `CLAUDE.md` | Instructions for the AI assistant that turns `requirements.md` into `flow.md`: spec links, `kinenix actions`, config and secret rules, and `kinenix validate` before handing back |
| `flow.md` | A one-step placeholder flow named after the task, so `validate` and `run` work from the start |
| `config/config.json` | Empty settings (`{}`) |
| `.env.example`, `.gitignore` | Where secrets go, and keeping `.env`, `output/`, and `logs/` out of git |
| `README.md` | The workflow: requirements, AI assistant, validate, run |

The intended workflow: write `requirements.md`, open the folder in an AI assistant and ask it to build the flow, then `kinenix validate` and `kinenix run`.

**To copy a complete example** instead, use `--example`. The folder must not exist or must be empty; nothing is overwritten.

```powershell
kinenix init --list                          # examples, and which need a browser
kinenix init demo --example hello            # no browser, no internet: the quickest installation check
kinenix init fx --example bot_fx_rate
kinenix run demo
```

| Example | What it does |
| :--- | :--- |
| `hello` | Builds a greeting table from `config.json` and writes a CSV; the quickest installation check |
| `bot_fx_rate` | Bank of Thailand transfer rates for chosen currencies and dates to CSV, with email (needs a browser) |
| `quote_requests` | Enters quote requests from a CSV into a made-up insurer's form and collects the packages; failed requests are listed with their reasons (needs a browser, no internet) |
| `first_flow` | The tutorial: finished `requirements.md`, an empty `flow.md` for your AI assistant to build, and saved shop pages; the solution stays in the repository so an assistant cannot copy it ([tutorial.md](tutorial.md)) |

The examples are copies of `flows/examples/` in the repository, kept identical by `.github/scripts/sync_examples.py` and a test. Examples that need a real website, such as the RPA Challenge, are in [kinenix/examples](https://github.com/kinenix/examples). Each has the `requirements.md` it was built from, as a model for your own.

**To refresh the AI assistant instructions of an older project**, so its assistant follows the current rules (for example `on_error: next_item`, no `flow.json`):

```powershell
kinenix init --update-agents                 # the project in the current folder
kinenix init tiph_quotes --update-agents     # a project by name or folder
```

It rewrites `AGENTS.md` and `CLAUDE.md` from the current template with the project's title; a changed `AGENTS.md` is kept as `AGENTS.md.bak`, to copy back anything specific to the project. `kinenix validate` suggests it when it finds a leftover `flow.json`.

### 2.4 Show or Change the Flows Folder (`flows-dir`)

```powershell
kinenix flows-dir                    # where flows are kept, and where that setting comes from
kinenix flows-dir D:\bots\flows      # change it (saved in ~/.kinenix/kinenix.env)
```

Order of precedence: the `KINENIX_FLOWS_DIR` environment variable, then the saved setting, then `~/kinenix-flows`.

### 2.5 List Actions and Their Parameters (`actions`)
Prints every action with the parameters it accepts, from the code itself. Useful while writing `flow.md`, and for AI assistants that need exact parameter names:

```powershell
kinenix actions          # all actions
kinenix actions web      # only web.*
```

### 2.6 List Available Flows (`list`)
Scans the current folder, your flows folder (`kinenix flows-dir`), and a repository's `flows/` and `examples/` folders, and lists every project bundle (a folder with a `flow.md`) by its folder name. A single `.md` file is not listed; run it by its path:

```powershell
kinenix list
```

### 2.7 Run a Flow (`run`)
Executes an automation flow using the Smart Flow Resolver. You can specify a flow by alias, project folder, relative path, or absolute path:

```powershell
# Run by alias or bundle name
kinenix run quote_requests

# Run by namespace
kinenix run examples/quote_requests

# Run by direct file path
kinenix run flows/examples/quote_requests
```

The first line `kinenix run` prints is `Run <run_id>`, for example `Run 20261028T101500-abcd`. The same id is `${run.id}` inside the flow, is part of the log file names, and is shown on the Hub; `kinenix hub logs <run_id>` shows the steps of that run.

### 2.8 Exit Codes
Every `kinenix` and `kinenix-worker` command ends with one of these codes, so a scheduler, a CI job, or an AI assistant can decide what to do next without reading the output. The codes stay the same for all of 1.x.

| Code | Meaning | Try again? |
| :--- | :--- | :--- |
| 0 | Success: nothing failed | |
| 1 | The run failed for a technical reason: timeout, element not found, file locked, or a failure in `## Finally` after the steps passed | Often |
| 2 | Wrong use of the command: unknown option, missing argument, bad `--vars` JSON, a `--config` file that is not a JSON object | No; fix the command |
| 3 | The run stopped on a business rule (`flow.fail`): the data did not pass | No; the data needs a person |
| 4 | The flow is invalid: `kinenix validate` problems, an expression error, an unknown action, no steps | No; fix the flow |
| 5 | The flow needs a newer Kinenix (`> Requires:`) | No; upgrade Kinenix |
| 6 | The Hub cannot be reached, or refused the key (`kinenix connect`, `kinenix hub status`, `logs`, `query --url`) | Yes, later |
| 7 | Not found: no such flow, file, example, action, run id, table, or view | No |
| 8 | The run finished, but items or steps failed on the way (`on_error: continue` or `next_item`); they are in the summary, the log, and on the Hub, where the run shows as partial | No; a person checks the failed items |
| 130 | Stopped on request: Ctrl+C or SIGTERM (`systemctl stop`). The current step ended, `## Finally` ran, and the run is recorded as interrupted | Yes, when you want it to run |

```powershell
kinenix run tiph_quotes
if ($LASTEXITCODE -eq 3) { Write-Output "The data did not pass; see the run on the Hub" }
```

### 2.9 Check a Flow (`validate`)
`kinenix validate NAME` checks a flow and its subflows without running them ([flow_markdown_spec.md, section 5](flow_markdown_spec.md#5-checking-and-inspecting-a-flow) lists the checks). `kinenix run` and `kinenix compile` print the same lines before they start. Each line starts with its level:

| Level | Meaning | Exit code of `validate` |
| :--- | :--- | :--- |
| `Warning:` | A problem: the flow would run wrongly or not at all, for example a misspelled parameter or variable | 4 |
| `Hint:` | Something that is often a mistake but may be intended, for example a `${name}` that only `--vars` could set, or a loop whose sub-steps use `on_error: next_item` while others stop the whole loop. Fix it, or change the flow as the hint says to make it go away | 0 |
| `Deprecated:` | Still works in 1.x, but Kinenix 2.0 removes it | 0 |

```text
Warning: Step 'step_1' (Build Subject), line 9: ${custmer_email} is never set, so it is empty when the step runs. Did you mean 'customer_email'?
Hint: Step 'step_1' (Build Subject), line 9: ${report_date} is not set anywhere in the flow, so it is empty unless the run gets it from --vars. If it does, declare it under ## Variables (for example "- `report_date`:") so this hint goes away.
Hint: Step 'step_3' (Quote Each Vehicle), line 21: 2 sub-steps that may fail stop the whole loop when they fail ('Open Page' line 30, 'Choose Model' line 33), while 'Check Row' line 23 uses on_error: next_item. Add on_error: next_item to the steps that may fail for one item, or write on_error: fail on those where one failure should stop the run.
```

---

## 3. Command Options & Parameters

### 3.1 Override / Inject Variables (`--vars`)
Pass external variables or runtime overrides to a flow as a JSON string:

```powershell
kinenix run quote_requests --vars "{\"config\": {\"dry_run\": true}}"
```

Inside the flow, these variables can be accessed using the standard expression syntax `${target_url}`. Declare each variable the flow expects from `--vars` under `## Variables`, with a default or empty (`` - `report_date`: ``): readers see what the flow takes, and `kinenix validate` does not report the name as never set.

**Another settings file for one run (`--config`):** the keys of the file replace the same keys of `config/config.json`, for example to point a flow at saved pages for a test ([project_bundles.md, Testing Against Saved Pages](project_bundles.md#4-testing-against-saved-pages)). The path is relative to the current folder or the flow's folder:

```powershell
kinenix run tiph_quotes --config config/test.json
```

### 3.2 Custom Log Directory (`--log-dir`)
By default, Kinenix writes structured JSON logs into `logs/` of the flow's project folder, or of the git repository that holds the project, whichever folder the command is started from. You can override this location using `--log-dir` or `KINENIX_LOG_DIR`:

```powershell
kinenix run quote_requests --log-dir "./custom_logs"
```

### 3.3 Send Telemetry to the Hub (`kinenix connect`, `--hub`)
Connect a machine once, and every run on it uploads its execution log to that Hub:

```bash
kinenix connect http://<hub-ip>:8080     # asks for the key, checks it, saves it in ~/.kinenix/kinenix.env
kinenix connect                          # the Hub in use;  kinenix connect --off  stops reporting
```

For one run only, `--hub` sets the Hub URL. If the Hub requires an API key and none is saved, set `KINENIX_HUB_API_KEY` first:

```powershell
$env:KINENIX_HUB_API_KEY = "<key>"
kinenix run quote_requests --hub http://localhost:8080
```

See the [Kinenix Hub Guide](hub.md#2-worker-authentication) for setup details.

### 3.4 Ask the Hub About Runs (`kinenix hub query`)
Reads runs, steps, and failures from the Hub database, read-only. On the Hub machine it reads `hub.db` directly; `--url` asks a Hub on another machine.

```bash
kinenix hub report --flow "BOT FX"                # how the latest run of a flow went
kinenix hub logs --flow "BOT FX"                  # every step of that run
kinenix hub query --list                          # what can be queried
kinenix hub query v_failures --since yesterday    # what failed, where, on which item
kinenix hub query "SELECT flow_name, COUNT(*) FROM v_runs GROUP BY flow_name"
```

Options, safety rules, and user views: [hub.md, Querying Runs](hub.md#7-querying-runs). Columns: [hub_data.md](hub_data.md).

---

## 4. Smart Flow Resolver Behavior

When running `kinenix run <input>`, the resolver searches candidate paths in the following priority order:

1. **Exact File Path:** Resolves directly if `<input>` is an existing file path.
2. **Project Bundle Directory:** If `<input>` is a directory containing `flow.md`, executes `<input>/flow.md`.
3. **Appended `.md`:** Checks if `<input>.md` exists.
4. **Discovered Flow Alias:** Matches the folder names listed by `kinenix list`.
5. **Search Directories:** Looks for `<input>/flow.md` in the current folder, your flows folder (`kinenix flows-dir`), and `flows/` and `examples/`.

---

## 5. Running Automated Unit Tests

To run the automated test suite using `pytest`:

```powershell
cd kinenix-core
pytest tests
```
