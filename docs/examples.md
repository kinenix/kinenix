# Examples

Complete flow projects that ship with Kinenix. Each one has the `requirements.md` it implements, in the sections `kinenix init` gives you for your own task, so you can see how a description in plain language becomes `flow.md`, settings, and error handling. Copy one with:

```bash
kinenix init --list                       # the examples, and which need a browser
kinenix init my-copy --example hello      # copy one into your flows folder
kinenix run my-copy
```

The examples that run offline use pages saved in their folder (`tests/pages/`) and made-up data, so they work without internet, on any machine, and in CI, which runs them end to end on every change.

| Example | What it does | Offline | Patterns it shows |
| :--- | :--- | :--- | :--- |
| `hello` | Builds a greeting per name from `config.json` and writes a CSV; the quickest installation check | Yes, no browser | A loop, a subflow per item with `flow.call`, `flow.fail` on empty input, `csv.write` |
| `first_flow` | The [tutorial](tutorial.md): finished requirements and an empty `flow.md` for your AI assistant to build; reads a made-up shop's catalog and lists the products over a budget. Its solution stays in the repository, out of the project | Yes | Requirements to a flow with an assistant; `web.get_list` over two pages (`next_selector`), `numeric_fields`, a condition in a loop, `## Finally`; reading a failure on purpose |
| `quote_requests` | Enters car insurance quote requests from a CSV into a made-up insurer's form, reads the packages offered, and e-mails the packages and the failed requests with their reasons | Yes | A subflow per request; `web.goto`, `web.choose` with search and `match: loose`, `web.get_list`; `on_error: next_item` and `continue` in a loop; `${error.root_cause}`; `redact`; On Error and Finally; partial success on the Hub |
| `bot_fx_rate` | Bank of Thailand transfer rates for chosen currencies over the previous month, to CSV, e-mailed | No (bot.or.th) | `date.calc`, date pickers, `web.get_table` with `numeric_columns` and `add_columns`, retries, e-mail |

## More examples

[kinenix/examples](https://github.com/kinenix/examples) holds examples that need a real website or other services, so they cannot run offline in CI with Kinenix itself. A weekly check there shows when a website has changed.

| Example | What it does |
| :--- | :--- |
| `rpa-challenge` | Downloads the RPA Challenge's Excel file and fills its web form for all ten people while the fields move |
| `rpa-challenge-ocr` | Reads an invoice image with a local AI model through Ollama |
| `extract-artbook` | Reads a category of Books to Scrape page by page and writes the well-rated books to a CSV |

These were in this repository until 1.0.0rc4; the RPA Challenge's Excel file now comes from its website when the flow runs.

## Reading an example

1. Start with `requirements.md`: the goal, the steps, which values are settings, the secrets, the output, and what to do when something fails.
2. Open `flow.md` next to it. Each requirement step becomes one or more steps; the settings are `${config...}`; the errors section becomes `max_retries`, `on_error`, `flow.fail`, and `## On Error`.
3. Run it, open `output/`, and read the run's log under `logs/`. With a Hub connected, the run appears on the dashboard.
4. Change `config/config.json` and run again; then change the flow.

## Baseline: how fast is the engine

Measured on a Raspberry Pi 4 (2 GB) and a Windows laptop with Kinenix 1.0.0rc2, so you can tell whether a flow is slow because of Kinenix or because of the pages it waits for. The flow reads 100 rows from a CSV file, calculates and checks each row in a loop, collects the results, and writes a CSV: 303 steps, no browser, and no network.

| Machine | Time in the flow | Per step | Whole command | Memory at most |
| :--- | :--- | :--- | :--- | :--- |
| Raspberry Pi 4, Python 3.13 | 0.36 s | about 1.2 ms | 2.5 s | about 95 MB |
| Windows laptop, Python 3.12 | 0.27 s | about 0.9 ms | | |

The whole command takes longer than the flow because starting Python and loading Kinenix takes about 2 seconds on the Pi; a worker that stays running pays this once. Web steps take far longer than these, from 100 ms to several seconds each, because they wait for the page.

In a 48-hour soak of 1.0.0rc3 on the same Pi, a worker running three flows every 30 minutes stayed at about 109 MB, and the Hub on the same machine at about 140 MB.

```markdown
# Loop Baseline
> Description: Measures the engine on this machine: reads 100 rows, checks and copies each one in a loop, and writes them back. No browser and no network.
> Requires: kinenix>=1.0.0rc2

## Variables
- `results`: []

## Steps

### 1. Read Items (`csv.read`)
- **file_path:** data/items.csv
- **output_var:** `items`

### 2. Process Each Item (`logic.loop`)
- **items:** ${items}
- **item_var:** `row`
- **item_label:** ${row.id}
- **Sub-steps:**
  - Compute Total (`logic.set_variable`):
    - **name:** total
    - **value:** ${number(row.qty) * number(row.price)}
  - Mark Large Orders (`logic.if`):
    - **left:** ${total}
    - **operator:** greater_than
    - **right:** 500
  - Keep Result (`logic.append`):
    - **target:** `results`
    - **item:** {"id": "${row.id}", "total": "${total}"}

### 3. Write Results (`csv.write`)
- **file_path:** output/results.csv
- **data:** ${results}
```

`data/items.csv` has the columns `id`, `qty`, and `price`. "Time in the flow" is the run's own duration in its log; "Whole command" is the time `kinenix run` took from start to exit.
