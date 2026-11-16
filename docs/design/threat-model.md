# Design: Threat Model

Status: **reviewed** (2026-10-29). It covers kinenix-core, kinenix-worker, and kinenix-hub as of 1.0.0rc1. Studio (paused, not published) is out of scope. The code and security review for 1.0.0 (`docs/roadmap.md`) checks the code against this document. Every finding is fixed or moved to a milestone (section 6).

## 1. What Kinenix protects

| Asset | Where it lives |
| :--- | :--- |
| Credentials of the flows: passwords, tokens, SMTP accounts | The bundle's `.env` and the environment of the worker |
| Kinenix credentials: the worker key, the dashboard password | `~/.kinenix/kinenix.env` (workers), `~/.kinenix/hub.env` (Hub; the password only as a PBKDF2 hash) |
| Business data: inputs, outputs, values read from web pages | The bundle's folders, run logs, failure screenshots, the Hub database `~/.kinenix/hub.db` |
| Correct run records | The Hub database; reports, `kinenix hub query`, and later AI agents read them |
| The machines: worker and Hub | Kinenix runs with the rights of the user who starts it |
| The published packages | GitHub Actions to PyPI |

## 2. How the parts trust each other

```text
flow author / AI assistant --writes--> flow.md, config, subflows   (a flow is code)
                                            |
                                   worker runs it as the user --> files, web sites, email, HTTP, local AI
                                            |
                         telemetry and heartbeats over HTTP, worker key (X-API-Key)
                                            v
                                          Hub --> hub.db
                                            ^
            people: dashboard and kinenix hub (Basic Auth); later AI agents through the same tools
```

**Assumptions:**
- **A flow is code.** Running a flow is like running a script: it can do whatever its actions can do, with the user's rights. Whoever can change `flow.md`, `config/`, or `subflows/` controls the worker. Kinenix does not sandbox flows. It evaluates expressions without `eval` and runs only registered actions, so a flow cannot run arbitrary Python.
- **The worker and Hub machines and their user accounts are trusted.** An attacker with that account is out of scope.
- **The LAN is partly trusted:** other devices on it can listen to and send traffic.
- **Holders of the worker key are trusted** to send runs, not to read them. Reading needs the dashboard password, or localhost when no password is set.

## 3. Threats

Each row: the threat, what protects against it today, the gap, and the proposal with its milestone.

| ID | Threat | Protection today | Gap | Proposal | When |
| :--- | :--- | :--- | :--- | :--- | :--- |
| T1 | A flow from someone else, or written by an AI assistant, does harm: deletes or sends files, sends email, submits web forms | No `eval`; only registered actions; `kinenix validate` reports unknown actions and parameters; every action declares its side effects (`kinenix actions`); flows are kept in git and reviewed | Nothing shows a flow's side effects before it runs; relative paths with `..` and absolute paths reach any folder of the user | `kinenix describe` and `--dry-run` list side effects before a run, including the files a run writes, moves, or deletes outside the bundle (design/agent-interface.md). No warning in `kinenix validate`: flows often write to shared folders on purpose, and frequent warnings get ignored (decided 2026-10-29) | 1.1.0 |
| T2 | Secrets reach logs, the Hub, or screenshots | The Redactor (`engine/redaction.py`) hides environment values with secret-like names, secret-like keys, `key=value` pairs in text, Thai ID and card numbers, before a log is written or sent; `web.type` has `secret: true`; key files are `0600` | The pattern misses common names such as `PIN`, `OTP`, and `PASSCODE`; failure screenshots are not redacted and may show personal data | Add `pin`, `otp`, `passcode` to the secret names. The security guide says that screenshots and logs hold business data | Names: done (rc1). Guide: after 1.0 |
| T3 | Someone on the LAN reads the worker key or the dashboard password, which travel over plain HTTP, and then sends fake runs or reads all runs | The Hub binds to localhost by default; other machines need the key and the password; `compare_digest`; PBKDF2 hash of the password; `hub.md` advises HTTPS through a reverse proxy | No built-in HTTPS; one key shared by all workers, so one worker cannot be revoked alone | A tested HTTPS recipe (Caddy or nginx) in the security guide; keys per worker | Guide: after 1.0. Per-worker keys: later |
| T4 | A web page opened on the Hub machine reads a localhost-only Hub through DNS rebinding: its own name resolves to 127.0.0.1, so the browser's requests come from localhost, which needs no password | Localhost-only mode is the default and needs no password | The Hub does not check the `Host` header | When a request gets in only because it comes from this machine, its `Host` must be `localhost`, `127.0.0.1`, `[::1]`, or the machine's own name; requests with a key or password are not affected | Done (rc1) |
| T5 | `kinenix hub query` changes or deletes data, or a heavy query blocks the Hub | Read-only connection, an SQLite authorizer that allows reading only, a time limit, dashboard auth on the API; names in SQL come from the database (CodeQL) | None known | Keep the tests that try writes, PRAGMA, and ATTACH | Done |
| T6 | File paths leave their folder: a zip entry such as `../../x`, a user view name, a subflow path | Zip entries are checked against the destination; user views must match `custom_\w+`; relative paths resolve from the bundle | Paths in flows may leave the bundle by design (see T1) | As T1 | As T1 |
| T7 | Data from a web page or a worker runs as script in the dashboard (XSS) | Every value from a worker is escaped (`escapeHtml`); CodeQL scans the JavaScript | The dashboard loads Tailwind as a script from `cdn.tailwindcss.com`, a third party that could then read every run shown; without internet the dashboard has no styles | Ship the dashboard's CSS in the package, and add a Content-Security-Policy that allows only its own scripts | 1.1.0 (decided 2026-10-29) |
| T8 | A worker with the key sends false or very large runs, or uses another worker's name | The key is required for writes from other machines | No size limit on telemetry; `worker_id` is not tied to the key | A size limit on telemetry; keys per worker (T3) | 1.1.0 |
| T9 | Business data leaves the machine without the user meaning it to | Local models by default (`ai.prompt`, `ai.extract` with Ollama); email and HTTP only through actions written in the flow | `ai.decide` sends data to the SystemOne server set in the flow, which may be a remote server | The security guide lists every action and setting that sends data out | Guide: after 1.0 |
| T10 | A compromised dependency, GitHub Action, or release | pip-audit, bandit, zizmor, and CodeQL in CI and weekly; Dependabot; actions pinned to commits; Trusted Publishing to PyPI with attestations; release environments that need approval | Dependencies have only lower bounds, so a new major version reaches users untested | Upper bounds for dependencies whose major versions have broken Kinenix before; an SBOM with each release | Later |
| T11 | An AI assistant or agent is misled: it puts secrets in `flow.md`, or text from a web page in a log tells an agent what to do (prompt injection) | `AGENTS.md` of every project says secrets go in `.env`; the Redactor; agents have no extra rights | Agents that read run results arrive in 1.1.0 | The agent interface marks tool results as data, and a person confirms every run (design/agent-interface.md, section 9) | 1.1.0 |
| T12 | `kinenix-worker run --sandbox` is taken for isolation | | It only copies the bundle to `~/.kinenix/workspaces/<job>`; the flow runs with the same rights. The copies, with their `.env` passwords, were never deleted | Say "separate copy", not "isolated"; delete the copy's `.env` files when the run ends (outputs stay). Removing old copies: 1.1.0 | Done (rc1) |

## 4. Out of scope

- An attacker who already has the user's account on the worker or Hub machine.
- Hardening the operating system, physical access, and backups of `hub.db`.
- Studio (paused, not published).

## 5. Review plan

The code review for 1.0.0 goes through each threat:

| Threat | Code to read |
| :--- | :--- |
| T1, T6 | `actions/file_system.py`, `actions/flow_control.py` (`flow.call` paths), `engine/interpreter.py` (subflow resolution) |
| T2 | `engine/redaction.py`, `engine/logger.py`, the screenshot code in `engine/interpreter.py`, `actions/web_playwright.py` (`secret`) |
| T3, T4, T8 | `kinenix_hub/security.py`, `app.py`, `console.py` (setup), `kinenix_worker/hub_client.py` |
| T5 | `kinenix_hub/query.py`, `views.py` |
| T7 | `kinenix_hub/static/app.js`, `index.html` |
| T9 | `actions/ai_*.py` |
| T10 | `.github/workflows/`, the `pyproject.toml` files |
| T12 | `kinenix_worker/runner.py`, `README.md` |

## 6. Findings

Filled in during the review: each finding with its threat, what was done, and the pull request or milestone.

| Finding | Threat | Outcome |
| :--- | :--- | :--- |
| `hub query` built SQL from the name a user typed (after checking it) | T5 | Fixed in #133: SQL uses only names that the database returns |
| A slow Hub was reported as a possible firewall | | Fixed in #136 |
| A localhost-only Hub answered requests for any `Host`, so a web page could read runs through DNS rebinding | T4 | Fixed: `kinenix_hub/security.py` checks `Host` on that path |
| `PIN`, `OTP`, and `PASSCODE` values were not redacted | T2 | Fixed: `engine/redaction.py` |
| `--sandbox` copies kept the bundle's `.env` forever, and the help called them isolated | T12 | Fixed: `.env` deleted after the run; wording in README and help |
| A missing `./subflows/x.md` fell back to the current folder and to flows found by name, so another flow with that path or name could run | T1, T6 | Fixed: a target that starts with `./` or `../` is looked up only in the bundle; `kinenix validate` reports it as not found. `@shared/` targets still search the `@shared` folders of the known flow locations, which is intended |
| The Hub's built-in failure hint recommended `on_error: retry`, now deprecated | T9 | Fixed: it recommends `max_retries` |
| No limit on dashboard password attempts (each costs one PBKDF2 hash) | T3 | Later, with per-user accounts; the password is hashed with 300,000 iterations, and the Hub is localhost-only unless the user opens it |

Checked with no finding (2026-10-29):

- **T2:** the JSON log, the live log, error lines on the console, and telemetry all go through the Redactor; actions print no parameter values; screenshots are referenced by path only.
- **T3, T8:** every write endpoint needs the worker key, and every read endpoint needs the dashboard password (or localhost with a local `Host`); keys are compared in constant time; malformed telemetry is recorded as an "Unknown" run instead of failing the Hub.
- **T5:** see #133.
- **T7:** every value from a worker that reaches `innerHTML` in `app.js` passes `escapeHtml`, and the modal uses `innerText`.
- **T9:** the SystemOne action defaults to `127.0.0.1`, and the Hub calls no model (1.2.0); nothing leaves the machine unless the user sets another address.
- **T10:** see the CI security checks (#133); dependency upper bounds and an SBOM stay for later.
