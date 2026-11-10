# kinenix-hub

The **Kinenix Hub** is the central server of [Kinenix](https://github.com/kinenix/kinenix), an open-source, local AI-native RPA framework in Python. Workers report to it, and you watch everything from one place.

> **Status: stable (1.x).** Job dispatch from the Hub to workers is planned; today workers run their own schedules and report to the Hub.

- Receives heartbeats from workers and shows each one as online, busy, or offline
- Stores every execution with its steps, timings, and errors (SQLite by default, any SQLAlchemy database through `DATABASE_URL`)
- Web dashboard, plus `kinenix hub status` and `kinenix hub logs` in the terminal
- AI failure summaries through a local model, so business data stays on your network
- Worker API key and dashboard login; listens on localhost only until you opt in

## Installation

```bash
pip install "kinenix[hub]"
```

This installs `kinenix-hub` together with `kinenix`, which provides the `kinenix hub` command. Requires Python 3.12 or newer.

## Usage

```bash
kinenix hub              # start; the first run asks a few setup questions and saves them
kinenix hub status       # workers and recent executions
kinenix hub logs         # steps of the latest execution
kinenix hub report --flow "BOT FX"   # how the latest run of a flow went
kinenix hub query v_failures --since yesterday   # what failed, where, on which item
kinenix hub show-key     # the API key to give to workers
```

Settings are saved in `~/.kinenix/hub.env` and data in `~/.kinenix/hub.db`. On a worker machine, install `kinenix[worker]` and set `KINENIX_HUB_URL` and `KINENIX_HUB_API_KEY`.

## Documentation

- [Hub guide](https://github.com/kinenix/kinenix/blob/main/docs/hub.md): setup, authentication, saved settings, and the API
- [Worker guide](https://github.com/kinenix/kinenix/blob/main/kinenix-worker/README.md)
- [Project README](https://github.com/kinenix/kinenix#readme)

## License

Apache License 2.0. Releases up to and including 0.2.0b3 were published under the MIT License.
