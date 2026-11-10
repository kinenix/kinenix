# kinenix

[![Status](https://img.shields.io/badge/Status-1.0%20release%20candidate-yellow.svg?style=flat-square)](CHANGELOG.md)
[![CI](https://github.com/kinenix/kinenix/actions/workflows/ci.yml/badge.svg)](https://github.com/kinenix/kinenix/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/kinenix.svg?style=flat-square)](https://pypi.org/project/kinenix/)
[![Python](https://img.shields.io/badge/Python-3.12%2B-brightgreen.svg?style=flat-square)](#)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg?style=flat-square)](LICENSE)

> **Open-source Python framework for automation flows written in Markdown.**  
> Describe the task, let your AI assistant write the flow, then run it on any PC or Raspberry Pi. Free unattended workers and a self-hosted Hub for every run.

> **Status: 1.0 release candidate.** From 1.0.0, the `flow.md` format, the CLI commands and exit codes, the log format, and the Hub's data stay compatible for all of 1.x ([compatibility.md](docs/compatibility.md)). Feedback and contributions are welcome.

---

## 1. Key Highlights

- **Flows in Markdown:** A flow is one `flow.md` file that people can read and AI assistants can write. `kinenix init` gives every project a `requirements.md` and an `AGENTS.md` for the assistant, and `kinenix validate` checks a flow before it runs.
- **Free unattended workers:** `kinenix-worker` runs flows on a schedule, a cron expression, or when a file arrives, on Windows, Linux, and Raspberry Pi, with no per-robot license.
- **Excel without Office:** Read and write spreadsheets and CSV files with `openpyxl` and `pandas`; no Microsoft Excel installation needed.
- **Self-hosted Hub:** Workers send every run and heartbeat to a Hub on your own network. See failures on the dashboard, or ask with `kinenix hub status`, `logs`, `report`, and `query`.
- **Built for diagnosis:** Every run writes a structured JSON log with the failed step, its line in `flow.md`, a plain-language cause and fix, and a screenshot for web steps. Exit codes tell scripts and AI assistants whether a run failed on data or on a technical problem.
- **Your data stays local:** Passwords and personal data are hidden in logs and telemetry before they leave the run. The optional AI steps (`ai.prompt`, `ai.extract`) use a local model through Ollama.
- **Python and extensible:** Built-in actions for web (Playwright), Excel and CSV, files, HTTP, email, dates, and flow control, on a plugin base (`BaseAction`) for your own.

---

## 2. Modules

| Module | Role | Status |
| :--- | :--- | :--- |
| **`kinenix-core`** | Flow interpreter, action plugins, and `kinenix` CLI | Implemented |
| **`kinenix-worker`** | Unattended runner with schedule and file-watch triggers | Implemented (WebSocket dispatch planned) |
| **`kinenix-studio`** | Web-based flow editor and runner | Paused (see [Roadmap](docs/roadmap.md#studio-kinenix-studio---paused)) |
| **`kinenix-hub`** | Central telemetry server, dashboard, and AI failure summaries | Early |

Flows are packaged as self-contained project bundles under `flows/`. See [Architecture](docs/architecture.md) for the execution pipeline, AI integration, and target design, and [Roadmap](docs/roadmap.md) for delivery status.

---

## 3. Prerequisites

Before installing and running kinenix, ensure your system meets the following requirements:

### Core Requirements
| Component | Minimum Version | Notes |
| :--- | :--- | :--- |
| **Python** | `3.12` or higher | Tested on `3.12` and `3.14`; install with `pip` and `venv` |
| **Git** | `2.30+` | Required for version control and GitOps flow deployments |
| **Operating System** | Windows 10/11, Ubuntu 20.04+, Debian 11+, Raspberry Pi OS (64-bit), macOS 12+ | Fully cross-platform |

### Platform-Specific Setup

#### Linux / Ubuntu / Debian / Raspberry Pi (64-bit)
On Linux environments, ensure system packages and Playwright browser shared libraries are installed:
```bash
# 1. Install system packages and python venv
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv

# 2. Install Playwright Chromium with Linux system dependencies (libnss3, libasound2, etc.)
playwright install --with-deps chromium
```

#### Windows
Ensure Python 3.12 or newer is installed with **"Add python.exe to PATH"** checked. Install Playwright browser binaries with:
```powershell
kinenix install-browsers
# or: playwright install chromium
```

### Optional Dependencies
- **Local AI Inference (for `ai.prompt`, `ai.extract`):** Install [Ollama](https://ollama.com/) and run a local model:
  ```bash
  ollama run qwen2.5:1.5b
  ```
- **kinenix-studio Web UI Development:** [Node.js 18+](https://nodejs.org/) and `npm` (only required if developing or building `kinenix-studio/frontend`).

---

## 4. Quick Start

### Installation

#### From PyPI

Kinenix is published on PyPI as [`kinenix`](https://pypi.org/project/kinenix/), with the worker and the Hub as extras (from version 0.2.0b1; all packages share one version):

```bash
pip install kinenix              # core engine and the kinenix CLI
pip install "kinenix[worker]"    # plus kinenix-worker: unattended runs, schedules, cron
pip install "kinenix[hub]"       # plus kinenix-hub: central server and dashboard (`kinenix hub`)

kinenix install-browsers         # Playwright Chromium, needed for web actions
kinenix --version
```

Check the installation with the `hello` example (no browser needed), then start a project for your own task:

```bash
kinenix init demo --example hello    # copy an example; `kinenix init --list` shows the others
kinenix run demo                     # writes demo/output/greetings.csv

kinenix init "Get stock data"        # new project: describe the task in requirements.md,
                                     # then let an AI assistant write flow.md (see the AGENTS.md it creates)
```

Projects are created in your own flows folder (default `~/kinenix-flows`, asked the first time), separate from this repository, and run by name from anywhere. Keep that folder in a private git repository. The [Quickstart](docs/quickstart.md) walks through all of this, then a worker reporting to the Hub, in about ten minutes.

Kinenix Studio is paused and not on PyPI: flows are written as `flow.md` with an AI assistant instead (see the [Roadmap](docs/roadmap.md#studio-kinenix-studio---paused)). Its code stays in the repository and can be installed from source as shown below. Maintainers: see [docs/releasing.md](docs/releasing.md).

#### From source (all modules, for development)

Clone the repository and install the modules in editable mode within your Python virtual environment:

```bash
# Clone repository from dev branch
git clone -b dev https://github.com/kinenix/kinenix.git kinenix
cd kinenix

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\Activate.ps1

# Install core engine and worker daemon in editable mode
pip install -e ./kinenix-core -e ./kinenix-worker
# Optional: Studio and the Kinenix Hub
pip install -e ./kinenix-studio -e ./kinenix-hub
```

### Verification & Execution

```bash
# Check installed version and runtime info
kinenix version
kinenix-worker info

# List available flows (clean, deduplicated view)
kinenix list

# Run an example (copy it first with: kinenix init demo --example quote_requests)
kinenix run demo

# Run with unattended worker daemon
kinenix-worker run demo
```

---

## 5. Documentation

Start at the [documentation index](docs/README.md). Most used:

- **[Architecture](docs/architecture.md):** Modules, execution pipeline, AI integration, current vs. target design.
- **[Roadmap](docs/roadmap.md):** What is done, in progress, and next.
- **[Flow Markdown Specification](docs/flow_markdown_spec.md)** and **[Actions Reference](docs/actions_reference.md):** Writing flows.
- **[CLI Guide](docs/cli_guide.md)** and **[Hub Guide](docs/hub.md):** Running flows and the central server.

AI coding assistants should start at [AGENTS.md](AGENTS.md).

---

## 6. Acknowledgments

Kinenix is developed with the help of [Claude Code](https://claude.com/claude-code), Anthropic's AI coding assistant, which assists with code, tests, and documentation. The maintainer reviews and merges every change.

---

## 7. License

Kinenix is licensed under the [Apache License 2.0](LICENSE); see also [NOTICE](NOTICE). Releases up to and including 0.2.0b3 were published under the MIT License.
