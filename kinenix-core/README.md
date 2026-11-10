# kinenix

Core execution engine and `kinenix` CLI for **Kinenix**, an open-source, local AI-native RPA framework in Python.

> **Status: stable (1.x).** Flows, commands, exit codes, and logs stay compatible for all of 1.x ([compatibility](https://github.com/kinenix/kinenix/blob/main/docs/compatibility.md)).

- Runs automation flows written as `flow.md`
- Built-in actions for web automation (Playwright), Excel and CSV (no Microsoft Office required), files, HTTP, email, and flow control
- Local AI actions through Ollama, so business data stays on your machine
- Retries, fallbacks, failure screenshots, and structured JSON execution logs

## Installation

```bash
pip install kinenix
kinenix install-browsers   # Playwright Chromium, needed for web actions
kinenix --version
```

Requires Python 3.12 or newer.

## Usage

```bash
kinenix list                       # list flows found in the current project
kinenix run path/to/bundle         # run the flow.md in a bundle folder
kinenix compile path/to/flow.md    # print the compiled form as JSON (inspection)
kinenix version                    # version and environment details
```

## Related packages

All Kinenix packages are released together with the same version.

```bash
pip install "kinenix[worker]"   # kinenix-worker: run flows unattended on schedules or cron, report to the Hub
pip install "kinenix[hub]"      # kinenix-hub: central server with dashboard; adds `kinenix hub`
```

Kinenix Studio (visual flow editor) lives in the same repository and is not yet published on PyPI.

## Documentation

- [Project README](https://github.com/kinenix/kinenix#readme)
- [Actions reference](https://github.com/kinenix/kinenix/blob/main/docs/actions_reference.md)
- [Flow Markdown specification](https://github.com/kinenix/kinenix/blob/main/docs/flow_markdown_spec.md)
- [CLI guide](https://github.com/kinenix/kinenix/blob/main/docs/cli_guide.md)

## License

Apache License 2.0. Releases up to and including 0.2.0b3 were published under the MIT License.
