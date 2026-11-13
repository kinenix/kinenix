# Architecture Rules

Rules that every change must respect. For how the system is structured today and the target design, see `docs/architecture.md`. For what is built and what is planned, see `docs/roadmap.md`.

---

## 1. Principles

1. **Open source, no per-bot fees:** Core, Studio, Hub, and Worker must remain open source without per-bot licensing.
2. **No Office dependency:** Spreadsheet processing (`.xlsx`, `.csv`) must use file-level libraries (`openpyxl`, `pandas`). Never require Microsoft Excel or Microsoft 365.
3. **Business-first telemetry:** Logs and dashboards must include business metrics (transactions, hours saved, cost saved), not only technical traces.
4. **Local AI-native:** AI features must work with locally hosted models (Ollama, llama.cpp, ONNX). Do not add a hard dependency on a cloud AI provider.
5. **Deterministic first:** Flow execution must stay deterministic. AI may act only through explicit actions or as an observer.
6. **Scope discipline:** Focus on core features and stability. Sponsorship and monetization features are out of scope for now.

---

## 2. Module Boundaries

- `kinenix-core` must stay lean: it must run non-AI flows without any ML runtime installed. AI integrations are optional sidecars reached over HTTP.
- Actions must not depend on GUI frameworks.
- AI copilot and diagnostic tools must run as detached sidecar services or optional add-ons.
- New and changed CLI commands keep their logic in functions that return data; `cli.py` only parses arguments and prints. The MCP server (`kinenix mcp`) will call the same functions (`docs/design/agent-interface.md`, section 10).
- From 0.4.0b1, every action declares its side-effect kind (`email`, `files`, `web`, `network`, or `none`), so a run can be described and confirmed before it starts.

---

## 3. Project Bundles

Flows must follow the self-contained bundle layout in `docs/project_bundles.md`:
- Reference assets and subflows with relative paths (`./assets/...`, `./subflows/...`) or the `@shared/` namespace.
- Never hardcode absolute, machine-specific paths.
- Keep secrets out of `flow.md` and `config.json`; use `.env` or environment variables.

---

## 4. Worker-Hub Communication

When implementing worker-hub messaging, follow the Hybrid Protocol in `docs/architecture.md`:
- Machine state travels as structured JSON (`type`, `job_id`, `status`, `metrics`) with explicit states `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`.
- Natural-language reports travel inside the envelope as Markdown (`agent_report_md`), never as the only carrier of state.
- Remote workers must not share state through mounted disks.
- Every worker-facing write endpoint must require authentication (see `kinenix-hub/kinenix_hub/security.py`).

---

## 5. Flows as Code

- Flows must remain declarative, human-readable `flow.md` files that are versioned in Git. Do not add a second file format for flows.
- Never introduce opaque binary flow formats.
- Deployment must follow the GitOps model in `docs/architecture.md`: Git branch, CI validation, versioned release.
