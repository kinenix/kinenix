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

At a terminal it also asks PyPI for the latest release and shows it, with the upgrade command when it is newer.

**New-release notice.** When a newer release is on PyPI, any `kinenix` command run at a terminal ends with a notice on stderr:

```text
A new Kinenix release is available: 1.2.0 -> 1.3.0
Upgrade: pip install --upgrade "kinenix[hub,worker]"
Changes: https://github.com/kinenix/kinenix/blob/main/CHANGELOG.md
(Turn this message off with KINENIX_NO_UPDATE_CHECK=1)
```

- Kinenix asks `https://pypi.org/pypi/kinenix/json` at most once a day, in the background, and keeps the answer in `update_check.json` next to the saved settings (`~/.kinenix/` by default). The request holds only the package name: no flow data, no machine id.
- A command waits for PyPI at most 2 seconds, and only on the run that asks. Without internet the notice does not appear.
- A pre-release (`1.3.0rc1`) is offered only to a machine that already runs a pre-release.
- There is no check when the output does not go to a terminal (scripts, services, pipes), when `CI` is set, with `--json` or `--format json`, for `kinenix hub start`, or when a worker runs flows from its triggers.
- `KINENIX_NO_UPDATE_CHECK=1` turns the check off, for example on machines that must not reach the internet.
- Nothing is upgraded for you: a person runs the `pip` command.

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

### 2.10 Build a Signed Package (`publisher`, `pack`, `trust`)
Kinenix 1.3.0. A package (`.kinx`) carries one flow folder to other machines as one file, signed by the machine that built it ([design/flow-deploy.md](design/flow-deploy.md)). Signing uses OpenSSH 8.1 or later (`ssh-keygen`), which Windows 10 and 11, Ubuntu, and Raspberry Pi OS have; without it, the commands say how to install it.

```bash
kinenix publisher init                 # once per building machine: makes the key, trusts it here
kinenix publisher show                 # the public key to give to other machines
kinenix pack get_stock_data            # validates, then builds ./get_stock_data-1.3.0.kinx
kinenix pack get_stock_data --version 1.3.1 -o dist
kinenix trust add "ssh-ed25519 AAAA... office-pc" --name office-pc   # on a machine that installs packages
kinenix trust list
kinenix trust remove office-pc
```

- **`publisher init`** makes an Ed25519 key in `~/.kinenix/publisher/` (private key mode `600` on Linux) named after the computer (`--name` to choose), and trusts it on this machine. `ssh-keygen` asks for an optional passphrase; with one, `pack` asks for it each time (`--no-passphrase` skips the question). It keeps an existing key; `--force` makes a new one, after which every machine must trust the new key. Keep the private key on the building machine only.
- **`pack`** needs a version, from `> Version:` in `flow.md` or `--version`, and runs `kinenix validate` first: a flow with problems, or one that changed since its version was packed, is not packed. It lists the files it packed, warns about file names that often hold secrets (`*.pem`, `*.key`, `*token*`, `*password*`, ...) and about packages over 50 MB, and records the version in `.kinenix-packed.json`. The package name is the flow's folder name.
- **What is packed:** the flow folder without `.env`, `config/local.json`, `output/`, `logs/`, `tests/`, `.git/`, and the patterns in `.kinenixignore` (one per line), plus the `@shared/` subflows it calls, under `@shared/`. The manifest `kinenix-package.json` holds the name, title, version, `> Requires:`, the Kinenix version that built it, the build time, the publisher's name and key id, and the SHA-256 of every file; `kinenix-package.sig` is its signature.
- **`trust`** keeps the publishers this machine accepts in `~/.kinenix/allowed_signers`. Only a person at the machine changes it; the Hub never sends keys. `trust list` marks this machine's own key.

Exit codes: 0 done; 1 no key, or `ssh-keygen` missing or failing; 2 no or bad version, a single-file flow, a bad key or name; 4 validation problems; 7 flow or publisher not found.

### 2.11 Install a Package (`install`, `rollback`)
Kinenix 1.3.0. Copy the `.kinx` file to the machine and install it there; it needs only `kinenix` and OpenSSH, no Hub and no `kinenix-worker`.

```bash
kinenix install get_stock_data-1.3.0.kinx     # into <flows folder>/get_stock_data
kinenix install get_stock_data-1.3.1.kinx     # the new version replaces 1.3.0 in the same folder
kinenix rollback get_stock_data               # back to 1.3.0
kinenix rollback get_stock_data --to 1.2.0
```

For several machines, trust the building machine's key once on each, then copy and install every new version:

```bash
for w in worker01 worker02; do
  scp get_stock_data-1.3.1.kinx $w: && ssh $w 'kinenix install get_stock_data-1.3.1.kinx'
done
```

- **Checks, before anything changes:** the signature, by a publisher in `kinenix trust list` (`PACKAGE_UNTRUSTED` names the publisher to trust); that the package holds exactly the files its signed manifest lists, each with the signed content, and no path that leaves the flow folder (`PACKAGE_DAMAGED`); and `> Requires:` against this Kinenix (`PACKAGE_REQUIRES`).
- **Where it goes:** `<flows folder>/<name>`, so `kinenix run NAME` and triggers keep working across versions. This machine's `.env`, `config/local.json`, `output/`, and `logs/` stay. `.kinenix-deployed.json` in the folder records the version, the publisher, and when it was installed. Installing the same package again changes nothing; an older version is installed with a note that it goes back.
- **A folder that was not installed from a package** (copied by hand, a git checkout, or the folder where the flow is written) is replaced only after you answer yes, or with `--replace` in a script. The whole old folder, `.git` included, is kept in `~/.kinenix/packages/<name>/replaced-<time>/`.
- **A run going on:** the install waits for it to end, at most 30 minutes (`--wait MINUTES`, `--wait 0` not at all), then swaps the folders by renaming. If anything fails, the old version stays whole. On Windows, a file held open (Excel, an Explorer window, a terminal in the folder) blocks the swap; the install retries for about two minutes, then names the file and changes nothing. Kinenix never closes other programs.
- **Rollback:** the last 10 packages of each flow are kept in `~/.kinenix/packages/<name>/` (`KINENIX_PACKAGES_KEEP` to change). `kinenix rollback` installs the version before the current one, or `--to` a kept version, with the same checks; a package whose publisher is no longer trusted is refused.

Exit codes: 0 installed or already installed; 1 a run did not end in time, a file is in use, or `ssh-keygen` is missing; 2 you answered no, or there was no terminal and no `--replace`; 4 `PACKAGE_UNTRUSTED` or `PACKAGE_DAMAGED`; 5 `PACKAGE_REQUIRES`; 7 the file, the flow, or the version was not found.

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
