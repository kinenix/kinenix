# kinenix-worker

The unattended robot worker daemon and edge execution engine for **[Kinenix](https://github.com/kinenix/kinenix)**, an open-source, local AI-native RPA framework in Python.

## Install from PyPI

```bash
pip install "kinenix[worker]"
kinenix install-browsers          # Playwright Chromium, needed for web actions
kinenix-worker info
```

Requires Python 3.12 or newer. To report to a Kinenix Hub, run `kinenix connect http://<hub-ip>:8080` (section 3D). The Raspberry Pi quickstart below installs from the repository instead and also sets up a systemd service.

---

## 1. Overview

`kinenix-worker` is designed to run unattended automation workloads on edge hardware, dedicated worker machines, virtual machines, and low-power devices such as **Raspberry Pi 4 Model B**.

### Key Capabilities
- **Lightweight Execution:** Minimal overhead with direct integration into `kinenix-core`.
- **Separate copy per run (`--sandbox`):** Runs a bundle from its own copy in `~/.kinenix/workspaces/<job_id>`, so a run does not change the original folder. It is not isolation: the flow keeps the rights of the user who runs the worker.
- **Hardware Telemetry:** Gathers CPU, memory, architecture, and platform metrics at runtime.
- **Structured JSON Auditing:** Stores hierarchical execution traces and error telemetry locally.

---

## 2. Raspberry Pi 4 Model B (ARM64) Quickstart

### Prerequisites
- **Hardware:** Raspberry Pi 4 Model B (Rev 1.4 or compatible) with 2GB, 4GB, or 8GB RAM.
- **Operating System:** Raspberry Pi OS (64-bit Debian bookworm / bullseye) or Ubuntu Server ARM64.
- **Network:** Internet access for initial setup and downloading benchmark web pages.

### Automated Setup
Clone the repository and run the setup script:

```bash
# 1. Clone repository onto Raspberry Pi
git clone -b dev https://github.com/kinenix/kinenix.git kinenix
cd kinenix

# 2. Run the setup script (it is already executable; do not chmod it, or git pull will see a local change)
./kinenix-worker/scripts/setup_rpi.sh
```

The script automatically:
1. Installs required Linux shared libraries for Chromium on aarch64.
2. Creates a Python 3.12+ virtual environment (`.venv`).
3. Installs `kinenix-core` and `kinenix-worker` in editable mode.
4. Installs the ARM64 Playwright Chromium browser.
5. Verifies the installation with `kinenix-worker info`.
6. Installs and starts the `kinenix-worker` systemd service (see [section 3E](#e-run-as-a-systemd-service)). Pass `--no-service` to skip it.

---

## 3. Running Workflows on Raspberry Pi

### A. Activate Environment
```bash
source .venv/bin/activate
```

### B. Verify System Information
```bash
kinenix-worker info
```

Expected output on Raspberry Pi 4:
```text
Kinenix Worker System Information:
-------------------------------
  os: Linux
  os_release: 6.6.x+rpt-rpi-v8
  machine: aarch64
  processor: aarch64
  python_version: 3.13.x
  cpu_count: 4
  memory_total_mb: 3884.2
  memory_available_mb: 3200.1
  memory_used_percent: 17.6
  worker_id: raspberrypi
  hub_url: (not set)
  hub_api_key: (not set)
```

### C. Run an Example Flow
```bash
kinenix init demo --example quote_requests
kinenix-worker run demo
```

To run from a separate copy of the bundle (the original folder stays unchanged):
```bash
kinenix-worker run demo --sandbox
```

### D. Connect to the Hub

Connect once; the command asks for the Hub's worker key (on the Hub: `kinenix hub show-key`), checks that the Hub accepts it, and saves both in `~/.kinenix/kinenix.env`, which the worker and `kinenix run` read:

```bash
kinenix connect http://192.168.1.132:8080
kinenix connect                 # the Hub in use and whether it answers
kinenix connect --off           # stop reporting
```

Environment variables still work and take precedence over the saved setting (see the [Hub guide](https://github.com/kinenix/kinenix/blob/main/docs/hub.md) for the server side):

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `KINENIX_HUB_URL` | *(unset: no reporting)* | Hub base URL, for example `http://192.168.1.132:8080` |
| `KINENIX_HUB_API_KEY` | *(unset)* | The Hub's worker key; the same variable holds the same value on the Hub |
| `KINENIX_WORKER_ID` | host name | Name shown on the dashboard and attached to every execution |
| `KINENIX_HEARTBEAT_INTERVAL` | `30` | Seconds between heartbeats while a worker command runs |

```bash
export KINENIX_HUB_URL=http://192.168.1.132:8080
export KINENIX_HUB_API_KEY="<key>"
export KINENIX_WORKER_ID=rpi4-01

kinenix-worker ping          # checks reachability and the API key; exit code 1 on failure
kinenix-worker run demo
```

With the URL set:

- Every run sends its execution log to the Hub. A local copy is also written to `logs/` of the flow's project (or its git repository); `--log-dir` chooses another folder.
- Every run reports the worker as busy while the flow runs and online when it finishes.
- Every command that runs flows (`run`, `watch`, `schedule`, `daemon`) also sends a heartbeat every `KINENIX_HEARTBEAT_INTERVAL` seconds, including during long flows. The dashboard shows the worker as offline when heartbeats stop.
- If the Hub is unreachable, flows still run. The worker logs one warning, then logs again when the connection recovers.

### E. Run as a systemd Service

The service keeps `kinenix-worker daemon` running in the background, starts it at boot, and restarts it within 10 seconds if it stops. It runs as the user who installed it. While it runs, the worker sends heartbeats and shows as online in the Hub. It needs systemd (Ubuntu, Raspberry Pi OS, and most Linux systems); on Windows, start the worker with Task Scheduler, on macOS with launchd (the command prints an example).

**Installed with pip** (`pip install "kinenix[worker]"` in a virtual environment, or pipx): run as your normal user (not root):

```bash
kinenix-worker service install              # install or update, then start
kinenix-worker service install --dry-run    # only print the unit file it would write
kinenix-worker service uninstall            # stop and remove the service
```

The service runs the `kinenix-worker` of the environment you ran the command from, in your flows folder (`kinenix flows-dir`, default `~/kinenix-flows`), so triggers can name flows by their folder name. `--working-dir` chooses another folder, against which relative paths in `triggers.json` resolve. After an upgrade, or after moving or recreating the virtual environment, run `kinenix-worker service install` again: it rewrites the unit. sudo is used only to write `/etc/systemd/system/kinenix-worker.service` and to run `systemctl`. If drop-in files in `/etc/systemd/system/kinenix-worker.service.d/` override the unit (for example one written by hand before this command existed), it names them and how to remove them; it does not remove them itself.

**A clone of this repository:** `setup_rpi.sh` installs the service. To install or update it on an existing setup, run as your normal user:

```bash
./kinenix-worker/scripts/install_service.sh              # calls kinenix-worker service install --working-dir <repository>
./kinenix-worker/scripts/install_service.sh --uninstall
```

It runs the service from the repository folder, so relative flow paths such as `flows/examples/quote_requests` work.

`systemctl stop` lets a running flow finish its step and run `## Finally` (up to 60 seconds) before the worker exits.

It reads two files in `~/.kinenix/`, creating them if they do not exist (existing files are never overwritten):

| File | Contents |
| :--- | :--- |
| `worker.env` | `KINENIX_HUB_URL`, `KINENIX_HUB_API_KEY`, `KINENIX_WORKER_ID` as `export` lines; owner-readable only. Leave the Hub lines empty to use the Hub saved by `kinenix connect`; values set here take precedence over it. Also put the secrets your flows read here, for example `GMAIL_USER` and `GMAIL_APP_PASSWORD` for `email.send`: the service does not see variables set in your shell. Add `source ~/.kinenix/worker.env` to `~/.bashrc` to use the same values in your shell. |
| `triggers.json` | Triggers for the daemon. The default `{"triggers": []}` runs no flows and only sends heartbeats. |

**Your own flows** belong in your flows folder, `~/kinenix-flows`, not in this repository (see [Where your flows live](https://github.com/kinenix/kinenix/blob/main/docs/quickstart.md#2-where-your-flows-live)). Keep them in a private git repository and clone it on the Pi:

```bash
git clone git@github.com:<you>/kinenix-flows.git ~/kinenix-flows     # your private repository
cd ~/kinenix-flows && git pull                                        # later, to update the flows
```

A trigger can then name a flow by its folder name; the worker looks it up in the flows folder (or in `KINENIX_FLOWS_DIR`). Paths still work too, relative to the folder the service runs in.

Example `triggers.json`:

```json
{
  "triggers": [
    { "type": "scheduler", "flow": "get_stock_data", "cron": "0 8 * * 1-5" },
    { "type": "scheduler", "flow": "flows/examples/bot_fx_rate", "cron": "0 8 1 * *" },
    { "type": "file_watcher", "flow": "invoice_check", "watch_dir": "/home/pi/inbox", "pattern": "*.xlsx" }
  ]
}
```

A scheduler runs either every `interval_seconds` or, when `cron` is set, at the minutes matching a five-field cron expression in the Pi's local time (`minute hour day-of-month month day-of-week`, Sunday is 0 or 7):

| `cron` | Runs |
| :--- | :--- |
| `0 8 1 * *` | 08:00 on the 1st of every month |
| `30 7 * * 1-5` | 07:30 Monday to Friday |
| `*/15 * * * *` | Every 15 minutes |
| `0 9 1,15 * *` | 09:00 on the 1st and 15th |

An invalid expression stops the daemon at startup with the field that is wrong.

A scheduler with `interval_seconds` runs once as soon as the daemon starts, then every interval, so every restart runs it again. Add `"run_at_start": false` to wait one interval before its first run; for a fixed time of day, use `cron` instead:

```json
{ "type": "scheduler", "flow": "cleanup", "interval_seconds": 21600, "run_at_start": false }
``` Check the Pi's time zone with `timedatectl` (set it with `sudo timedatectl set-timezone Asia/Bangkok`).

At start, the log shows each trigger and when it runs first, then a line each time one fires:

```text
[2026-11-11 09:00:00,120] [INFO] Starting scheduler on flow 'soak-hello' every 1800.0s, first run now
[2026-11-11 09:00:00,121] [INFO] Starting scheduler on flow 'bot_fx_rate' cron '0 8 * * *', next run 2026-11-12 08:00
[2026-11-11 09:00:00,122] [INFO] Started 2 triggers in background daemon.
[2026-11-11 09:00:00,130] [INFO] Scheduler triggering flow: soak-hello at 2026-11-11T09:00:00.125311
```

Set `KINENIX_WORKER_LOG_LEVEL=WARNING` in `worker.env` to keep only warnings and errors from the worker itself; the output of each run does not change.

| Task | Command |
| :--- | :--- |
| Apply changes to `worker.env` or `triggers.json` | `sudo systemctl restart kinenix-worker` |
| Status | `systemctl status kinenix-worker` |
| Follow logs | `journalctl -u kinenix-worker -f` |
| Stop until next boot | `sudo systemctl stop kinenix-worker` |
| Update after an upgrade or a venv move | `kinenix-worker service install` |
| Remove the service | `kinenix-worker service uninstall` (a clone: `./kinenix-worker/scripts/install_service.sh --uninstall`) |

Jobs sent from the Hub are not supported yet; each worker runs the triggers in its own `triggers.json`.

---

## 4. CLI Reference

```text
usage: kinenix-worker [-h] [--version] {info,ping,run,watch,schedule,daemon,service} ...

positional arguments:
    info      Display worker machine hardware, architecture, and runtime stats
    ping      Check the connection and API key to the Hub (KINENIX_HUB_URL)
    run       Execute a flow or project bundle on this worker
    watch     Watch a directory and automatically trigger a flow when new files appear
    schedule  Execute a flow on an interval (--interval) or a cron expression (--cron "0 8 1 * *")
    daemon    Run multi-trigger daemon using a configuration file
    service   Install or remove the systemd service (Linux): service install [--working-dir DIR] [--dry-run], service uninstall

options:
  --version, -v
```

### `kinenix-worker run` Options
- `flow_path`: Flow name, project bundle directory, or path to a `flow.md`.
- `--sandbox`: Run from a separate copy of the bundle in `~/.kinenix/workspaces/<job_id>`. The flow's outputs stay in that copy; its `.env` files are deleted when the run ends. Not isolation: the flow has the same rights as without it.
- `--vars`: JSON string of variables to override.
- `--log-dir`: Write the local JSON execution log to this directory instead of `logs/` of the flow's project. Telemetry to the Hub does not depend on it.
