# Kinenix Hub Guide

The Kinenix Hub (`kinenix-hub`) receives worker heartbeats and execution telemetry, stores them in a database, and serves the web dashboard with AI-assisted failure summaries. It is planned to also dispatch jobs to workers (see the [roadmap](roadmap.md)). It was called the Orchestrator before; see [Renamed from Orchestrator](#5-renamed-from-orchestrator).

---

## 1. Starting the Hub

Install it once. From PyPI (version 0.2.0b1 and later):

```powershell
pip install "kinenix[hub]"
```

From a clone of the repository, for development: `pip install -e kinenix-core -e kinenix-hub`.

```powershell
# Local only (default): dashboard at http://127.0.0.1:8080
kinenix hub

# Accept remote workers and viewers: set credentials first (sections 2 and 3)
kinenix hub --host 0.0.0.0 --port 8080
```

The Hub listens on `127.0.0.1` by default, so nothing on the network can reach it until you opt in with `--host 0.0.0.0` (or `KINENIX_HUB_HOST`). The startup banner shows the address it listens on, the URL to open in a browser, the URL workers should use (`Worker URL`, the machine's LAN address when bound to `0.0.0.0`), and whether the worker API key and dashboard password are set.

### Saved Settings (First Run)

The first time `kinenix hub` runs in an interactive terminal, it asks a few questions and saves the answers, so later starts need no flags or environment variables:

1. Allow workers on other machines to connect (binds to `0.0.0.0` instead of `127.0.0.1`)
2. Port
3. Worker API key, with hidden input; press Enter to generate one
4. Dashboard password, typed twice; press Enter to keep the dashboard localhost-only
5. Whether `kinenix run` and `kinenix-worker` on this machine send their runs to this Hub (saved in `~/.kinenix/kinenix.env`, as `kinenix connect` does)

| Command | Purpose |
| :--- | :--- |
| `kinenix hub` | Start; runs the questions on first use |
| `kinenix hub setup` | Change the saved answers (Enter keeps the current key and password) |
| `kinenix hub show-key` | Print the worker API key to copy to workers |
| `kinenix hub query` | Ask the database about runs, steps, and failures ([section 7](#7-querying-runs)) |
| `kinenix hub --no-prompt` | Never ask (services and scripts) |

The answers are stored in `~/.kinenix/hub.env` (override with `KINENIX_HUB_SETTINGS_FILE`), outside the repository. The dashboard password is stored only as a salted PBKDF2 hash; the worker API key is stored as is, because the server must compare it, so the file is made owner-readable only on Linux and macOS. Environment variables and the `--host` / `--port` flags always take precedence over the file.

`kinenix hub status` asks for the dashboard password when the server requires one and `KINENIX_HUB_DASHBOARD_PASSWORD` is not set.

On Windows, remote workers also need an inbound firewall rule for the port, and the network must be in the profile the rule applies to (run as Administrator):

```powershell
Set-NetConnectionProfile -InterfaceAlias "<adapter>" -NetworkCategory Private   # only on a trusted home or office network
New-NetFirewallRule -DisplayName "Kinenix Hub 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -RemoteAddress LocalSubnet -Action Allow -Profile Private
```

### Checking Status from the Command Line

A run has one of three statuses, on the dashboard, in `kinenix hub status`, and in the run records: **success**; **partial** (สำเร็จบางส่วน, amber): the run finished, but work items or steps failed on the way and were handled by `on_error: continue` or `next_item`, shown with what failed, for example "1 จาก 2 รายการไม่สำเร็จ"; and **failed** (the run stopped). A run that ends with failed items is never shown as a plain success.

The dashboard is optional. From a second terminal, `kinenix hub status` shows workers (status, current task, CPU, RAM, last heartbeat) and recent executions with failure summaries:

```powershell
kinenix hub status                                   # http://127.0.0.1:8080
kinenix hub status --url http://<hub-ip>:8080 --limit 20
kinenix hub logs                                     # steps of the latest execution
kinenix hub logs 54f84bd6                            # steps of one execution, by the ID shown in status
kinenix hub logs 20261028T101500-abcd                # or by the run id that kinenix run prints first
kinenix hub logs --flow "BOT FX"                     # steps of the latest run of a flow
kinenix hub report --flow "BOT FX"                   # short report of the latest run of a flow
kinenix hub report --flow invoice --limit 3          # the last three reports, newest first
kinenix hub report 54f84bd6                          # report of one execution
```

`--flow` takes the flow's name, or part of it in any case: `invoice` finds `Monthly Invoice Export`. When the text matches several flows, the command lists them so you can type more of the name.

`report` prints the run report described in [hub_data.md](hub_data.md#run-report): items done and failed, each failure with its item, step, subflow, line, and how it was handled, and the On Error and Finally results. Like `query` ([section 7](#7-querying-runs)), it reads `hub.db` on the Hub machine without a running Hub, or a Hub on another machine with `--url`. `logs` and `status` always ask a running Hub.

`logs` shows each step's name, action, status, duration, and error, plus the failed step and error of a failed run. For a failed step it shows the worker's diagnosis (what went wrong and how to fix it, for example a cookie banner covering a button) and the loop item it failed on, instead of the raw browser message; the dashboard shows the same, with the full message under "ข้อความเต็ม". The dashboard shows the same table from the "ดู Steps" button on each execution. Step output and flow variables are stored in the execution log but are not shown, because they can contain business data. Worker messages outside flow steps (heartbeat problems, service start) stay on the worker; on a Raspberry Pi service, read them with `journalctl -u kinenix-worker -f`.

It reads `KINENIX_HUB_DASHBOARD_USER` and `KINENIX_HUB_DASHBOARD_PASSWORD` from the environment, so set them to the server's values when a dashboard password is configured ([section 3](#3-dashboard-authentication)).

No CORS policy is configured: the dashboard is served from the Hub's own origin, and workers call the API directly rather than from a browser, so other websites cannot read Hub data through a visitor's browser.

### Environment Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `KINENIX_HUB_API_KEY` | *(unset)* | Shared secret workers must send in the `X-API-Key` header. See [Worker Authentication](#2-worker-authentication). |
| `KINENIX_HUB_DASHBOARD_USER` | `admin` | Username for the dashboard login. See [Dashboard Authentication](#3-dashboard-authentication). |
| `KINENIX_HUB_DASHBOARD_PASSWORD` | *(unset)* | Password for the dashboard login. |
| `DATABASE_URL` | `sqlite:///~/.kinenix/hub.db` | SQLAlchemy connection string (e.g. PostgreSQL). The default SQLite file lives in your home folder, outside the source tree, so reinstalling keeps the data. |
| `KINENIX_HUB_HOST` / `KINENIX_HUB_PORT` | `127.0.0.1` / `8080` | Bind address and port. The CLI flags `--host` / `--port` override them. Use `0.0.0.0` to accept remote connections. |
| `KINENIX_HUB_SETTINGS_FILE` | `~/.kinenix/hub.env` | Saved settings written by `kinenix hub setup`. See [Saved Settings](#saved-settings-first-run). |
| `KINENIX_HUB_VIEWS_DIR` | `~/.kinenix/hub_views` | Folder of user views (`custom_*.sql`), created at every start. See [User views](#72-user-views). |
| `KINENIX_HUB_WORKER_OFFLINE_SECONDS` | `90` | A worker with no heartbeat for this long is shown as `offline`. Keep it above three times the workers' `KINENIX_HEARTBEAT_INTERVAL`. |

---

## 2. Worker Authentication

The Hub has two independent credentials: an API key for workers (this section) and a username/password for people viewing the dashboard ([section 3](#3-dashboard-authentication)). Neither grants the other's access.

| Endpoint | Protected by |
| :--- | :--- |
| `POST /api/v1/heartbeat` | Worker API key |
| `POST /api/v1/telemetry` | Worker API key |
| `GET /api/v1/auth/worker` (key check for `kinenix connect`; records nothing) | Worker API key |
| `GET /` (dashboard page) | Dashboard login |
| `GET /api/v1/workers`, `/api/v1/executions`, `/api/v1/executions/{id}`, `/api/v1/executions/{id}/steps` | Dashboard login |
| `POST /api/v1/query`, `GET /api/v1/query/catalog`, `/api/v1/query/describe/{name}` (read-only queries, [section 7](#7-querying-runs)) | Dashboard login |
| `GET /api/v1/healthz`, `/static/*` | Public (no data) |

### 2.1 Behavior

| `KINENIX_HUB_API_KEY` | Request | Result |
| :--- | :--- | :--- |
| Set | Matching `X-API-Key` header | `200 OK` |
| Set | Missing or wrong key (from any host, including localhost) | `401 Unauthorized` |
| Unset | From localhost (`127.0.0.1` / `::1`) | Accepted (local development mode) |
| Unset | From another machine | `403 Forbidden` |

When the key is unset, the Hub still binds to the network but refuses remote writes, so a forgotten key never leaves the server open. The active mode is logged at startup.

### 2.2 Setup

1. Generate a random key:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Start the Hub with the key:

   ```powershell
   $env:KINENIX_HUB_API_KEY = "<generated-key>"
   kinenix hub
   ```

3. On every worker, connect to the Hub. `kinenix connect` asks for the key, checks it against the Hub (`GET /api/v1/auth/worker`), and saves the URL and key in `~/.kinenix/kinenix.env` only when the Hub accepts them; `kinenix run` and `kinenix-worker` on that machine then report to the Hub:

   ```powershell
   kinenix connect http://<hub-ip>:8080        # or: kinenix connect <hub-ip> (port 8080), --key <key> to skip the question
   kinenix connect                             # the Hub in use, where the setting comes from, and whether it answers
   kinenix connect --off                       # stop reporting
   ```

   `KINENIX_HUB_URL` and `KINENIX_HUB_API_KEY` in the environment (for example in a worker service's `worker.env`) and `kinenix run --hub URL` take precedence over the saved setting; `kinenix connect` warns when they do. On the Hub machine, `kinenix hub show-key` prints the key and the `kinenix connect` command for workers, and the startup banner shows the command too.

   Runs started on the Hub machine itself need no step: `kinenix hub setup` (also on the first start) asks whether to send this machine's runs to this Hub and saves `http://127.0.0.1:<port>` with the key.

4. Verify from a worker machine:

   ```powershell
   kinenix-worker ping
   ```

   `ping` reports whether the Hub is reachable and whether the key is accepted. Without kinenix-worker, send a heartbeat by hand:

   ```powershell
   curl.exe -X POST http://<hub-ip>:8080/api/v1/heartbeat `
     -H "X-API-Key: <generated-key>" -H "Content-Type: application/json" `
     -d '{\"worker_id\": \"test-worker\"}'
   ```

   A `401` response means the key is missing or does not match; a `403` means the Hub has no key configured.

Workers started with `kinenix-worker` send heartbeats on their own; see the [worker guide](../kinenix-worker/README.md#d-connect-to-the-hub).

If the Hub rejects telemetry, the worker logs a warning asking you to check `KINENIX_HUB_API_KEY`. The flow itself still completes; only the telemetry upload fails.

### 2.3 Security Notes

- **Environment variables only:** The key is read from environment variables, never from `config.json` or flow variables, so it cannot be committed to git or written into execution logs.
- **Reverse proxy:** When a reverse proxy runs on the same machine, every request appears to come from localhost. Always set `KINENIX_HUB_API_KEY` in that setup.
- **Use HTTPS across networks:** The key travels in a plain header. Put the Hub behind HTTPS (e.g. a TLS-terminating reverse proxy) when workers connect over untrusted networks.
- **Single shared key:** All workers currently share one key. Rotating it requires updating every worker.

---

## 3. Dashboard Authentication

The dashboard page and its read endpoints use HTTP Basic Auth. Browsers show a built-in login prompt when the page opens and reuse the credentials for the dashboard's API calls, so no separate login page is needed.

### 3.1 Behavior

| `KINENIX_HUB_DASHBOARD_PASSWORD` | Request | Result |
| :--- | :--- | :--- |
| Set | Correct username and password | `200 OK` |
| Set | Missing or wrong credentials (from any host, including localhost) | `401 Unauthorized` (browser shows login prompt) |
| Unset | From localhost | Accepted (local development mode) |
| Unset | From another machine | `403 Forbidden` |

### 3.2 Setup

```powershell
$env:KINENIX_HUB_DASHBOARD_USER = "admin"            # optional, defaults to admin
$env:KINENIX_HUB_DASHBOARD_PASSWORD = "<strong-password>"
kinenix hub
```

Open `http://<hub-ip>:8080` and sign in. For scripts, pass the same credentials:

```powershell
curl.exe -u admin:<strong-password> http://<hub-ip>:8080/api/v1/executions
```

### 3.3 Security Notes

- **Use HTTPS across networks:** Basic Auth sends the password encoded but not encrypted on every request.
- **Signing out:** Browsers cache Basic Auth credentials until the browser is closed; there is no logout button.
- **Single account:** There is one shared dashboard account. Per-user accounts and roles are not implemented.
- **Reverse proxy:** As with the worker key, always set the password when a reverse proxy on the same machine forwards requests.
- **Localhost-only names:** Without a key or password, the Hub answers only requests addressed to `localhost`, `127.0.0.1`, `[::1]`, or this machine's own name. A web page whose name was made to point at this machine (DNS rebinding) is refused, so it cannot read runs from your browser. Open the dashboard as `http://localhost:8080`.

---

## 4. Timestamps

- **Storage:** All timestamps are stored in UTC. Timestamps received from workers are converted using their UTC offset.
- **Workers without an offset:** Older kinenix-core releases send local time without an offset. These timestamps are treated as the Hub host's local time, which is only correct when the worker and the Hub share a time zone.
- **API output:** Every timestamp is returned in ISO 8601 with an explicit `+00:00` offset. The dashboard converts it to the viewer's local time.
- **Existing databases:** Rows written before this behavior mix worker local time and UTC. For test data, delete the SQLite file and let the Hub recreate it.

---

## 5. Renamed from Orchestrator

The Hub was called the Orchestrator. Old names keep working in 1.x, with a warning asking you to switch; Kinenix 2.0 removes them:

| Before | Now |
| :--- | :--- |
| Package `kinenix-orchestrator`, module `kinenix_orchestrator` | `kinenix-hub`, `kinenix_hub` |
| `kinenix orchestrator ...` | `kinenix hub ...` (the old command is an alias) |
| `kinenix run --orchestrator <url>` | `--hub <url>` (the old flag is an alias) |
| `ORCHESTRATOR_*` on the Hub, for example `ORCHESTRATOR_API_KEY` | `KINENIX_HUB_*`, for example `KINENIX_HUB_API_KEY` |
| `KINENIX_ORCHESTRATOR_URL`, `KINENIX_ORCHESTRATOR_API_KEY` on workers | `KINENIX_HUB_URL`, `KINENIX_HUB_API_KEY` |
| `~/.kinenix/orchestrator.env` | `~/.kinenix/hub.env` (the old file is read while the new one does not exist; `kinenix hub setup` writes the new one) |
| `kinenix_orchestrator/orchestrator.db` inside the package | `~/.kinenix/hub.db` (move the old file there to keep its data) |

To upgrade an editable install: `pip uninstall kinenix-orchestrator`, then `pip install -e kinenix-hub`.

---

## 6. Database

The Hub keeps workers and executions in one SQLite file, `~/.kinenix/hub.db` by default (`DATABASE_URL` selects another file or a PostgreSQL server). Each run is stored with every step and every failure, a short run report, and views for querying; [hub_data.md](hub_data.md) describes the tables and views and gives example queries.

### 6.1 Upgrades

A newer Hub may need more tables or columns than an existing `hub.db` has. At every start, the Hub applies the schema changes it has not applied yet and records each one in the `schema_version` table; existing data is kept. Each change runs in its own transaction, so a change that fails leaves the database as it was, and the Hub stops with the error. Nothing needs to be run by hand. The first start of Hub 0.2.0b4 also fills in the steps, failures, and run reports of the runs already stored, from their logs; on a large database this start takes longer.

A `hub.db` from Hub 0.2.0b3 or older that holds runs cannot go straight to a Hub newer than 1.0.0rc2: the Hub stops at the start with `no such column: executions.run_id`, and the data stays as it was. Start Hub 1.0.0rc2 on it once first, then upgrade.

### 6.2 WAL mode and the extra files

The SQLite database runs in WAL (write-ahead log) mode, so workers can write while the dashboard, `kinenix hub` commands, and other readers read. In this mode SQLite keeps two more files next to the database while the Hub runs:

| File | Purpose |
| :--- | :--- |
| `hub.db` | The database |
| `hub.db-wal` | Recent changes not yet copied into `hub.db` |
| `hub.db-shm` | Shared index for the WAL file |

**To back up or move the database** (for example to another machine), stop the Hub first. When the last connection closes, SQLite copies the recent changes into `hub.db` and removes the other two files, so `hub.db` alone is complete. If `hub.db-wal` is still there (for example after the machine lost power), copy all three files together; SQLite applies the log the next time it opens the database. Copying only `hub.db` while the Hub runs can miss the latest executions. Do not keep `hub.db` on a network drive; SQLite needs local file locking.

---

## 7. Querying Runs

`kinenix hub query` answers questions such as "what failed last night, and where?" from the terminal. It reads the views and tables described in [hub_data.md](hub_data.md). On the Hub machine it reads `hub.db` directly, and the Hub does not need to be running. With `--url` it asks a Hub on another machine, with the dashboard credentials (as `status` does).

```bash
kinenix hub query --list                                 # tables and views, row counts, what each answers
kinenix hub query --describe v_failures                  # columns, their meaning, and examples
kinenix hub query v_failures --since yesterday           # failures since yesterday 00:00, newest first
kinenix hub query v_runs --flow "TIPH Quotes" --status failed --limit 10
kinenix hub query v_failures --filter handled=continued --filter loop_item="R007 HONDA HR-V"
kinenix hub query "SELECT step_name, COUNT(*) AS n FROM v_failures GROUP BY step_name ORDER BY n DESC"
kinenix hub query v_steps --flow Hello --format json     # table (default), json, csv, md
kinenix hub query v_failures --since 7d --output failures.csv
kinenix hub query v_failures --url http://192.168.1.137:8080
```

| Option | Meaning |
| :--- | :--- |
| `--since` | Rows from this time: `today`, `yesterday`, `30m`, `12h`, `7d`, `2w`, or a date (`2026-10-12`) or date and time. Days and dates are local midnight on the machine that runs the command. Filters on the view's time column (`failed_at`, `started_at`, ...) |
| `--flow`, `--worker`, `--status` | `flow_name`, `worker_id`, `status` equal to the value |
| `--filter COLUMN=VALUE` | Any column equal to the value; repeat for more |
| `--limit` | Rows returned (default 50, at most 10000); the output says when more exist |
| `--format`, `--output` | `table`, `json`, `csv`, or `md`; `--output FILE` writes the rows to a file (the format follows the file extension when `--format` is not given) |
| `--expand` | Whole values instead of cut ones, and `details` columns as JSON objects in `json` |

The filters work with a view or table name. With SQL, write the conditions in the `WHERE` clause. A result with more columns than fit the terminal is printed as one block of `column  value` lines per row.

### 7.1 Safety

- The database is opened read-only, and only reading is allowed: `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `PRAGMA`, and `ATTACH` are refused.
- One statement per call; a query is stopped after 10 seconds.
- Over HTTP (`--url`), `executions.raw_log` reads as empty, because the whole execution log can hold flow variables and step outputs that the API does not show. On the Hub machine the file is readable anyway, so a local query shows it.
- Queries read SQLite only; with another `DATABASE_URL` the command reports that.

### 7.2 User Views

Save a query you ask often as a view: put one `SELECT` in a file named `custom_<name>.sql` in `~/.kinenix/hub_views/` (setting `KINENIX_HUB_VIEWS_DIR`). The Hub creates a view with the file's name at every start, so restart the Hub after adding or changing a file.

```sql
-- ~/.kinenix/hub_views/custom_failures_by_flow.sql
SELECT flow_name, COUNT(*) AS failures, MAX(failed_at) AS last_failed_at
FROM v_failures GROUP BY flow_name
```

- Names start with `custom_`, so Kinenix views (`v_`) and upgrades never overwrite them. A file with another name is reported and skipped.
- A file `custom_<name>.md` next to it documents the view: its first paragraph appears in `--list`, the whole file in `--describe`.
- A view may read Kinenix views and other user views.
- A file that fails (an SQL error, more than one statement) is logged with its file name at start, and the Hub keeps starting.
- The folder is the source of user views: when a file is removed, the Hub drops its view at the next start. Views hold no data, so nothing is lost.

---

## 8. How Machines Connect, and Troubleshooting

### 8.1 Who connects to whom

```text
kinenix run / kinenix-worker  --HTTP-->  Hub (port 8080)  <--browser--  dashboard viewers
   (any machine)                          (one machine)                 kinenix hub status/logs/report/query --url
```

- Workers and `kinenix run` always connect to the Hub; the Hub never connects to them. The only address to set is the Hub's.
- `127.0.0.1` means "this machine". It is right on the Hub machine itself (what `kinenix hub setup` saves for local runs) and wrong on any other machine, which must use the Hub's LAN address or name, for example `http://192.168.1.137:8080` or `http://hub-host.local:8080`.
- The Hub accepts other machines only when setup allowed it (`KINENIX_HUB_HOST=0.0.0.0`; the banner says `Listening on 0.0.0.0:8080 (all interfaces)`). Other machines then need the worker key to send runs and the dashboard password to read.
- A dashboard opened at `http://127.0.0.1:8080` on another computer works only through a tunnel such as a VS Code Remote-SSH port forward; without one, open the Hub's LAN address.

### 8.2 Where a machine finds its Hub

In this order, the first one set wins:

1. `kinenix run --hub URL` (one run)
2. `KINENIX_HUB_URL` and `KINENIX_HUB_API_KEY` in the environment, including a worker service's `~/.kinenix/worker.env` and a bundle's `.env`
3. `~/.kinenix/kinenix.env`, saved by `kinenix connect` or `kinenix hub setup`

`kinenix connect` without arguments shows which one is used and whether the Hub answers. A run with no Hub ends with `Hub: not connected` in its log.

### 8.3 Runs the Hub did not receive

When a run cannot reach the Hub (it is down, restarting, busy, or refuses the key), its log ends with a warning that the run is kept on this machine. The run goes to the outbox, `~/.kinenix/outbox` (next to `kinenix.env`), and is sent, oldest first, as soon as the Hub answers again: after the next run that reaches it, or with the next heartbeat of `kinenix-worker`. The Hub stores one record for each run id of a worker, so a run sent twice is stored once.

- At most 100 runs go in one send, and at most 2,000 are kept; beyond that the oldest are dropped with a warning (their log files stay on the machine).
- A run the Hub answers with any other error, such as a malformed body, would fail again: it moves to `~/.kinenix/outbox/rejected` for a person to look at.
- The files hold the same redacted data the Hub receives, readable only by their owner where the file system supports it. Deleting the folder gives up on the runs in it.
- A run with no Hub set (`Hub: not connected`) is not kept.

### 8.4 Symptoms

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| Run log ends with `Hub: not connected` | No Hub is set for this machine | `kinenix connect http://<hub>:8080`, or answer yes to the question in `kinenix hub setup` on the Hub machine |
| `Hub rejected telemetry (HTTP 401)` | The key is missing or differs from the Hub's | On the Hub, `kinenix hub show-key`; on the worker, `kinenix connect` again with that key |
| `HTTP 403` from another machine | The Hub has no worker key, so it accepts runs only from itself | On the Hub, `kinenix hub setup`, allow other machines (a key is created) |
| `Cannot find the address of '<name>'` | The name does not resolve; `.local` names need mDNS (Avahi) on both machines | Use the IP address (on the Hub: `hostname -I`), or install `avahi-daemon` on the Hub and `libnss-mdns` on the worker |
| `<name> was found, but nothing accepts connections on port 8080` | The Hub is not running, or listens on `127.0.0.1` only | On the Hub: `ss -ltnp \| grep 8080`; start `kinenix hub`, or run `kinenix hub setup` and allow other machines |
| `No answer ... a firewall may block the port` | A firewall drops the connection | On the Hub: `sudo ufw allow 8080/tcp` (Linux), or an inbound rule on Windows ([Saved Settings](#saved-settings-first-run)) |
| `kinenix connect` warns that an environment variable takes precedence | `worker.env`, `~/.bashrc`, or a bundle `.env` sets the Hub | Empty those values (then restart the worker service) to use the saved Hub |
| `kinenix hub report` or `query` is an invalid choice | The `kinenix` on the path is an older install, not the repository's | `which kinenix`; activate the repository's `.venv`, or upgrade the installed package |
| The Hub was updated but behaves as before | The running Hub still runs the old code | Restart it (`Ctrl+C` and `kinenix hub`, or `sudo systemctl restart kinenix-hub`) |

