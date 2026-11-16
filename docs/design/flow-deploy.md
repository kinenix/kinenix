# Design: Deploying Flows to Workers

Status: **proposal** (2026-11-14), not yet approved. It changes one decision of [agent-interface.md](agent-interface.md), section 14 ("only flows that are already on the worker"); see section 11.

## 1. Goal

A person builds and tests a flow on one machine, publishes it once, and the Hub delivers it to the workers chosen on the dashboard. Every worker then runs the same version, the dashboard shows which version each worker has, and going back to the previous version is one command.

Today a flow reaches a worker by copying its folder or by `git pull` on every machine. That needs git and access to the repository on each worker, is easy to forget on one machine, and nothing shows which version a worker runs. People used to UiPath or Power Automate expect to publish once.

Kinenix keeps working without this: a flow folder copied or pulled by hand runs as today.

## 2. How other tools do it

| Tool | Package | Stored in | Delivered by | Secrets |
| :--- | :--- | :--- | :--- | :--- |
| UiPath | `.nupkg` with a version, published from Studio | Orchestrator (on premises or cloud) | The robot connects out to Orchestrator | Orchestrator Assets and credential stores |
| Power Automate Desktop | Flow stored in the cloud environment | Dataverse | The machine's agent connects out to the cloud | Connections in the cloud |
| Robocorp / Sema4.ai (on Robot Framework) | Zip with `robot.yaml` and `conda.yaml`, built by `rcc` | Control Room (cloud) | The worker connects out to Control Room | Control Room Vault |
| Robot Framework alone | None | Git | CI (Jenkins, GitHub Actions) | CI secrets |

They share one shape: a versioned package, a central store, and a worker that connects out and pulls. Kinenix follows that shape with two differences: the store is the Hub on the user's own network, and a package is trusted because of its signature, not because of where it came from (section 5).

## 3. Principles

1. **The worker pulls; the Hub never calls in.** Same channel as job dispatch: the worker opens no port.
2. **A package is signed on the machine that built it.** The Hub stores and delivers packages but cannot make or change one. A stolen Hub key or a taken-over Hub cannot put new code on a worker.
3. **The worker's owner decides whom to trust.** A worker installs only packages signed by a publisher key its owner added, and only when deploying is turned on.
4. **Secrets and machine settings never travel in a package.** They stay on each worker and survive updates.
5. **Nothing runs because it was deployed.** Deploying installs files. Runs still come from the worker's triggers, a person, or a confirmed job.
6. **Git stays the place for the source.** A package is built from a folder, wherever that folder comes from.

## 4. The package

`kinenix pack FLOW` builds `<name>-<version>.kinx`, a zip file:

```text
hello-1.3.0.kinx
├── kinenix-package.json     manifest (below)
├── kinenix-package.sig      signature of the manifest (section 5)
├── flow.md
├── config/config.json
├── subflows/                the bundle's subflows and the @shared/ subflows it calls, copied in
└── assets/
```

- **Extension `.kinx`** (decided 2026-11-14): short, and no other program was found using it. `.knx` was dropped because the KNX building-automation standard uses `.knxproj` and `.knxprod`; `.kix` because it is a KiXtart logon script, which Windows machines may run and mail filters block.
- **Left out:** `.env`, `config/local.json` (section 7), `output/`, `logs/`, `tests/`, `.git/`, and the patterns in an optional `.kinenixignore`.
- **`@shared/` subflows are copied in**, and the package records which were copied, so the package runs on a worker without the same `@shared` folder.
- **Version:** `--version 1.3.0`, or `## Package` / `- **version:**` in `flow.md` (to be decided, section 13). A version that was already published cannot be published again with other content.
- **Manifest:** name, version, the SHA-256 of every file, the `> Requires:` of the flow, the Kinenix version that built it, the build time, and the publisher key id.
- `kinenix validate` runs before packing; a flow with issues is not packed.

`kinenix install hello-1.3.0.kinx` installs a package from a file, with the checks of section 5 and the layout of section 7. This works without a Hub: copying one file to the Raspberry Pi is already easier than copying a folder.

## 5. Signing and trust

- `kinenix publisher init` creates a key pair on the building machine: the private key in `~/.kinenix/publisher/` with mode 600, the public key printed as one line to give to workers.
- `kinenix pack` signs the manifest with the private key; the manifest holds the hash of every file, so the signature covers the whole package.
- `kinenix-worker trust add <public key> --name office-pc` adds a publisher on a worker; `trust list` and `trust remove` manage them.
- On install, the worker checks, in order: the signature against a trusted publisher, every file hash, `> Requires:` against its own Kinenix version, and that no path leaves the flow folder (threat model T6). Any failure refuses the package with a stable error code (`PACKAGE_UNTRUSTED`, `PACKAGE_DAMAGED`, `PACKAGE_REQUIRES`).
- **Algorithm:** Ed25519. Which library is open (section 13): `cryptography` adds a dependency to kinenix-core; OpenSSH signatures (`ssh-keygen -Y sign`) need no Python dependency and exist on Windows, Ubuntu, and Raspberry Pi OS.
- **Losing the private key:** make a new key, trust it on the workers, remove the old one. A stolen private key can sign packages until workers remove it, so the key stays on the building machine and is never put on the Hub.

## 6. Publishing and assigning on the Hub

- `kinenix publish hello-1.3.0.kinx` uploads to the Hub with the worker key. The Hub checks the signature against the publishers it was told about (only to show who signed; workers check again), stores the file in `~/.kinenix/hub_packages/`, and records it in a `packages` table.
- On the dashboard, signed in, a person assigns a version of a flow to workers. `kinenix hub deploy hello 1.3.0 --worker pi` does the same from a terminal with the dashboard password. An assignment is a row: flow, version, worker, assigned by, assigned at.
- The worker key alone can publish but not assign. A stolen worker key can upload packages, which no worker installs unless they carry a trusted signature.
- A size limit on uploads (default 50 MB) and on the number of stored versions per flow (default 10, the oldest unassigned removed first).

## 7. Delivery and the layout on the worker

- **Turned on by the owner:** `kinenix-worker deploy enable`. Off by default; a worker with deploying off ignores assignments and shows so in its heartbeat.
- **Delivery:** the worker's long poll (`GET /api/v1/jobs/next`, agent-interface.md section 14) also answers "a new assignment exists". The worker then downloads the package, checks it (section 5), and installs it. Workers before this version never ask and are not affected.
- **Where it goes:** into the flows folder as `~/kinenix-flows/hello/`, so `kinenix run hello` and existing triggers keep working. A file `.kinenix-deployed.json` in the folder records the package, version, publisher, and install time.
- **Never over a hand-made folder:** the worker refuses to install into a folder without `.kinenix-deployed.json` (a git checkout or a copied folder), and reports it on the dashboard. `kinenix-worker deploy adopt hello` lets the owner hand that folder to deploying.
- **Kept across updates:** `.env`, `config/local.json`, `output/`, and `logs/`. Everything else is replaced.
- **Atomic:** the new version is unpacked next to the folder and swapped in by renaming; a run that is going on finishes on the files it started with, and the swap waits until it ends.
- **Rollback:** the last packages are kept in `~/.kinenix/packages/<flow>/`. Assigning an older version on the dashboard installs it again; `kinenix-worker deploy rollback hello` does it on the machine without the Hub.
- **Machine settings:** `config/local.json` is merged over `config/config.json` key by key, as `kinenix run --config` does today, for values that differ per machine (folders, printer names, a test or production site). Secrets stay in `.env`.

## 8. What the dashboard shows

The worker's heartbeat adds the flows in its flows folder, each with the deployed version (or "not deployed"), whether deploying is on, and the publishers it trusts (their names and key ids, never keys). The Hub keeps the latest list per worker, so it also knows flows that never ran, which `v_flows` cannot (it reads only runs). The dashboard shows a table of flows by worker with the assigned and the installed version, and marks a worker that has not installed its assignment after a few minutes, with the reason it reported.

## 9. Security

New threats for [threat-model.md](threat-model.md):

| Threat | Protection |
| :--- | :--- |
| The Hub, or someone with the worker key, sends code to every worker | Workers install only packages signed by a publisher they trust; the Hub has no private key |
| A changed or damaged package | File hashes in the signed manifest; any mismatch refuses the whole package |
| A package writes outside its folder (`../` in a zip entry) | Paths checked before unpacking (T6) |
| Secrets leave the building machine inside a package | `.env` and `config/local.json` are never packed; `kinenix pack` lists the files it packed and warns about files whose names look like secrets |
| An old, broken version is assigned again on purpose | Only a signed-in dashboard user can assign; every assignment is recorded with who made it |
| The publisher's private key is stolen | Remove it on the workers (`trust remove`); keep it only on the building machine, mode 600 |
| Deploying replaces a flow while it runs | The swap waits for the run to end |

A flow is still code (T1): a trusted publisher can still sign a harmful flow. Signing proves who built a package, not that it is safe; review of flows before publishing stays the person's job.

## 10. Commands

| Command | Where | What it does |
| :--- | :--- | :--- |
| `kinenix pack FLOW [--version V]` | building machine | Validates, builds, and signs `<name>-<version>.kinx` |
| `kinenix publisher init` / `show` | building machine | Creates the signing key / prints the public key |
| `kinenix install FILE` | any machine | Installs a package from a file, with all checks |
| `kinenix publish FILE` | building machine | Uploads a package to the Hub |
| `kinenix hub deploy FLOW VERSION --worker W` | Hub or any connected machine | Assigns a version to workers (dashboard password) |
| `kinenix-worker trust add / list / remove` | worker | Publishers this worker accepts |
| `kinenix-worker deploy enable / disable / status / adopt / rollback` | worker | Deploying on this worker |

## 11. Relation to job dispatch and triggers

- **Job dispatch** (agent-interface.md, section 14) said "only flows that are already on the worker". With deploying, a job still names a flow that is installed on the worker; it never carries the package. The decision stays true, but a flow can now arrive on a worker without anyone at it, so the job allow list (`kinenix-worker jobs allow`) applies to deployed flows like any other, and a new deployment of an allowed flow needs no new allow.
- **Triggers** (#155, 1.4.0): deploying installs files only. Assigning schedules from the Hub is a later step, once triggers are managed by command.
- **Flow approval** (agent-interface.md, section 12): publishing a signed package counts as the person's approval of that content; a deployed flow does not need `kinenix approve` again on the worker.

## 12. Order and releases

Each part is useful before the next:

1. **`kinenix pack`, `kinenix install`, publisher keys, and trust.** No Hub needed: one file to copy instead of a folder or a git checkout. Fits 1.3.0 (hardening), since it closes part of T1 for flows moved between machines.
2. **The heartbeat reports flows and versions** (section 8). Small, and lets the Hub list flows that never ran.
3. **Publish, assign, and delivery through the long poll.** With job dispatch in 1.5.0, since both use the same channel.

All of it is additions: new commands, endpoints, tables, and heartbeat fields; nothing in [compatibility.md](../compatibility.md) changes.

## 13. Open questions

- Signing library: `cryptography` (a new dependency of kinenix-core) or OpenSSH signatures (no dependency, an external program).
- Where the version is written: a `--version` flag only, or also in `flow.md`.
- Whether `config/local.json` is loaded by every run or only when the worker runs a deployed flow.
- Whether the Hub should also keep the publishers' public keys, to warn before a worker refuses a package.
- Windows service and file locking during the swap (a file open in Excel inside `assets/`).

## 14. Out of scope

- Packages that carry Python code or install Python packages; a flow uses only Kinenix actions.
- Deploying to workers outside the Hub's network, or a cloud store.
- Assigning schedules and triggers from the Hub (after #155).
- Per-worker keys and user accounts on the Hub (threat model T3), which would let assignments name a person instead of "the dashboard user".
