# Hub Data Dictionary

What the Hub stores about runs, and how to query it. Written for people and AI assistants that answer questions such as "what failed last night, and where?". Start with the views; the tables behind them are listed after.

Query them with `kinenix hub query` ([hub.md, Querying Runs](hub.md#7-querying-runs)), for example `kinenix hub query v_failures --since yesterday`, or with any SQLite tool on `~/.kinenix/hub.db`. User views (`custom_*`) are added from `~/.kinenix/hub_views/`.

A test (`kinenix-hub/tests/test_data_dictionary.py`) fails when a table, view, column, or `details` key exists without a row here, or the other way round. `kinenix hub query --describe` shows this document's meanings, from a copy in the package (`kinenix-hub/kinenix_hub/hub_data.md`); copy this file there after editing it, a test checks that they are the same.

## How the data gets here

A worker sends one execution log per run when the flow ends ([logging.md](logging.md)). The Hub keeps the log whole in `executions.raw_log` and stores its facts as rows: one in `executions`, one in `step_results` per executed step (also every loop iteration, subflow steps, and On Error and Finally steps), and one in `failures` per failure (also failures the flow continued after).

- The worker removes secrets and personal data before sending ([logging.md, Redaction](logging.md#redaction)).
- Step outputs and step errors are stored at most 500 characters long, ending with `...` when cut; the full log stays in `executions.raw_log`.
- Runs from workers older than 0.2.0b4 have fewer facts: no run id, Kinenix version, work items, line, path, subflow, loop item, or retries. Their step outputs are not stored, because those workers did not redact them. Only the failure that stopped such a run has `handled = stopped`; other failed steps have an empty `handled`.
- When the Hub is upgraded, runs it already stored get their rows from `raw_log` once, at the first start.

## Conventions

- Times are UTC, stored as text `YYYY-MM-DD HH:MM:SS.ffffff`, so they sort and compare as text: `failed_at >= datetime('now', '-1 day')`.
- `section` is where a step is in `flow.md`: `steps`, `on_error` (`## On Error`), or `finally` (`## Finally`).
- `handled` is what happened after a step failed: `stopped` (the run stopped; On Error ran), `continued` (`on_error: continue`, or a step in On Error or Finally), `fallback` (`fallback_step_id` ran), `next_item` (`on_error: next_item`: the loop went on with its next item), `ignored` (`on_error: ignore`: the run went on and does not count it as a failure).
- `details` columns are JSON with a version key `v`; the views expose their keys as columns. The views exist on SQLite only.

## Views

### `v_runs`

One row per run. Answers: how many runs, which failed, success rate and duration per flow and worker, how many work items were done.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `execution_id` | Id of the run on the Hub | `53a58daa-109f-44fa-8d07-b9c0270dc9be` |
| `run_id` | Id of the run on the worker (`${run.id}`, also in log file names) | `20261012T020000-abcd` |
| `flow_name` | Flow | `TIPH Quotes` |
| `worker_id` | Worker that ran it | `rpi4` |
| `status` | `success`; `partial` (the run finished, but work items or steps failed and were handled by `on_error: continue` or `next_item`; a step with `on_error: ignore` does not count); `failed` (the run stopped); or `interrupted` (stopped on request, such as `systemctl stop`, which is not a failure) | `partial` |
| `started_at` | Start, UTC | `2026-10-11 19:00:00.000000` |
| `ended_at` | End, UTC | `2026-10-11 19:14:00.000000` |
| `duration_seconds` | Duration | `840.0` |
| `kinenix_version` | Kinenix version on the worker | `0.2.0b4` |
| `items_total` | Work items (iterations of loops with `item_label`) | `12` |
| `items_done` | Work items done | `6` |
| `items_failed` | Work items that failed; the rest were not reached | `1` |
| `step_count` | Steps executed | `48` |
| `failure_count` | Failures, also continued ones | `3` |
| `failed_step_name` | Step that failed the run | `Save Quotes` |
| `error_type` | `Technical` or `Business`, for the failure that failed the run | `Technical` |
| `error_message` | Message of the failure that failed the run | `File is open in Excel` |
| `report_md` | Short Markdown report of the run (see Run report) | `# TIPH Quotes, ...` |

### `v_failures`

One row per failure. Answers: what failed, where, on which item, how it was handled, and what to do about it.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `failure_id` | Id of the failure | `17` |
| `execution_id` | Run on the Hub | `53a58daa-...` |
| `run_id` | Run id on the worker | `20261012T020000-abcd` |
| `failed_at` | Time of the failure, UTC | `2026-10-11 19:07:42.000000` |
| `flow_name` | Flow | `TIPH Quotes` |
| `worker_id` | Worker | `rpi4` |
| `section` | `steps`, `on_error`, or `finally` | `steps` |
| `step_name` | Step that failed | `Choose Brand` |
| `action` | Its action | `web.click` |
| `step_path` | Flow, loops, conditions, and subflows down to the step | `TIPH Quotes > Each Request > process_one > Choose Brand` |
| `subflow` | Subflow the step is in, or empty | `process_one` |
| `line` | Line of the step heading in its `flow.md` | `42` |
| `loop_item` | Item of the innermost loop (from `item_label`) | `R007 HONDA HR-V` |
| `loop_index` | Its position, from 1 | `7` |
| `loop_of` | Number of items in that loop | `12` |
| `retries` | Retries made before the step gave up | `2` |
| `handled` | `stopped`, `continued`, `fallback`, `next_item`, or `ignored` | `continued` |
| `error_type` | `Technical` or `Business` | `Technical` |
| `exception` | Exception class | `TimeoutError` |
| `message` | Error message | `Timeout 30000ms exceeded waiting for option HONDA` |
| `root_cause` | Rule-based diagnosis on the worker | `Element did not appear in time` |
| `suggested_fix` | What to try | `Check the selector or raise the timeout` |
| `screenshot` | Screenshot path on the worker | `./errors/20261012T020000-abcd_step_3.png` |
| `run_status` | Status of the whole run | `failed` |

### `v_steps`

One row per executed step. Answers: slowest steps, steps that fail most, what a run did in order, which items were skipped and why.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `step_result_id` | Id of the step row | `412` |
| `execution_id` | Run on the Hub | `53a58daa-...` |
| `run_id` | Run id on the worker | `20261012T020000-abcd` |
| `flow_name` | Flow | `TIPH Quotes` |
| `worker_id` | Worker | `rpi4` |
| `seq` | Order within the run, from 1, by the time the step ended (a subflow's steps come before its `flow.call` step) | `5` |
| `section` | `steps`, `on_error`, or `finally` | `steps` |
| `step_id` | Step id in the compiled flow | `sub_step_2_1` |
| `step_name` | Step | `Choose Brand` |
| `action` | Action | `web.click` |
| `status` | `success`, `failed`, or `skipped` | `success` |
| `started_at` | Start, UTC | `2026-10-11 19:07:12.000000` |
| `duration_seconds` | Duration | `1.42` |
| `step_path` | Flow, loops, conditions, and subflows down to the step | `TIPH Quotes > Each Request > Choose Brand` |
| `subflow` | Subflow the step is in, or empty | `process_one` |
| `line` | Line of the step heading in its `flow.md` | `42` |
| `loop_item` | Item of the innermost loop | `R007 HONDA HR-V` |
| `loop_index` | Its position, from 1 | `7` |
| `loop_of` | Number of items in that loop | `12` |
| `retries` | Retries made | `0` |
| `skipped_reason` | Why a skipped step did not run | `Condition '${req.brand} is empty' not met` |
| `error` | Error of a failed step, at most 500 characters | `Timeout 30000ms exceeded` |
| `output` | Output of the step as text, at most 500 characters | `{"rows": 12}` |

### `v_flows`

One row per flow the Hub has a run of. Answers: which flows run and how many there are, how often each one ran and how its runs ended, which flows stopped running, and where each one ran last. The counts cover every run the Hub keeps; `--since` (on `last_run_at`) keeps the flows that ran since then. A flow that has never run is not here: it exists only in the flows folder of its worker (`kinenix list` on that machine).

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `flow_name` | Flow | `TIPH Quotes` |
| `run_count` | Runs of the flow | `412` |
| `success_count` | Runs with status `success` | `380` |
| `partial_count` | Runs with status `partial` | `25` |
| `failed_count` | Runs with status `failed` | `6` |
| `interrupted_count` | Runs with status `interrupted` | `1` |
| `worker_count` | Workers that ran it | `2` |
| `first_run_at` | Start of its first run, UTC | `2026-09-01 02:00:00.000000` |
| `last_run_at` | Start of its newest run, UTC | `2026-11-14 08:29:00.000000` |
| `last_status` | Status of its newest run | `partial` |
| `last_worker_id` | Worker of its newest run | `rpi4` |
| `last_execution_id` | Id on the Hub of its newest run (`v_runs.execution_id`) | `53a58daa-...` |

## Tables

### `executions`

One row per run, written when the worker sends the run.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `id` | Id of the run on the Hub | `53a58daa-...` |
| `worker_id` | Worker | `rpi4` |
| `flow_name` | Flow | `TIPH Quotes` |
| `status` | `success`; `partial` (the run finished, but work items or steps failed and were handled by `on_error: continue` or `next_item`; a step with `on_error: ignore` does not count); `failed` (the run stopped); or `interrupted` (stopped on request, such as `systemctl stop`, which is not a failure) | `partial` |
| `start_time` | Start, UTC | `2026-10-11 19:00:00.000000` |
| `end_time` | End, UTC | `2026-10-11 19:14:00.000000` |
| `duration_seconds` | Duration | `840.0` |
| `has_error` | 1 when the run failed | `1` |
| `failed_step_id` | Step that failed the run | `step_3` |
| `failed_step_name` | Its name | `Save Quotes` |
| `error_type` | `Technical` or `Business` | `Technical` |
| `exception_class` | Exception class | `PermissionError` |
| `error_message` | Error message | `File is open in Excel` |
| `screenshot_path` | Screenshot path on the worker | `./errors/step_3.png` |
| `raw_log` | The whole execution log as sent ([logging.md](logging.md)) | `{"flow_name": ...}` |
| `ai_category` | Failure category from the Hub's failure analysis, a Thai label. Empty for runs recorded from 1.2.0, which removed that analysis; read `root_cause` and `suggested_fix` of `v_failures` instead | `หาปุ่มหรือ Element ไม่พบบนหน้าเว็บ (โครงสร้างเปลี่ยน)` |
| `ai_confidence` | Its confidence, 0 to 100 (empty from 1.2.0) | `85.0` |
| `ai_summary` | Short explanation, in Thai (empty from 1.2.0) | |
| `ai_root_cause` | Likely cause, in Thai (empty from 1.2.0) | |
| `ai_suggestion` | Suggested fix, in Thai (empty from 1.2.0) | |
| `created_at` | When the Hub received the run, UTC | `2026-10-11 19:14:01.000000` |
| `details` | JSON, keys below | `{"v": 1, "run_id": ...}` |
| `run_id` | Run id on the worker; unique for each worker, so a run sent twice is stored once. Empty for runs from older workers | `20261012T020000-abcd` |

#### `executions.details`

| Key | Meaning | Example |
| :--- | :--- | :--- |
| `v` | Version of this JSON | `1` |
| `run_id` | Run id on the worker | `20261012T020000-abcd` |
| `kinenix_version` | Kinenix version on the worker | `0.2.0b4` |
| `items_total` | Work items | `12` |
| `items_done` | Work items done | `6` |
| `items_failed` | Work items failed | `1` |
| `failure_count` | Failures recorded, also those the run went on after | `2` |
| `report_md` | Run report | `# TIPH Quotes, ...` |

### `step_results`

One row per executed step.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `id` | Row id | `412` |
| `execution_id` | Run (`executions.id`) | `53a58daa-...` |
| `seq` | Order within the run, from 1 | `5` |
| `section` | `steps`, `on_error`, or `finally` | `steps` |
| `step_id` | Step id | `sub_step_2_1` |
| `step_name` | Step | `Choose Brand` |
| `action` | Action | `web.click` |
| `status` | `success`, `failed`, or `skipped` | `failed` |
| `started_at` | Start, UTC | `2026-10-11 19:07:12.000000` |
| `duration_seconds` | Duration | `31.2` |
| `details` | JSON, keys below | `{"v": 1, "line": 42, ...}` |

#### `step_results.details`

| Key | Meaning | Example |
| :--- | :--- | :--- |
| `v` | Version of this JSON | `1` |
| `line` | Line of the step heading in its `flow.md` | `42` |
| `path` | Flow, loops, conditions, and subflows down to the step | `TIPH Quotes > Each Request > Choose Brand` |
| `subflow` | Subflow the step is in | `process_one` |
| `loop` | Innermost loop item: `index`, `of`, `item` | `{"index": 7, "of": 12, "item": "R007 HONDA HR-V"}` |
| `retries` | Retries made | `2` |
| `skipped_reason` | Why a skipped step did not run | `Condition '...' not met` |
| `error` | Error of a failed step, at most 500 characters | `Timeout 30000ms exceeded` |
| `output` | Output as text, at most 500 characters (not for runs from workers older than 0.2.0b4) | `{"rows": 12}` |

### `failures`

One row per failure, also failures the flow continued after, so a run that succeeded can still report failed items. A `flow.call` step whose subflow failed has no row of its own: the failure is the subflow step's.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `id` | Row id | `17` |
| `execution_id` | Run (`executions.id`) | `53a58daa-...` |
| `step_result_id` | The failed step (`step_results.id`); empty when the run failed before any step, for example a flow that needs a newer Kinenix | `415` |
| `failed_at` | Time of the failure, UTC | `2026-10-11 19:07:42.000000` |
| `flow_name` | Flow, copied from the run | `TIPH Quotes` |
| `worker_id` | Worker, copied from the run | `rpi4` |
| `step_name` | Step | `Choose Brand` |
| `action` | Action | `web.click` |
| `error_type` | `Technical` or `Business` | `Technical` |
| `handled` | `stopped`, `continued`, `fallback`, `next_item`, or `ignored` | `continued` |
| `message` | Error message | `Timeout 30000ms exceeded` |
| `details` | JSON, keys below | `{"v": 1, "exception": ...}` |

#### `failures.details`

| Key | Meaning | Example |
| :--- | :--- | :--- |
| `v` | Version of this JSON | `1` |
| `step_id` | Step id | `step_1` |
| `section` | `steps`, `on_error`, or `finally` | `steps` |
| `exception` | Exception class | `TimeoutError` |
| `root_cause` | Rule-based diagnosis on the worker | `Element did not appear in time` |
| `suggested_fix` | What to try | `Check the selector` |
| `path` | Flow, loops, conditions, and subflows down to the step | `TIPH Quotes > Each Request > process_one > Choose Brand` |
| `subflow` | Subflow the step is in | `process_one` |
| `line` | Line of the step heading | `42` |
| `loop` | Innermost loop item: `index`, `of`, `item` | `{"index": 7, "of": 12, "item": "R007 HONDA HR-V"}` |
| `retries` | Retries made | `2` |
| `screenshot` | Screenshot path on the worker | `./errors/step_1.png` |
| `on_error` | For the failure that stopped the run: each On Error step with `step_name`, `action`, `status` | `[{"step_name": "Email Error", "action": "email.send", "status": "success"}]` |

### `workers`

One row per worker, updated by its heartbeats.

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `id` | Worker id (`KINENIX_WORKER_ID`, default the host name) | `rpi4` |
| `name` | Display name | `Raspberry Pi 4` |
| `ip_address` | Address it reported | `192.168.1.50` |
| `os_info` | Operating system | `Linux 6.1` |
| `status` | `online` or `busy` as last reported; shown as `offline` when heartbeats stop | `online` |
| `current_task` | Flow it is running, or empty | `TIPH Quotes` |
| `cpu_percent` | CPU use | `12.5` |
| `ram_usage` | Memory use | `1.2 / 8 GB` |
| `last_heartbeat` | Last heartbeat, UTC | `2026-10-12 01:59:30.000000` |

### `schema_version`

Schema changes applied to this database ([hub.md, Upgrades](hub.md#61-upgrades)).

| Column | Meaning | Example |
| :--- | :--- | :--- |
| `version` | Migration number | `2` |
| `name` | What it changed | `run records: executions.details, step_results, failures` |
| `applied_at` | When, UTC, ISO 8601 | `2026-10-14T06:50:28+00:00` |

## Run report

Each run gets a short Markdown report in `executions.details.report_md` (`v_runs.report_md`), for people, e-mail, and AI. Times are the worker's local time. `kinenix hub report --flow NAME` prints the report of a flow's latest run.

```markdown
# TIPH Quotes, 2026-10-12 02:00 +07:00 (failed)
- Worker: rpi4, Kinenix 0.2.0b4, duration 14 min
- Items: 6 of 12 done, 1 failed, 5 not reached
- Failed: R007 HONDA HR-V at "Choose Brand" (subflow process_one, line 42, after 2 retries), continued: Timeout 30000ms exceeded
- Failed: "Save Quotes" (line 60), run stopped: File is open in Excel
- On Error: Capture Screen succeeded, Email Error succeeded
- Finally: Close Browser succeeded
```

At most 10 failures are listed; the rest are counted. A run without failures says `- No failures`.

## Example questions

```sql
-- How many flows ran in the last 30 days, and how did each one end last time?
SELECT flow_name, run_count, last_status, last_run_at, last_worker_id
FROM v_flows WHERE last_run_at >= datetime('now', '-30 days') ORDER BY flow_name;

-- What failed since yesterday, and where?
SELECT failed_at, flow_name, worker_id, step_path, loop_item, handled, message
FROM v_failures WHERE failed_at >= datetime('now', '-1 day') ORDER BY failed_at;

-- Success rate and average duration per flow over the last 7 days
SELECT flow_name, COUNT(*) AS runs, AVG(status = 'success') AS success_rate, AVG(duration_seconds) AS avg_seconds
FROM v_runs WHERE started_at >= datetime('now', '-7 days') GROUP BY flow_name;

-- Steps that fail most
SELECT flow_name, step_name, action, COUNT(*) AS failures
FROM v_failures GROUP BY flow_name, step_name, action ORDER BY failures DESC LIMIT 10;

-- Slowest steps on average
SELECT flow_name, step_name, AVG(duration_seconds) AS avg_seconds, COUNT(*) AS runs
FROM v_steps WHERE status = 'success' GROUP BY flow_name, step_name ORDER BY avg_seconds DESC LIMIT 10;
```
