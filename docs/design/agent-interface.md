# Design: Agent Interface

Status: **approved** (2026-10-18), **revised 2026-11-12** for milestone 1.5.0. Built in two parts: the foundation went into 1.0.0 (section 10); the interface itself, the MCP server, and job dispatch are 1.5.0 (section 11).

## 1. Goal

An AI agent can use Kinenix the way a careful employee does: find out what it can do, build a flow from a `requirements.md` for a person to review, run the flows a person approved, follow a run, and read and explain the result, without guessing from text meant for people. The agents 1.5.0 is tested with are OpenClaw, Hermes, and Nanobot, with a small local model and a cloud model; Claude and other MCP clients work the same way.

Kinenix stays a complete tool without any agent: scheduled runs, the worker, and the Hub never need an AI. The agent interface is a layer on top, and the same layer serves scripts, CI jobs, and the MCP server. Conversation is the agent's job: Kinenix answers with data, the agent talks to the person.

```text
layer 3  job dispatch: the Hub starts a run on a worker            "run hello on the Raspberry Pi"
layer 2  MCP server (kinenix mcp)                                   any MCP client
layer 1  tools with a contract: JSON, exit codes, run ids, errors   <- sections 3 to 9
```

Layer 1 comes first; layers 2 and 3 only call it.

## 2. Timing

| Part | When | Why then |
| :--- | :--- | :--- |
| Foundation (section 10) | 1.0.0 (done) | Exit codes and what is promised stable cannot change after 1.0.0 without breaking users' scripts |
| Agent interface (sections 3 to 9), MCP server (section 13), job dispatch (section 14) | 1.5.0 | Everything in it is new commands, flags, and fields, which 1.x can add without breaking anything. It comes after 1.4.0, which gives Kinenix expected outputs per flow (#152) and missed runs on the Hub (#154): an agent reports those, it does not work them out |

## 3. Principles

1. **`--json` on every command.** With it, standard output holds one JSON document and nothing else; progress and logs go to standard error. Without it, the output is for people and may change in any release.
2. **Never ask.** Without a terminal, a command never waits for input. Every value comes from a flag or the environment; confirmation is section 9.
3. **One implementation.** The CLI and the MCP server call the same functions (as `kinenix hub query` and `report` already do through `kinenix_hub/query.py`). The CLI only parses arguments and prints.
4. **Times carry their offset**, for example `2026-10-18T23:00:00+07:00`.
5. **`run_id` is the public id of a run.** The worker creates it, it appears in logs, on the Hub, and in every answer. The Hub's `execution_id` is internal.
6. **Answers are data, not instructions.** Text in a run (a web page, a cell, an error message) can say anything; tools return it in fields, and the agent guide tells agents never to follow it ([threat-model.md](threat-model.md), T11).

## 4. Exit codes

| Code | Meaning | Retry? |
| :--- | :--- | :--- |
| 0 | Success | |
| 1 | The run failed for a technical reason (timeout, element not found, file locked) | Often |
| 2 | Wrong use of the command (unknown option, missing argument); argparse already uses 2 | No |
| 3 | The run stopped on a business rule (`flow.fail`): the data did not pass | No; the data needs a person |
| 4 | The flow is invalid (`kinenix validate` problems, expression errors, unknown action, `logic.break` outside a loop) | No; the flow needs fixing |
| 5 | The flow needs a newer Kinenix (`> Requires:`) | No; upgrade |
| 6 | The Hub or another service cannot be reached, or refused the key | Yes, later |
| 7 | Not found: no such flow, run id, or view | No |
| 8 | The run finished, but items or steps failed on the way (`on_error: continue` or `next_item`) | No; a person checks the failed items |
| 130 | Interrupted (Ctrl+C or SIGTERM) | |

A run that stops in `## Steps` takes the code of that failure; a failure in `## Finally` after successful steps is 1. A step with `on_error: ignore` that fails does not change the code. Built in 1.0.0 (`kinenix/exit_codes.py`); the user reference is [cli_guide.md, Exit Codes](../cli_guide.md#28-exit-codes).

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
| **Run** | `run_id`, `flow`, `worker`, `status` (`success`, `partial`, `failed`, `interrupted`, `running`, `queued`), `started`, `duration_seconds`, `items {total, done, failed}`, `failures` (list of Failure), `report_md`, `log_path`, `kinenix_version`, `on_hub` (false while the run waits in the outbox) |
| **Step** | `seq`, `section`, `step`, `action`, `status`, `started`, `duration_seconds`, `path`, `subflow`, `line`, `item`, `retries`, `error`, `output` (for `logic.loop`: `total_items_processed`, `stopped_early`) |
| **Failure** | `step`, `action`, `type` (`Business`, `Technical`), `handled` (`stopped`, `continued`, `fallback`, `next_item`, `ignored`), `message`, `root_cause`, `suggested_fix`, `path`, `subflow`, `line`, `item`, `retries`, `screenshot` |
| **Issue** (from validate) | `code`, `severity` (`error`, `warning`), `message`, `file`, `line`, `step`, `hint` |
| **Flow** | `name`, `path`, `description`, `requires`, `inputs` (from `## Variables`), `side_effects`, `last_run`, `approved` (section 12) |
| **Job** (section 14) | `job_id`, `flow`, `worker`, `vars`, `status` (`waiting for confirmation`, `confirmed`, `started`, `refused`, `expired`), `requested_by`, `confirmed_by`, `run_id` |

## 7. Tools

| Tool (CLI) | Input | Output (`data`) | Kind | Today |
| :--- | :--- | :--- | :--- | :--- |
| `kinenix capabilities` | | version, actions and their parameters, expression functions, features | read-only | `kinenix actions` (text) |
| `kinenix list` | | Flow list | read-only | text |
| `kinenix describe FLOW` | flow | Flow, with inputs and side effects | read-only | none |
| `kinenix validate FLOW` | flow | Issue list | read-only | text, exit 4 on problems |
| `kinenix run FLOW` | flow, `--var NAME=VALUE` (repeatable; `--vars JSON` stays), `--dry-run`, `--detach`, confirmation (section 9) | Run (with `--detach`: `run_id` at once) | **side effect** | runs; prints `Run <run_id>` first; exit codes of section 4 |
| `kinenix runs status RUN_ID` | run id | Run so far (from the live log) | read-only | none |
| `kinenix hub report` | flow or run id, limit | Run list | read-only | text |
| `kinenix hub logs` | flow or run id | Run with Step list | read-only | text; accepts the run id |
| `kinenix hub query` | view, filters, or SQL | rows | read-only | `--format json` |
| `kinenix hub status` | | workers, recent runs | read-only | text |
| `kinenix hub run FLOW --worker NAME` | flow, worker, `--var` | Job (`waiting for confirmation`) | **side effect**, confirmed on the Hub (section 14) | none |
| `kinenix connect` | | Hub in use and whether it answers | read-only (without a URL) | text |
| `kinenix mcp` | | an MCP server on standard input and output (section 13) | | none |
| `kinenix agent-guide` | | the agent guide, as a skill file | read-only | none |

**Side effects of a flow** are derived from its actions, so `describe` and a confirmation can say what a run will do: `email` (`email.send`), `files` (writes, moves, deletes), `web` (clicks and typing on a site), `network` (HTTP calls), `none`. Each action declares its kind in code (`side_effects`, next to `accepted_parameters`; done in 1.0.0). For `files`, `describe` and `--dry-run` also name the paths a run writes, moves, or deletes outside its bundle, so a flow from someone else cannot touch other folders unnoticed ([threat-model.md](threat-model.md), T1).

**`--dry-run`** compiles and validates the flow, resolves its config and inputs, and lists the steps and side effects it would run, without running any action. It also returns a confirmation token (section 9).

**`--detach`** starts the run in a separate process on the same machine and returns its `run_id` at once; the process writes its log as it goes, and `kinenix runs status RUN_ID` reads it. It needs no worker and no Hub, so one Ubuntu machine with an agent is enough. Runs on another machine go through job dispatch (section 14).

## 8. Error codes

Stable names; the message may change, the code may not. Each says whether retrying can help.

| Code | Meaning | Retryable |
| :--- | :--- | :--- |
| `FLOW_NOT_FOUND`, `RUN_NOT_FOUND`, `VIEW_NOT_FOUND`, `WORKER_NOT_FOUND` | Nothing by that name | No |
| `FLOW_INVALID` | Validation problems; the Issue list is in `data` | No |
| `FLOW_NOT_APPROVED` | The flow changed since a person approved it (section 12) | No; a person reviews it |
| `EXPRESSION_ERROR` | An expression cannot be read or evaluated | No |
| `REQUIRES_NEWER` | The flow needs a newer Kinenix | No |
| `BUSINESS_RULE` | A `flow.fail` stopped the run | No |
| `STEP_FAILED` | A step failed for a technical reason; `root_cause` says more | Yes |
| `STEP_TIMEOUT` | A step ran out of time | Yes |
| `CONFIRMATION_NEEDED` | A run needs a confirmation it did not get, or the token is wrong, used, or expired | No; ask the person |
| `JOB_REFUSED` | The worker does not accept this flow from the Hub (section 14) | No |
| `HUB_UNREACHABLE`, `HUB_AUTH` | The Hub cannot be reached, or refused the key | Yes / No |
| `QUERY_REFUSED` | A query that would change data, or took too long | No |
| `USAGE` | Wrong options | No |

## 9. Safety and confirmation

- Every tool is marked `read-only` or `side effect` (section 7). An agent may call read-only tools freely.
- A run is a side effect and is never started by an agent alone. Three ways to confirm, decided 2026-11-12:

| Where the run happens | How a person confirms |
| :--- | :--- |
| This machine, MCP client that can ask the user (MCP elicitation) | The MCP server asks through the client: the flow, its inputs, and its side effects, with Run and Cancel |
| This machine, any other client or the CLI | A confirmation token. `--dry-run` (MCP: `dry_run`) returns the side effects and a short token; `run` needs `--confirm TOKEN` (MCP: `confirm_token`). The token is tied to the flow's content, its inputs, and the machine, is used once, and expires after 10 minutes. The agent guide tells the agent to show the dry run to the person and wait for a yes. In a terminal, `--yes` works as today |
| Another machine (job dispatch) | On the Hub dashboard only. A run requested by an agent waits there until a person signed in to the dashboard confirms it; neither the agent nor the token can confirm it |

- The token stops an agent from skipping the dry run, and ties the confirmation to what was shown; it cannot stop an agent that misuses it. That is why runs on other machines need the dashboard.
- Agents get no extra rights: the same redaction, read-only Hub queries, and Hub credentials as people.

## 10. Foundation in 1.0.0

Only what cannot be added later without breaking anyone. All done in 1.0.0:

1. **Exit codes** of section 4 for `kinenix run`, `validate`, `connect`, and `kinenix hub ...`, written into the stability promise ([compatibility.md](../compatibility.md)).
2. **`run_id` early:** `kinenix run` prints `Run <run_id>` as its first line, and every command that takes a run id accepts the `run_id` (the Hub's `execution_id` keeps working).
3. **What is stable:** the stability promise says that exit codes, `--json` output (when it exists), the JSON Schemas, and the Hub views are stable, and that text meant for people is not.
4. **One implementation:** new commands put their logic in a function that returns data; `cli.py` only parses and prints (the rule is in `.agents/rules/architecture.md`).
5. **Side-effect kinds on actions:** every action declares its kind, so `describe` and confirmations need no change of actions later.

## 11. Milestone 1.5.0

The setup it is tested on: the Ubuntu machine runs the Hub, a local model (Ollama), and the agent; the Raspberry Pi stays a worker without AI. Small local models choose well from a short list of tools with fixed values and read a prepared `report_md`, so the tools stay few and their answers short.

In order, each usable before the next:

1. `--json` and the envelope on every command, JSON Schemas in `schemas/`, and contract tests in CI that check every `--json` answer
2. `kinenix agent-guide`: a skill file for OpenClaw, Hermes, Nanobot, and Claude that teaches the CLI with `--json` (agents that can run commands use Kinenix from here on)
3. `capabilities`, `describe`, `runs status`, `--var`, `--dry-run` with tokens, `--detach`, error codes, and flow approval (section 12)
4. `kinenix mcp` (section 13), calling the same functions
5. Job dispatch (section 14)
6. An evaluation set of agent tasks (build a flow for review, run after confirmation, explain a failure, say what did not run) with a success rate measured for at least one small local model and one cloud model, through OpenClaw, Hermes, and Nanobot

## 12. Building a flow for a person to review

An agent may write and change flows; a person decides what runs. The steps the agent guide teaches:

1. `kinenix init "Task"` and read `requirements.md` and the project's `AGENTS.md`
2. Write `flow.md`; `kinenix capabilities` lists the actions and functions
3. `kinenix validate --json` until it has no issues
4. Test against saved pages or a test config (`kinenix run --config`), never against production data or real e-mail recipients
5. Show the person the flow and the `--dry-run` result, and stop

**Approval:** `kinenix approve FLOW` (run by the person, in a terminal) records the hash of the flow and its subflows in the bundle. A run started by an agent (with a token, through MCP, or through job dispatch) refuses a flow whose files changed since then (`FLOW_NOT_APPROVED`), so a changed flow cannot run until a person has seen it. A person running `kinenix run` in a terminal is not stopped; schedules on a worker keep running the flow they were given, as today.

## 13. MCP server

`kinenix mcp` in kinenix-core, decided 2026-11-12: an MCP server over standard input and output, started by the agent on the machine where it runs. It reads the Hub over its HTTP API with the saved Hub URL and key, so it works on the Hub machine and on any machine connected with `kinenix connect`.

- Its tools are the ones in section 7, few and with short answers: read-only ones free, `run` and `hub_run` with the confirmation of section 9.
- It returns the same `data` objects as `--json`.
- An MCP server over HTTP inside the Hub, for agents on machines without Kinenix, waits until someone needs it.

## 14. Job dispatch

The Hub starts a run on a worker, decided 2026-11-12:

- **The worker asks; the Hub never calls in.** The worker keeps one long-poll request open to the Hub (`GET /api/v1/jobs/next`, held up to about 25 seconds, answered at once when a job is confirmed), with the same key it uses for telemetry. A confirmed run starts within about a second; the worker opens no port. One open request per worker is fine for tens of workers.
- **Only flows that are already on the worker.** A job names a flow and its inputs, never flow content or code. The worker runs it from its own flows folder.
- **Off until the owner turns it on.** The worker accepts jobs only when its owner allows it, and only for the flows listed (for example `kinenix-worker jobs allow hello quotes`); anything else is refused (`JOB_REFUSED`). A stolen Hub key can then start only those flows, and only after a person confirms on the dashboard.
- **Confirmed on the Hub dashboard** (section 9). A job waits as `waiting for confirmation` and expires after 30 minutes without one.
- The worker reports the run as today; the Job gets the `run_id`.
- Over plain HTTP the key crosses the network unencrypted, as telemetry does today: fine on a home or office LAN, otherwise put the Hub behind HTTPS or a VPN ([hub.md](../hub.md)).

## 15. Out of scope

- Agents changing flows and running them without a person seeing the change (section 12).
- `kinenix ask` and free-form chat inside Kinenix: the agent talks to the person (decided 2026-11-12; [ask_router.md](../ask_router.md) waits for a Kinenix agent of its own).
- Sending flow data to a cloud model from Kinenix itself. A cloud agent that the user connects sees what the tools return, which is redacted.
- WebSocket dispatch and log streaming (long polling is enough for now).

## 16. Decisions and open questions

- 2026-10-18: the agent interface comes before developer tools and includes job dispatch.
- 2026-11-03: moved to 1.5.0, with the goal of an agent that works like an employee.
- 2026-11-12:
  - **Job dispatch:** the worker long-polls the Hub, and only flows already on the worker can be started.
  - **Confirmation:** MCP elicitation, confirmation tokens, and the Hub dashboard for other machines.
  - **MCP server:** `kinenix mcp` over standard input and output.
  - **Conversation:** no `kinenix ask`; the agent talks to the person.
  - **`--detach`:** a local process, so a single machine works.
- Open: the exact list of MCP tools and their names, settled with the first agent tests (section 11, step 2).
- Open: whether `kinenix approve` is needed for flows started by a schedule after an agent changed them, or the approval check in section 12 is enough.
