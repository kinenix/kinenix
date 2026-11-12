# Batch Flows

A batch flow works through a list of items unattended: the rows of a CSV file, the requests of the day, the pages of a website. It is run by a schedule, and people read only what it leaves behind: the files in `output/`, an e-mail, the run on the Hub. These five rules keep that picture true. They come from a flow an AI assistant wrote from the new-project template (#150): it passed `kinenix validate` and ran against the real website, yet its files, its e-mails, and its tests misled the people reading them.

The template's `AGENTS.md` (`kinenix init`) states the rules in short and links here. The `quote_requests` example (`kinenix init --example quote_requests`) follows rules 2, 4, and 5.

## 1. Every file in the output folder belongs to this run

A file left over from an earlier run looks like today's result. A flow that writes `packages.csv` only when it found packages leaves yesterday's file in place on a day without any, and every zip of `output/` carries the screenshots of old failures.

Give each run its own folder with `${run.id}`:

```markdown
### 5. Save The Packages (`csv.write`)
- **file_path:** ./output/${run.id}/packages.csv
- **data:** ${packages}
- **columns:** ["request_id", "package_name", "premium"]

### 6. Zip The Results (`file.zip`)
- **source:** ./output/${run.id}
- **destination:** ./output/${run.id}.zip
```

Failure screenshots go to their own folder per run with `"error_dir": "./output/errors/${run.id}"` in `config/config.json`.

When the files must keep fixed names (another system picks them up), clear the folder as the first step instead:

```markdown
### 1. Clear The Output Folder (`file.delete`)
- **path:** ./output
```

`file.delete` deletes a folder with its contents, and a folder that is not there is not an error (`missing_ok` is true by default).

Write a result file even when it has no rows: `csv.write` with `columns` and an empty list writes the header only, which says "nothing today" instead of leaving no file. It also keeps `email.send` working, because a missing attachment stops that step.

## 2. One bad item does not stop the batch

A step without `on_error` stops the whole run when it fails. In a loop, a model that cannot be chosen for item 3 of 20 then ends the run, and the other 17 items are never tried. Decide for every step in the loop that can fail for one item (web steps, file reads, calls to other systems) what should happen:

- `on_error: next_item` gives up on this item and goes on with the next one. The run ends as partial, and the Hub lists the item with its error.
- `on_error: continue` goes on with the next step of the same item, so a later step can record the failure.

Put the steps for one item in a subflow, call it with `on_error: continue`, and record the item when the call did not succeed:

```markdown
  - Reset The Result (`logic.set_variable`):
    - **name:** quote_result
    - **value:** {"status": "failed", "packages": []}
  - Quote One Request (`flow.call`):
    - **flow:** ./subflows/quote_one.md
    - **inputs:** {"req": "${req}"}
    - **output_var:** `quote_result`
    - **on_error:** continue
  - Note The Failure (`logic.append`):
    - **condition:** `${quote_result.status} != ok`
    - **target:** `failed`
    - **item:** {"request_id": "${req.request_id}", "reason": "${default(error.root_cause, error.message)}"}
```

Reset the result before each call: a failed call does not set `output_var`, so the previous item's result would be read. `kinenix validate` cannot tell which failures should stop the run; only the requirements say that one failure must stop everything (for example a login that fails).

## 3. A run that produced nothing does not end as a success

A run whose input was empty, or whose items all came back without a result, finishes as success unless the flow says otherwise. Stop it with `flow.fail` after the loop, once the files are written:

```markdown
> Requires: kinenix>=0.3.0b1

### 6. Stop When Nothing Was Quoted (`flow.fail`)
- **condition:** `${len(packages)} == 0`
- **message:** No packages were found for ${len(requests)} requests; ${len(failed)} failed.
```

`flow.fail` is a business failure: the run ends as failed with exit code 3, and `## On Error` sends its message. Stop as early as the problem shows, too: an empty input file is better stopped right after it is read.

## 4. The completion message says what happened

A message that always says "completed successfully" hides failed items. Put the counts in the subject and the failed items in the body:

```markdown
> Requires: kinenix>=1.1.0

### 7. Send The Results (`email.send`)
- **to:** ${config.email.to}
- **subject:** Quotes: ${len(requests)} requests, ${len(failed)} failed
- **body:** |
    ${len(packages)} packages were found for ${len(requests)} requests.
    Failed: ${default(join(column(failed, 'request_id'), ', '), 'none')}
- **attachments:** ["./output/${run.id}/packages.csv", "./output/${run.id}/failed_requests.csv"]
```

`column` needs Kinenix 1.1.0, hence the `> Requires:` line, which goes under the flow's title. Every list a message uses must be filled by the flow: a `failed` variable that is declared but never appended to always reads as zero.

## 5. Test pages for JavaScript sites are written, not saved

A page saved from a site built with React, Vue, or similar loses the scripts that make it work: its dropdowns never open, and the test run fails at the first `web.choose` every time. Write a small test page instead, with only the parts the flow touches, the same selectors (`data-testid`, labels, roles), and a few lines of script for what the flow relies on: a dropdown that opens and lists its options, a button that shows the results.

`flows/examples/quote_requests/tests/pages/quote.html` is such a page: custom dropdowns with a search box, a cookie banner that appears late, and package cards, in about 200 lines. Point `config/test.json` at it and run with `--config config/test.json`; [project_bundles.md, Testing Against Saved Pages](project_bundles.md#4-testing-against-saved-pages) describes the setup.
