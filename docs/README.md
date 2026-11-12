# Documentation Index

Each topic has one owning document. Other files link here instead of repeating the content.

## Understand the System

| Document | Covers |
| :--- | :--- |
| [architecture.md](architecture.md) | Principles, modules (current vs. target), execution pipeline, AI integration, planned protocol |
| [roadmap.md](roadmap.md) | Delivery status by phase and next priorities |
| [benchmarks/flow_format.md](benchmarks/flow_format.md) | Benchmark: local AI models writing flows in `flow.md` vs YAML, and why Kinenix keeps `flow.md` |
| [design/expressions.md](design/expressions.md) | Design of expressions in `${...}` and `and` / `or` / `not` in conditions (0.3.0b1) |
| [design/list-functions.md](design/list-functions.md) | Design of sorting, filtering, totals, and comparisons in `${...}` (1.1.0) |
| [design/loop-control.md](design/loop-control.md) | Design of `logic.break` and loops with `times` (1.1.0) |
| [design/agent-interface.md](design/agent-interface.md) | Design of the agent interface: exit codes, `--json`, tools, error codes, safety; foundation in 1.0.0, interface in 1.1.0 |
| [design/threat-model.md](design/threat-model.md) | Threat model of core, worker, and Hub: what is protected, trust assumptions, threats with their milestone, review plan and findings |
| [design/phase-2.md](design/phase-2.md) | Phase 2 design: On Error and Finally, subflow context, run records for AI questions, Hub tables and views, redaction (proposal) |

## Build Flows

| Document | Covers |
| :--- | :--- |
| [flow_markdown_spec.md](flow_markdown_spec.md) | `flow.md` syntax, validation, and the compiled form (`kinenix compile`) |
| [actions_reference.md](actions_reference.md) | Every built-in action with parameters and examples |
| [project_bundles.md](project_bundles.md) | Bundle layout, `config.json`, `.env`, subflows (`flow.call`), deployment lifecycle, testing against saved pages |
| [llms.txt](llms.txt) | For AI assistants: how a flow is built and which pages to read, served as https://www.kinenix.com/llms.txt |

## Run and Operate

| Document | Covers |
| :--- | :--- |
| [examples.md](examples.md) | The examples that ship with Kinenix, what each does, and which patterns it shows |
| [tutorial.md](tutorial.md) | Tutorial: build a first flow from `requirements.md` with an AI assistant, validate, run, and break it on purpose (the `first_flow` example) |
| [quickstart.md](quickstart.md) | Install, create a project with `kinenix init`, run it, and connect a worker to the Hub in about ten minutes |
| [cli_guide.md](cli_guide.md) | `kinenix` commands and options |
| [hub.md](hub.md) | Running the Hub, environment variables, worker authentication, querying runs (`kinenix hub query`), user views |
| [hub_data.md](hub_data.md) | Hub data dictionary: tables, views, run reports, and example queries, for people and AI |
| [logging.md](logging.md) | Execution log layout and JSON format |
| [ask_router.md](ask_router.md) | Natural-language questions to the Hub (work in progress) |
| [../kinenix-worker/README.md](../kinenix-worker/README.md) | Worker CLI and Raspberry Pi setup |
| [../CHANGELOG.md](../CHANGELOG.md) | Changes and upgrade notes of each release |
| [compatibility.md](compatibility.md) | What stays stable for all of 1.x, what may change, deprecations, and upgrading |
| [../SECURITY.md](../SECURITY.md) | Supported versions and how to report a vulnerability privately |
| [releasing.md](releasing.md) | Publishing `kinenix`, `kinenix-hub`, and `kinenix-worker` to PyPI with Trusted Publishing |
| [../kinenix-studio/README.md](../kinenix-studio/README.md) | Studio design and layout |

## Contribute

| Document | Covers |
| :--- | :--- |
| [../AGENTS.md](../AGENTS.md) | Entry point for AI assistants: commands, rules index, current vs. target state |
| [../.agents/rules/](../.agents/rules/) | Engineering rules: coding, testing, security, errors, logging, git |

Machine-readable schemas: [../schemas/flow.schema.json](../schemas/flow.schema.json), [../schemas/execution_log.schema.json](../schemas/execution_log.schema.json).
