# Design: Agent Interface

Status: **approved** (2026-10-18). Built in two parts: the foundation goes into 1.0.0 (section 10), the interface itself into milestone 1.1.0, before developer tools (1.2.0).

## 1. Goal

An AI agent (a general one such as OpenClaw or Claude, or a Kinenix agent built later) can use Kinenix the way a careful person does: find out what it can do, run a flow, follow the run, and read and explain the result, without guessing from text meant for people.

Kinenix stays a complete tool without any agent: scheduled runs, the worker, and the Hub never need an AI. The agent interface is a layer on top, and the same layer serves scripts, CI jobs, and the MCP server.

```text
layer 4  remote runs with confirmation (job dispatch)          "run flow hello for me"
layer 3  kinenix ask (ask router, local model)                  "did hello fail at 11 pm?"
layer 2  MCP server                                              any MCP client
layer 1  tools with a contract: JSON, exit codes, run ids, errors   <- this document
```

Layer 1 comes first; layers 2 to 4 only call it.

## 2. Timing

| Part | When | Why then |
| :--- | :--- | :--- |
| Foundation (section 10) | 1.0.0 | Exit codes and what is promised stable cannot change after 1.0.0 without breaking users' scripts |
| Agent interface (sections 3 to 9) and job dispatch | 1.1.0, after business flows have been built and tested on 1.0.0 | Everything in it is new commands, flags, and fields, which 1.x can add without breaking anything |

## 3. Principles

1. **`--json` on every command.** With it, standard output holds one JSON document and nothing else; progress and logs go to standard error. Without it, the output is for people and may change in any release.
2. **Never ask.** Without a terminal, a command never waits for input. Every value comes from a flag or the environment; confirmation is `--yes`.
3. **One implementation.** The CLI, the MCP server, and `kinenix ask` call the same functions (as `kinenix hub query` and `report` already do through `kinenix_hub/query.py`). The CLI only parses arguments and prints.
4. **Times carry their offset**, for example `2026-10-18T23:00:00+07:00`.
5. **`run_id` is the public id of a run.** The worker creates it, it appears in logs, on the Hub, and in every answer. The Hub's `execution_id` is internal.

## 4. Exit codes

| Code | Meaning | Retry? |
| :--- | :--- | :--- |
| 0 | Success | |
| 1 | The run failed for a technical reason (timeout, element not found, file locked) | Often |
| 2 | Wrong use of the command (unknown option, missing argument); argparse already uses 2 | No |
| 3 | The run stopped on a business rule (`flow.fail`): the data did not pass | No; the data needs a person |
| 4 | The flow is invalid (`kinenix validate` problems, expression errors, unknown action) | No; the flow needs fixing |
| 5 | The flow needs a newer Kinenix (`> Requires:`) | No; upgrade |
| 6 | The Hub or another service cannot be reached, or refused the key | Yes, later |
| 7 | Not found: no such flow, run id, or view | No |
| 8 | The run finished, but items or steps failed on the way (`on_error: continue` or `next_item`) | No; a person checks the failed items |
| 130 | Interrupted (Ctrl+C or SIGTERM) | |

A run that stops in `## Steps` takes the code of that failure; a failure in `## Finally` after successful steps is 1. Built in 1.0.0 (`kinenix/exit_codes.py`); the user reference is [cli_guide.md, Exit Codes](../cli_guide.md#28-exit-codes).

## 5. The envelope

Every `--json` answer has the same outer shape:

```json
{
  "schema": "kinenix/1",
  "command": "run",
  "ok": false,
  "exit_code": 3,
  "data": { "run_id": "20261018T230000-ab12", "status": "failed" },
  "error": {
    "code": "BUSINESS_RULE",
    "message": "Request R007 has no brand",
    "where": { "file": "subflows/process_one.md", "line": 8, "step": "Check Brand", "item": "R007" },
    "hint": "Check the brand of R007 in requests.csv",
    "retryable": false
  },
  "warnings": [ { "code": "REQUIRES_MISSING", "message": "Add > Requires: kinenix>=0.3.0b1" } ]
}
```

`schema` names the version of the contract. Within `kinenix/1`, fields are only added, never removed or changed in meaning.

## 6. Objects

The same objects appear in every command and in the MCP server; their fields follow the Hub data dictionary ([hub_data.md](../hub_data.md)) so that a run reads the same everywhere. Each has a JSON Schema in `schemas/`.

| Object | Main fields |
| :--- | :--- |
| **Run** | `run_id`, `flow`, `worker`, `status`, `started`, `duration_seconds`, `items {total, done, failed}`, `failures` (list of Failure), `report_md`, `log_path`, `kinenix_version` |
| **Step** | `seq`, `section`, `step`, `action`, `status`, `started`, `duration_seconds`, `path`, `subflow`, `line`, `item`, `retries`, `error` |
| **Failure** | `step`, `action`, `type` (`Business`, `Technical`), `handled` (`stopped`, `continued`, `fallback`, `next_item`), `message`, `root_cause`, `suggested_fix`, `path`, `subflow`, `line`, `item`, `retries`, `screenshot` |
| **Issue** (from validate) | `code`, `severity` (`error`, `warning`), `message`, `file`, `line`, `step`, `hint` |
| **Flow** | `name`, `path`, `description`, `requires`, `inputs` (from `## Variables`), `side_effects`, `last_run` |

## 7. Tools

| Tool (CLI) | Input | Output (`data`) | Kind | Today |
| :--- | :--- | :--- | :--- | :--- |
| `kinenix capabilities` | | version, actions and their parameters, expression functions, features | read-only | `kinenix actions` (text) |
| `kinenix list` | | Flow list | read-only | text |
| `kinenix describe FLOW` | flow | Flow, with inputs and side effects | read-only | none |
| `kinenix validate FLOW` | flow | Issue list | read-only | text, exit 4 on problems |
| `kinenix run FLOW` | flow, `--var NAME=VALUE`, `--dry-run`, `--detach`, `--yes` | Run (with `--detach`: `run_id` at once) | **side effect** | runs; prints `Run <run_id>` first; exit codes of section 4 |
| `kinenix runs status RUN_ID` | run id | Run so far (from the live log) | read-only | none |
| `kinenix hub report` | flow or run id, limit | Run list | read-only | text |
| `kinenix hub logs` | flow or run id | Run with Step list | read-only | text; accepts the run id |
| `kinenix hub query` | view, filters, or SQL | rows | read-only | `--format json` |
| `kinenix hub status` | | workers, recent runs | read-only | text |
| `kinenix connect` | | Hub in use and whether it answers | read-only (without a URL) | text |

**Side effects of a flow** are derived from its actions, so `describe` and a confirmation can say what a run will do: `email` (`email.send`), `files` (writes, moves, deletes), `web` (clicks and typing on a site), `network` (HTTP calls), `none`. Each action declares its kind in code (an attribute next to `accepted_parameters`). For `files`, `describe` and `--dry-run` also name the paths a run writes, moves, or deletes outside its bundle, so a flow from someone else cannot touch other folders unnoticed ([threat-model.md](threat-model.md), T1).

**`--dry-run`** compiles and validates the flow, resolves its config and inputs, and lists the steps and side effects it would run, without running any action.

## 8. Error codes

Stable names; the message may change, the code may not. Each says whether retrying can help.

| Code | Meaning | Retryable |
| :--- | :--- | :--- |
| `FLOW_NOT_FOUND`, `RUN_NOT_FOUND`, `VIEW_NOT_FOUND` | Nothing by that name | No |
| `FLOW_INVALID` | Validation problems; the Issue list is in `data` | No |
| `EXPRESSION_ERROR` | An expression cannot be read or evaluated | No |
| `REQUIRES_NEWER` | The flow needs a newer Kinenix | No |
| `BUSINESS_RULE` | A `flow.fail` stopped the run | No |
| `STEP_FAILED` | A step failed for a technical reason; `root_cause` says more | Yes |
| `STEP_TIMEOUT` | A step ran out of time | Yes |
| `HUB_UNREACHABLE`, `HUB_AUTH` | The Hub cannot be reached, or refused the key | Yes / No |
| `QUERY_REFUSED` | A query that would change data, or took too long | No |
| `USAGE` | Wrong options | No |

## 9. Safety

- Every tool is marked `read-only` or `side effect` (section 7). An agent may call read-only tools freely.
- A run is a side effect. Without a terminal, `kinenix run` needs `--yes`; the MCP tool asks the client for confirmation and shows the flow's side effects first.
- `--dry-run` lets an agent check a run completely before asking for that confirmation.
- Agents get no extra rights: the same redaction, read-only Hub queries, and Hub credentials as people.

## 10. Foundation in 1.0.0

Only what cannot be added later without breaking anyone:

1. **Exit codes** of section 4 for `kinenix run`, `validate`, `connect`, and `kinenix hub ...`, written into the stability promise ([compatibility.md](../compatibility.md)).
2. **`run_id` early:** `kinenix run` prints `Run <run_id>` as its first line, and every command that takes a run id accepts the `run_id` (the Hub's `execution_id` keeps working).
3. **What is stable:** the stability promise says that exit codes, `--json` output (when it exists), the JSON Schemas, and the Hub views are stable, and that text meant for people is not.
4. **One implementation:** new commands in 0.4.0b1 to 1.0.0 put their logic in a function that returns data; `cli.py` only parses and prints (the rule goes into `.agents/rules/architecture.md`).
5. **Side-effect kinds on actions:** the actions added in 0.4.0b1 declare their kind, and the existing ones get it in the same release, so `describe` and confirmations need no change of actions later.

## 11. Milestone 1.1.0

The first setup to serve: the Ubuntu machine runs the Hub, a local model (Ollama), and the agent; the Raspberry Pi stays a worker without AI. Small local models choose well from a short list of tools with fixed values and read a prepared `report_md`, so the tools stay few and their answers short.

Everything else in this document: `--json` and the envelope on every command, JSON Schemas and contract tests in CI that check every `--json` answer, `capabilities`, `describe`, `runs status`, `--var`, `--dry-run`, `--detach`, `--yes`, error codes, an agent guide shipped in the package (`kinenix agent-guide`) and usable as an OpenClaw or Claude skill, the MCP server, `kinenix ask` (finishing the ask router in [ask_router.md](../ask_router.md) on top of these tools), and an evaluation set of agent tasks run against local and cloud models.

Remote runs from a chat ("run flow hello on the Raspberry Pi") need the Hub to send work to a worker. **Job dispatch is part of 1.1.0**: the Hub sends a run to a chosen worker, the worker runs it and reports as it does today, and a person confirms every run started this way.

## 12. Out of scope

- Agents changing flows on their own and running them without a person seeing the change.
- Free-form chat inside Kinenix beyond `kinenix ask`'s fixed questions; general conversation is the agent's job.
- Sending flow data to a cloud model from Kinenix itself. A cloud agent that the user connects sees what the tools return, which is redacted.

## 13. Decisions and open questions

- Decided 2026-10-18: the agent interface is 1.1.0, before developer tools (1.2.0), and includes job dispatch.
- Open, decided when 1.1.0 starts: whether `kinenix run --detach` hands the run to the local worker (through the same path as job dispatch) or starts a background process.
