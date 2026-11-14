# Modular Project Architecture & Unattended Lifecycle

This guide documents Kinenix's **Self-Contained Project Bundle** architecture, subflow execution standards, and the complete lifecycle from development to unattended deployment.

Your bundles live in your flows folder (default `~/kinenix-flows`), outside the Kinenix repository; `kinenix init` creates them there. The layout below is the inside of one bundle, wherever it lives. See [Where your flows live](quickstart.md#2-where-your-flows-live).

---

## 1. Self-Contained Project Bundle Overview

Enterprise automation workflows often contain multiple sub-processes, data files, and external templates. To avoid path dependencies, broken references, or variable collisions, Kinenix organizes workflows into **Self-Contained Project Bundles**:

```text
flows/
├── @shared/                                # Cross-project reusable library
│   ├── web_login_sso.json                  # SSO login component
│   └── send_email.md                       # Reusable Gmail/SMTP component
│
└── accounting/                             # Department / Business Domain
    └── invoice_tax_filing/                 # 1 Self-Contained Project Bundle
        ├── flow.md                         # Main flow, the file you edit (source of truth)
        ├── config.json                     # Project-specific configuration (Auto-loaded)
        ├── .env                            # Optional local secrets (Git-ignored)
        ├── subflows/                       # Project-specific subflows
        │   ├── download_tax_pdf.json
        │   └── extract_table.json
        └── assets/                         # Local templates, configs, test data
            └── tax_template.xlsx
```

### Key Principles:
- **Portability:** All references to assets and subflows inside a project bundle use **Relative Paths** (e.g. `./assets/tax_template.xlsx`, `./subflows/extract_table.md`).
- **No Hardcoded Absolute Paths:** Workflows never depend on developer-specific paths (e.g., `C:\Users\Dev\...`), ensuring seamless portability across different machines, VMs, or operating systems.
- **Atomic Units:** A single project directory represents one coherent unit of business automation that can be developed, tested, versioned, and deployed as a standalone bundle.
- **Decoupled Settings (`config.json`):** Engine automatically auto-loads `config.json` from the flow bundle directory into `${config.*}` and top-level variables. Business users or admins can modify endpoints, email recipients, or thresholds without altering `flow.json`.
- **Local Secrets (`.env`):** Optional project-level `.env` is automatically parsed and mapped to `${env.*}` for local execution without leaking credentials to version control. One `NAME=value` per line; `export NAME=value` works too, a line starting with `#` is a comment, and so is ` # note` after a value. Put a value that holds ` #` in quotes (`NOTE='room # 5'`); a `#` without a space before it stays in the value (`PASSWORD=abc#123`). A variable already set in the environment wins over the file.

---

## 2. Calling Subflows (`flow.call`)

The `flow.call` action runs another flow (a subflow) and can use the value it returns. Write subflows in the same Markdown format as `flow.md`; `flow.call` compiles a `.md` subflow when it runs, so no `.json` file is kept next to it. Existing `.json` subflows still work, and a target without an extension (`./subflows/extract_table`) uses the `.md` file when both exist.

### 2.1 Subflow of the Bundle (`./subflows/`)

```markdown
### 3. Extract Table Data (`flow.call`)
- **flow:** ./subflows/extract_table.md
- **inputs:** {"pdf_path": "${downloaded_pdf}"}
- **output_var:** `extracted_data`
```

A subflow inside the bundle works like part of the main flow:

- **Config:** it sees the bundle's `${config.*}`. An `inputs` key named `config` is merged over it, key by key.
- **Folder:** relative paths (`./output/...`, `./assets/...`) resolve against the bundle folder, not `subflows/`. A subflow can still call another subflow by a path relative to its own file (`./other.md` from `subflows/`).
- **Data:** other values reach the subflow only through `inputs`. The subflow declares them in its `## Variables`, with defaults; `kinenix validate` reports an `inputs` key the subflow does not declare.

The `hello` example (`kinenix init demo --example hello`) calls `subflows/make_greeting.md` once per name.

### 2.2 Shared Component (`@shared/`)

```markdown
### 1. Send LINE Alert (`flow.call`)
- **flow:** @shared/notify_line.md
- **inputs:** {"message": "Invoice tax filing completed successfully.", "token_env": "LINE_TOKEN"}
```

Components in `@shared/` (or any flow file outside the calling bundle) are used by many projects, so they keep their own folder and their own `config/config.json`. Give them values with `inputs`: the component's `## Variables` is its contract, and `kinenix validate` checks the names.

When a shared component needs many values from the caller's config, `inherit_config: true` passes the caller's whole config. The caller's keys win; keys only the component defines keep the component's defaults:

```markdown
> Requires: kinenix>=0.2.0b4

### 2. Monthly Report (`flow.call`)
- **flow:** @shared/monthly_report.md
- **inherit_config:** true
```

`inherit_config` needs Kinenix 0.2.0b4 or later; the `> Requires:` line under the flow's title makes older workers refuse the flow instead of running the subflow without the config.

This ties the component to the caller's key names, so prefer `inputs` for components used by projects with different configs.

### 2.3 Variable Scope Isolation
- When `flow.call` executes a subflow, the child flow receives its own isolated `ExecutionContext`.
- Only `inputs`, the config described above, and runtime sessions (for example the active Playwright browser) are shared with the child flow.
- Variables set inside the subflow do not overwrite the caller's variables. Values come back through `flow.return` and `output_var`, or `outputs`.

### 2.4 Validation
`kinenix validate`, `kinenix run`, and the worker check every subflow whose path is fixed (not built from `${...}`): that the file exists, its own problems (unknown actions and parameters, ignored lines), and the `inputs` names. Each subflow is checked once, also when subflows call each other.

---

## 3. Flow Lifecycle & Unattended Deployment Strategy

The project bundle structure directly enables a robust deployment pipeline to unattended robot workers (`kinenix-worker`):

> **Status:** Stage 1 and the sandbox workspace in Stage 4 (`kinenix-worker run --sandbox`) are implemented. Packaging, Hub distribution, the worker cache, and WebSocket streaming (Stages 2, 3, 5) are planned. See [roadmap.md](roadmap.md). The proposal that replaces Stages 2 and 3 (signed packages that workers pull from the Hub, no WebSocket) is [design/flow-deploy.md](design/flow-deploy.md).

```text
[ Developer Machine ] -> [ Kinenix Hub ] -> [ Unattended Worker Daemon ]
  Local Dev & Test          Package & Version          Isolated Sandbox Execution
```

### Stage 1: Local Development & Verification
- Developer authors and tests the workflow locally within `flows/<dept>/<project>/`.
- Run and debug via CLI: `kinenix run <project_name>`.
- All assets remain inside `./assets/` and logs are written to central `logs/`.

### Stage 2: Packaging & Versioning
- The project bundle directory is packaged into a versioned archive (e.g. `invoice_tax_filing-1.0.0.kinx` or `.zip`).
- Any referenced `@shared/` flows are inlined by the packaging tool into the bundle, ensuring the archive is 100% self-contained.
- The package is published to **Kinenix Hub**.

### Stage 3: Distribution & Local Worker Cache
- Background daemons (`kinenix-worker`) running on target worker machines (Windows VMs, PCs, or Raspberry Pi) connect to Hub via WebSocket.
- When a job is dispatched, the worker checks its local package cache (`~/.kinenix/packages/` or `C:\ProgramData\Kinenix\packages\`).
- If the requested version is not present or updated, the worker downloads and verifies the package archive.

### Stage 4: Sandbox Workspace Isolation
- Prior to execution, the worker unpacks the project bundle into an isolated, per-job workspace directory:
  ```text
  ~/.kinenix/workspaces/job_20260911_001/
  ├── flow.md
  ├── subflows/
  └── assets/
  ```
- This ensures complete filesystem isolation, eliminates cross-job file locking or corruption, and allows clean workspace disposal after job completion.

### Stage 5: Execution & Telemetry
- Worker executes the bundle: `kinenix-worker run <bundle>`.
- Step results, business metrics, and failure screenshots are streamed in real time to the Hub dashboard.

## 4. Testing Against Saved Pages

A web flow depends on pages it does not control: a changed button, a new cookie banner, or a renamed field breaks it in production. Testing it against saved copies of those pages catches the flow's own mistakes before it touches the real site, without internet, on any machine, and in CI.

1. **Save the pages** the flow visits under `tests/pages/` in the bundle (in the browser: Save page as, "Webpage, Complete"), and remove customer data from them. Open each saved page in a browser first: a page built by JavaScript may need its scripts to show the form, and then a hand-written HTML page with the same selectors is the better test page ([batch_flows.md, rule 5](batch_flows.md#5-test-pages-for-javascript-sites-are-written-not-saved)).
2. **Point the flow at them** with a second settings file. `config/test.json` holds only the keys that change for a test run; the rest comes from `config/config.json`:
   ```json
   {
     "website_url": "tests/pages/quote_form.html",
     "input_csv": "input/test_requests.csv",
     "email": {"to": "me@example.com", "dry_run": true}
   }
   ```
   `web.open` and `web.goto` open a path that names a file in the bundle (here `tests/pages/quote_form.html`) as a local page, so the same file works on every machine.
3. **Run with it:**
   ```bash
   kinenix run tiph_quotes --config config/test.json
   ```
   Each key of the file replaces the same key of `config/config.json` for this run only; a key holding an object, such as `email`, is replaced as a whole. `--vars '{"config": {...}}'` is applied on top, for a one-off change.
4. **Check the outcome:** `kinenix run` exits with 1 for a technical failure, 3 when a business rule stopped it, and 8 when it finished with failed items ([cli_guide.md, Exit Codes](cli_guide.md#28-exit-codes)); compare the files under `output/` (rows written, failed items in the summary) with what the saved pages should give. Keep the saved pages and the test file in git with the flow, and refresh the pages when the real site changes.

A command that runs such a test and compares the results by itself (`kinenix test`) is planned for 1.2.0.
