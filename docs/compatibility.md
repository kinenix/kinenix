# Compatibility

What Kinenix promises to keep working for all of 1.x, what may still change, and how to upgrade. It applies to `kinenix`, `kinenix-hub`, and `kinenix-worker`, which are released together with one version.

## 1. Version numbers

Kinenix follows [semantic versioning](https://semver.org) from 1.0.0:

| Release | Example | What it may contain |
| :--- | :--- | :--- |
| Patch | 1.0.1 | Bug fixes only |
| Minor | 1.1.0 | New actions, parameters, commands, options, columns, and fields; deprecations with a warning |
| Major | 2.0.0 | Removal of what was deprecated, and other changes that break the promise below |

A flow, a script, or a Hub query that works on 1.0.0 keeps working on every later 1.x version, except where it relied on a bug.

## 2. Stable for all of 1.x

| Area | What stays the same | What a minor release may add |
| :--- | :--- | :--- |
| `flow.md` syntax | Sections (`## Variables`, `## Steps`, `## On Error`, `## Finally`), step headings, step keys, `${...}` expressions and their functions, conditions with `and` / `or` / `not`, `> Requires:` ([flow_markdown_spec.md](flow_markdown_spec.md)) | New functions, operators, and step keys |
| Actions | Action names, parameter names, the meaning of their values and defaults, and the shape of what they return in `output_var` ([actions_reference.md](actions_reference.md)) | New actions, new optional parameters, new fields in returned objects |
| Project bundles | `flow.md`, `config/config.json`, `.env`, `subflows/`, `assets/`, and `kinenix run --config` ([project_bundles.md](project_bundles.md)) | New optional files |
| CLI | Command names, options, and arguments of `kinenix` and `kinenix-worker` ([cli_guide.md](cli_guide.md)) | New commands and options |
| Exit codes | The codes and their meanings ([cli_guide.md, Exit Codes](cli_guide.md#28-exit-codes)) | New codes for new situations only, never a new meaning for an existing code |
| Run id | `kinenix run` prints `Run <run_id>` as its first line; the same id is `${run.id}`, is part of the log file names, and is accepted by `kinenix hub logs` | |
| Execution logs | The JSON format of a run's log ([logging.md](logging.md), `schemas/execution_log.schema.json`) | New fields |
| Hub views | `v_runs`, `v_failures`, `v_steps`: their names, columns, and the meaning of each column ([hub_data.md](hub_data.md)) | New views and columns |
| Hub API | The `/api/v1/` endpoints that workers and `kinenix hub` use, and the `X-API-Key` header | New endpoints and fields |
| Settings | Environment variables (`KINENIX_*`, `DATABASE_URL`) and the keys of `~/.kinenix/kinenix.env` and `~/.kinenix/hub.env` | New variables and keys |

`--json` output and its JSON Schemas join this list when they arrive in 1.5.0 ([design/agent-interface.md](design/agent-interface.md)): within the schema version `kinenix/1`, fields are only added.

## 3. Not covered: may change in any release

- **Text meant for people:** messages, warnings, tables of `kinenix hub status` and `report`, console log lines, and the Hub dashboard. Scripts and AI assistants should read exit codes, the run id, the Hub views, and later `--json`, not this text.
- **The run id's format:** treat it as an opaque string; do not parse the date out of it.
- **Where logs are written by default:** the run prints the path at the end, and `--log-dir` sets it.
- **The Hub's tables:** query the views, which stay the same while the tables under them may change.
- **The compiled JSON of `kinenix compile`:** it is for inspection; `flow.md` is the only input Kinenix reads.
- **Python modules:** importing `kinenix`, `kinenix_hub`, or `kinenix_worker` from your own Python code is not a supported interface.
- **Kinenix Studio** (paused) and the **ask router** (work in progress).

## 4. Experimental

These work, but their behavior may change in a minor release; the CHANGELOG says when:

- The Hub's AI failure analysis (`CENTRAL_LLM_URL`, `POST /api/v1/executions/{id}/reanalyze`). It is being developed further, so a local model explains why a run failed; it joins section 2 in the minor release that finishes it.
- `ai.decide`, which depends on a specific central model server (`CENTRAL_LLM_URL`).
- The answers of `ai.prompt` and `ai.extract`: their parameters are stable, but what a model answers depends on the model.

## 5. Deprecation and removal

Something that will be removed is first deprecated in a minor release. From then on it still works for all of 1.x, warns when it is used (`kinenix validate` prints `Deprecated:` without failing, and every run logs it), and is listed under Deprecated in the [CHANGELOG](../CHANGELOG.md) with what to use instead. It is removed only in the next major release.

Deprecated in 1.0.0, removed in 2.0: `on_error: retry`, `fallback_step_id`, `kinenix export-md`, and the Orchestrator names (`kinenix orchestrator`, `--orchestrator`, `ORCHESTRATOR_*`, `KINENIX_ORCHESTRATOR_*`, `~/.kinenix/orchestrator.env`).

## 6. Upgrading

- **Hub first, then workers.** A Hub accepts runs from workers of the same or an older 1.x version. An older Hub also accepts a newer worker, but it ignores fields it does not know.
- **The Hub database upgrades itself** at start (`kinenix_hub/migrations.py`), with no data lost. A database is not downgraded: copy `~/.kinenix/hub.db` before an upgrade if you may go back to an older version.
- **Flows that need a newer Kinenix** say so with `> Requires: kinenix>=1.1.0` under the title. An older worker then refuses the flow with exit code 5 instead of running it wrongly, and `kinenix validate` reports a flow that uses newer features without it.
- **Python:** Kinenix 1.0 supports Python 3.12 and later. 3.12 reaches its end of life in October 2028. A minor release may stop supporting a Python version that has reached its end of life; the CHANGELOG says so, and `pip` keeps installing the last Kinenix that supports it.
