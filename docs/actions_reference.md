# Kinenix Actions Reference Guide

This document specifies the standard actions available in Kinenix. Each action lists its parameters, an example step in `flow.md` (see the [Flow Markdown specification](flow_markdown_spec.md)), and, where useful, the shape of its output. `kinenix actions` lists every action with the parameters it accepts and, in brackets, what it can do outside the run: `email`, `files` (writes, moves, or deletes), `web` (opens a site, clicks, types, uploads), or `network` (calls another service). Actions without brackets only read or compute.

---

## Table of Contents

1. [Web Automation (`web.*`)](#web-automation-web)
   - [web.open](#webopen)
   - [web.goto](#webgoto)
   - [web.click](#webclick)
   - [web.type](#webtype)
   - [web.get_text](#webget_text)
   - [web.get_attribute](#webget_attribute)
   - [web.get_table](#webget_table)
   - [web.get_list](#webget_list)
   - [web.wait_for](#webwait_for)
   - [web.is_visible](#webis_visible)
   - [web.press](#webpress)
   - [web.scroll](#webscroll)
   - [web.hover](#webhover)
   - [web.switch_tab](#webswitch_tab)
   - [web.choose](#webchoose)
   - [web.select_option](#webselect_option)
   - [web.upload_file](#webupload_file)
   - [web.check](#webcheck)
   - [web.uncheck](#webuncheck)
   - [web.download](#webdownload)
   - [web.screenshot](#webscreenshot)
   - [web.close](#webclose)
2. [Data, Excel, and CSV (`excel.*`, `csv.*`)](#data-excel-and-csv-excel-csv)
   - [excel.read](#excelread)
   - [excel.write](#excelwrite)
   - [csv.read](#csvread)
   - [csv.write](#csvwrite)
3. [File System Operations (`file.*`)](#file-system-operations-file)
   - [file.exists](#fileexists)
   - [file.copy](#filecopy)
   - [file.move](#filemove)
   - [file.delete](#filedelete)
   - [file.zip](#filezip)
   - [file.unzip](#fileunzip)
   - [file.list](#filelist)
   - [file.read_text](#fileread_text)
   - [file.write_text](#filewrite_text)
   - [file.create_folder](#filecreate_folder)
4. [Control Flow and Logic (`logic.*`)](#control-flow-and-logic-logic)
   - [logic.set_variable](#logicset_variable)
   - [logic.delay](#logicdelay)
   - [logic.if](#logicif)
   - [logic.loop](#logicloop)
   - [logic.break](#logicbreak)
   - [logic.next](#logicnext)
   - [logic.append](#logicappend)
5. [Dates (`date.*`)](#dates-date)
   - [date.calc](#datecalc)
6. [HTTP API Integration (`http.*`)](#http-api-integration-http)
   - [http.request](#httprequest)
   - [http.download](#httpdownload)
7. [Modular Subflows and Flow Control (`flow.*`)](#modular-subflows-and-flow-control-flow)
   - [flow.call](#flowcall)
   - [flow.return](#flowreturn)
   - [flow.fail](#flowfail)
8. [Email Notification (`email.*`)](#email-notification-email)
   - [email.send](#emailsend)
9. [AI and Local LLM (`ai.*`)](#ai-and-local-llm-ai)
   - [ai.prompt](#aiprompt)
   - [ai.extract](#aiextract)
   - [ai.decide](#aidecide)

---

## Web Automation (`web.*`)

Powered by Playwright with automatic browser binary installation.

### `web.open`
Launches a browser instance and navigates to a target URL.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | Yes | - | URL of the website to open, or a page saved in the flow's folder such as `tests/pages/form.html` (opened as a local file, for testing; see [project_bundles.md](project_bundles.md#4-testing-against-saved-pages)). If the parameter is given but resolves to an empty value (for example `${config.url}` with no config loaded), the step fails instead of opening a blank page |
| `headless` | boolean | No | `false` | Run browser in headless mode |
| `timeout` | number | No | `30000` | Navigation timeout in milliseconds |

**Example:**
```markdown
### step_open. Open Target Website (`web.open`)
- **url:** https://rpachallenge.com/
- **headless:** true
```

---

### `web.goto`
Goes to a URL **in the current tab** (Kinenix 0.4.0b1). `web.open` opens a new tab every time; in a loop or a subflow that returns to the same form, `web.goto` keeps one tab and starts from a fresh page each time. When no browser is open yet, it opens one, so a subflow can start with `web.goto`.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | Yes | - | URL to go to, or a page saved in the flow's folder such as `tests/pages/form.html`. An empty value (for example `${config.url}` with no config loaded) fails the step |
| `wait_until` | string | No | `load` | When the page counts as loaded: `load`, `domcontentloaded`, `networkidle` (no network traffic for 0.5 s; slower), or `commit` |
| `timeout` | number | No | `30000` | Navigation timeout in milliseconds |
| `headless` | boolean | No | `false` | Only used when `web.goto` opens the browser |

**Example:**
```markdown
### 2. Each Request (`logic.loop`)
- **items:** `${requests}`
- **item_var:** `req`
- **item_label:** ${req.request_id}
- **Sub-steps:**
  - Back To The Quote Form (`web.goto`):
    - **url:** ${config.quote_url}
    - **wait_until:** domcontentloaded
  - Process One Request (`flow.call`):
    - **flow:** ./subflows/process_one.md
    - **inputs:** {"req": "${req}"}
```

**Output:** `{"url": "<url after redirects>", "title": "<page title>", "status": "navigated"}`

---

### `web.click`
Clicks an element identified by CSS selector, XPath, or adjacent label text.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Label text preceding the input element |
| `timeout` | number | No | `30000` | Maximum wait timeout for element to be actionable in milliseconds |
| `optional` | boolean | No | `false` | If `true`, suppresses exceptions if click fails or times out (returns `status: "skipped"`) |
| `wait_for_response` | string | No | - | Part of a URL the click is expected to request. The step ends only when a matching response arrives, so the next step reads the new data instead of relying on `logic.delay`. Find the URL in the browser's DevTools Network tab |
| `response_timeout` | number | No | `timeout` | Milliseconds to wait for that response |

With `wait_for_response`, the step returns `{"status": "clicked", "response_url": ..., "response_status": 200}`.

**Example:**
```markdown
### step_click_submit. Click Submit Button (`web.click`)
- **selector:** //input[@value='Submit']

### step_search. Search And Wait For Results (`web.click`)
- **selector:** `button.search`
- **wait_for_response:** /api/search
- **response_timeout:** 20000
```

---

### `web.type`
Fills text into an input or textarea element.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | Yes | `""` | Text to enter into the field |
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Case-sensitive label text matching preceding element |
| `secret` | boolean | No | `false` | Hide the typed text in logs and Hub telemetry. Text typed into a `type="password"` field is always hidden |

**Output:** `{"action": "web.type", "text": "<typed text, or **** when hidden>", "status": "typed"}`. Hidden text is also replaced wherever it appears in the run's records ([logging.md](logging.md#redaction)).

**Example:**
```markdown
### step_type_name. Fill First Name (`web.type`)
- **label:** First Name
- **text:** ${row.First Name}

### step_type_pin. Enter PIN (`web.type`)
- **selector:** #pin
- **text:** ${env.PORTAL_PIN}
- **secret:** true
```

---

### `web.get_text`
Extracts visible inner text from a target element.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Label identifier |

**Example:**
```markdown
### step_read_score. Read Score Message (`web.get_text`)
- **output_var:** `final_score`
- **selector:** //div[contains(@class, 'congratulations')]
```

---

### `web.get_attribute`
Extracts an HTML attribute value (such as `href`, `src`, `value`, `class`, or `data-*`) from a target element.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `attribute` | string | Yes | - | Name of attribute to extract (e.g. `"href"`, `"src"`, `"value"`) |
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Label identifier |

**Example:**
```markdown
### step_get_link. Extract Download Link (`web.get_attribute`)
- **output_var:** `file_url`
- **selector:** a.download-button
- **attribute:** href
```

---

### `web.get_table`
Reads an HTML `<table>` into a list of rows, one dictionary per row keyed by the header cells (`<thead> <th>`, or the first row when there is no header). Empty rows are skipped and cell text is trimmed. When the selector matches several tables, the first is used; add `:visible` to read the table currently shown (for example in tabs).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath of the table |
| `label` | string | Either | - | Label identifier |
| `columns` | list / dict | No | all columns | A list keeps only those columns, in that order. A dict keeps and renames them (`{"Source Header": "New Name"}`). A missing column fails the step and lists the actual headers |
| `numeric_columns` | list | No | `[]` | Columns (after renaming) converted to numbers; thousands separators are removed, and blank or `-` cells become empty. Text that is not a number fails the step |
| `add_columns` | dict | No | `{}` | Fixed values added as the first columns of every row, for example the currency a table belongs to |
| `min_rows` | number | No | `0` | Fail the step when fewer rows are found, so an empty result stops the flow instead of producing an empty report |
| `on_item_error` | string | No | `fail` | Kinenix 1.1.0. `skip` leaves out a row whose `numeric_columns` value is not a number, instead of failing the step; one warning in the log says how many rows were left out and why. `min_rows` counts the rows that are kept |
| `timeout` | number | No | `30000` | Milliseconds to wait for the table to exist, and for the content to change after each `next_selector` click |
| `next_selector` | string | No | - | The "next page" button or link of a paged table (Kinenix 0.4.0b1). It is clicked until it is gone or disabled (`disabled`, `aria-disabled="true"`, or a `disabled` class on it or its parents, as in DataTables and Bootstrap), and the rows of every page are returned in order. Each click waits until the content has changed |
| `max_pages` | number | No | `20` | The most pages read with `next_selector`. More pages than this fails the step instead of leaving pages out without notice |

**Example:**
```markdown
### step_read_rates. Read Currency Table (`web.get_table`)
- **output_var:** `currency_rows`
- **selector:** `.results table:visible`
- **columns:** {"Period": "Date", "Buying Rates Transfer": "Buying Transfer Rate"}
- **numeric_columns:** ["Buying Transfer Rate"]
- **add_columns:** {"Currency": "${currency}"}
- **min_rows:** 1
```

Returns, for example: `[{"Currency": "USD", "Date": "30 Dec 2024", "Buying Transfer Rate": 33.8296}, ...]`.

**Example (paged table):**
```markdown
### 3. Read All Invoices (`web.get_table`)
- **output_var:** `invoices`
- **selector:** `#invoices`
- **next_selector:** `#invoices_next`
- **max_pages:** 50
```

---

### `web.get_list`
Reads repeated elements, such as product cards or search results, into a list of rows (Kinenix 0.4.0b1). One row per element that matches `selector`; each field is found inside that element. Use it where `web.get_table` does not apply because the page shows cards instead of a `<table>`. Text is trimmed and runs of spaces and line breaks become one space.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Yes | - | CSS selector or XPath of the repeated element (one card, one result) |
| `fields` | dict | Yes | - | Column name to a selector inside each element. `".price"` reads the text, `"a@href"` reads an attribute, and `"."` (or `""`) reads the element itself. A field that is not found in an element is `""` |
| `numeric_fields` | list | No | `[]` | Fields converted to numbers, the way `number()` reads them in expressions: the first number in the text, so `"15,434.75 บาท/ปี"` is `15434.75`. Blank and `-` become empty; text with no number fails the step |
| `required_fields` | list | No | `[]` | Fields that must not be empty; an element without one fails the step, naming the element and what it reads |
| `add_columns` | dict | No | `{}` | Fixed values added as the first columns of every row, for example the request the results belong to |
| `min_rows` | number | No | `0` | Fail the step when fewer elements are found; with `on_item_error: skip`, only the items kept count |
| `on_item_error` | string | No | `fail` | Kinenix 1.1.0. `skip` leaves out an item that has an empty `required_fields` field or a `numeric_fields` field with no number, instead of failing the step and losing every page read so far. One warning in the log says how many items were left out and why (`skipped 2 of 40 item(s): item 14 has no 'title'; ...`), without their content |
| `timeout` | number | No | `30000` | Milliseconds to wait for the first element, and for the content to change after each `next_selector` click |
| `next_selector` | string | No | - | The "next page" or "more" control, as in `web.get_table`; the rows of every page are returned in order |
| `max_pages` | number | No | `20` | The most pages read with `next_selector`; more fails the step |

**Example:**
```markdown
### 5. Read Offered Packages (`web.get_list`)
- **output_var:** `packages`
- **selector:** `[data-testid=package-card]`
- **fields:** {"name": "h3", "premium": ".price", "details": "a@href"}
- **numeric_fields:** ["premium"]
- **required_fields:** ["name"]
- **add_columns:** {"request_id": "${req.request_id}"}
- **min_rows:** 1
```

Returns, for example: `[{"request_id": "R001", "name": "Class 1 Plus", "premium": 15434.75, "details": "/packages/123"}, ...]`.

**Example: every page, leaving out books that cannot be read (Kinenix 1.1.0):**
```markdown
> Requires: kinenix>=1.1.0

### 3. Read All Books (`web.get_list`)
- **output_var:** `books`
- **selector:** `article.product_pod`
- **fields:** {"title": "h3 a@title", "price": ".price_color", "rating_class": "p.star-rating@class"}
- **numeric_fields:** ["price"]
- **required_fields:** ["title"]
- **next_selector:** `li.next a`
- **max_pages:** 50
- **on_item_error:** skip
```

A page that does not load still fails the step. To go on after a page that fails, loop over the pages yourself with `logic.loop` and `times`, `on_error: next_item` on the read, and `logic.break` when there is no next page ([logic.loop](#logicloop)).

---

### `web.wait_for`
Waits for an element to satisfy a desired state (or performs an explicit pause).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Optional | - | Target element CSS selector or XPath |
| `label` | string | Optional | - | Target element label |
| `state` | string | No | `"visible"` | Expected state: `"visible"`, `"attached"`, `"detached"`, `"hidden"` |
| `timeout` | number | No | `30000` | Maximum wait timeout in milliseconds |

*Note:* If neither `selector` nor `label` is specified, `web.wait_for` acts as a browser-synchronized pause for `timeout` milliseconds.

**Example:**
```markdown
### step_wait_modal. Wait For Success Modal (`web.wait_for`)
- **selector:** #success-dialog
- **state:** visible
- **timeout:** 15000
```

---

### `web.is_visible`
Checks if an element is currently visible on the page within an optional timeout. Returns a boolean (`true` or `false`) without raising an exception. Useful for conditional branching (e.g. cookie consent banners, optional modals).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Target element by adjacent label |
| `timeout` | number | No | `2000` | Max milliseconds to wait for the element to become visible. If `<= 0`, checks immediately. |

**Example:**
```markdown
### step_check_cookie_banner. Check Cookie Banner Visibility (`web.is_visible`)
- **output_var:** `has_cookie_banner`
- **selector:** button:has-text('Accept recommended cookies')
- **timeout:** 2000
```

---

### `web.press`
Sends a keyboard key press or key combination to a specific element or to the active page.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `key` | string | Yes | - | Key name or chord (e.g. `"Enter"`, `"Tab"`, `"Escape"`, `"Control+A"`) |
| `selector` | string | Optional | - | Specific element to receive keystroke (omitted for global page) |
| `label` | string | Optional | - | Target element by adjacent label |

**Example:**
```markdown
### step_press_enter. Submit Form via Enter Key (`web.press`)
- **selector:** input#search-box
- **key:** Enter
```

---

### `web.scroll`
Scrolls the page in a specified direction or scrolls a specific element into visible view.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `direction` | string | No | `"down"` | Scroll direction: `"down"`, `"up"`, `"bottom"`, `"top"` |
| `amount` | number | No | `500` | Pixels to scroll (when direction is `"down"` or `"up"`) |
| `selector` | string | Optional | - | Scroll this specific element into view |
| `label` | string | Optional | - | Scroll element associated with this label into view |

**Example:**
```markdown
### step_scroll_down. Scroll Down To Load Content (`web.scroll`)
- **direction:** down
- **amount:** 800
```

---

### `web.hover`
Hovers the mouse pointer over a target element to trigger dropdowns or tooltip menus.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Label identifier |
| `timeout` | number | No | `30000` | Maximum hover timeout in milliseconds |

**Example:**
```markdown
### step_hover_menu. Open Navigation Dropdown (`web.hover`)
- **selector:** .nav-dropdown-trigger
```

---

### `web.switch_tab`
Switches active focus to another open tab or window in the browser context.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `index` | number | Optional | - | Zero-based index of open tab (`0` for first, `1` for second, `-1` for latest) |
| `url_pattern` | string | Optional | - | Substring or URL pattern matching target tab |
| `title` | string | Optional | - | Case-insensitive substring matching target page title |

*Note:* If no parameters are provided, switches to the most recently opened tab.

**Example:**
```markdown
### step_switch_dashboard. Switch to Dashboard Tab (`web.switch_tab`)
- **url_pattern:** /dashboard
```

---

### `web.download`
Downloads a file by clicking an export button or resolving a direct link.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Yes | - | Element triggering the download or containing `href` |
| `target_path` | string | No | `"downloads/downloaded_file"` | Destination path for saved file |
| `timeout` | number | No | `30000` | Download timeout in milliseconds |

**Example:**
```markdown
### step_download_excel. Download Challenge Excel File (`web.download`)
- **output_var:** `download_info`
- **selector:** //a[contains(text(),'Download Excel')]
- **target_path:** ./assets/challenge.xlsx
```

---

### `web.choose`
Picks an option in a dropdown by its visible name (Kinenix 0.4.0b1). It works with the custom dropdowns of modern sites (Radix and shadcn Select, cmdk combobox, Headless UI, MUI): it clicks the dropdown, types into its search box when `search` is `true`, and clicks the option with that name. When `selector` points to a native `<select>`, it selects the option with that label. When the option is not there, the error lists the options that are, for example `option 'HONDAX' not found; available: HONDA, HONDA BIGWING, HYUNDAI`.

Options are found by their accessibility role (`role="option"`), which these libraries set; `<option>` elements of other native selects on the page are not counted.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath of the element that opens the dropdown (the button or input you click), or of a native `<select>` |
| `label` | string | Either | - | Label identifier of that element |
| `option` | string | Yes | - | Name of the option to pick. An empty value (for example a missing variable) fails the step |
| `match` | string | No | `exact` | How `option` is compared with the names shown. `exact`: the whole name, so `HONDA` does not pick `HONDA BIGWING`. `loose` (Kinenix 0.5.0b1): the same name apart from spaces, hyphens, dots, and similar marks and case, so `HRV`, `hr-v`, and `HR V` pick `HR-V`; when several names match loosely, the step fails and lists them instead of guessing. `contains`: the first name that contains `option`, ignoring case. An exact name always wins |
| `exact` | boolean | No | `true` | The older spelling: `false` is `match: contains` |
| `search` | boolean | No | `false` | Type into the dropdown's search box before picking, for long lists that show only what matches |
| `search_text` | string | No | `option` | What to type into the search box. The site filters by what is typed, so with `match: loose` type the start of the name as the site writes it, for example `HR` for `HR-V` |
| `search_selector` | string | No | - | The search box, when it is not found by itself (cmdk input, `role=combobox` input, `type=search` input, or an input in the open dialog or list) |
| `timeout` | number | No | `10000` | Milliseconds to wait for the dropdown and for the option to appear |

**Example:**
```markdown
### 3. Car Brand (`web.choose`)
- **selector:** `[data-testid=carBrand]`
- **option:** ${req.brand}

### 4. Car Model (`web.choose`)
- **selector:** `[data-testid=carModel]`
- **option:** ${req.model}
- **search:** true
```

**Names written differently by people:** `match: loose` covers spacing, marks, and case (`HRV` for `HR-V`). For names that really differ, such as a short form or a Thai and an English name, keep a table in `config/config.json` and look the name up, keeping it as written when it is not in the table:

```json
{"models": {"HRV": "HR-V", "แจ๊ส": "JAZZ"}}
```

```markdown
> Requires: kinenix>=0.5.0b1

### 4. Car Model (`web.choose`)
- **selector:** `[data-testid=carModel]`
- **option:** ${default(config.models[req.model], req.model)}
- **match:** loose
- **search:** true
- **search_text:** ${substring(default(config.models[req.model], req.model), 0, 2)}
```

**Output:** `{"option": "<name of the option picked>", "status": "chosen"}`

---

### `web.select_option`
Selects one or more options in an HTML `<select>` dropdown element. For custom dropdowns that are not a `<select>`, use [`web.choose`](#webchoose). Supports automatic semantic AI matching via OpenThai-SystemOne / Ollama to map abbreviations (e.g. "กทม." -> "กรุงเทพมหานคร") against live page options.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression of `<select>` element |
| `label` | string | Either | - | Label identifying the dropdown |
| `value` | string | Optional | - | Option value attribute to select |
| `text` / `label_text` | string | Optional | - | Visible text label of the option to select |
| `index` | number | Optional | - | Zero-based index of option to select |
| `ai_match` | boolean | No | `false` | When `true`, automatically queries all `<option>` items from the element and uses OpenThai-SystemOne to resolve fuzzy/abbreviated text semantically |
| `systemone_url` | string | No | `"http://localhost:8000"` | OpenThai-SystemOne API base URL |
| `fallback_to_ollama` | boolean | No | `true` | Fallback to Ollama if SystemOne server is unreachable |

**Example (Exact Match) in `flow.md` (Markdown):**
```markdown
### step_select_province. Select Province (`web.select_option`)
- **selector:** select#province
- **text:** Bangkok
```

**Example (AI Semantic Match) in `flow.md` (Markdown):**
```markdown
### step_select_province_ai. Select Province Semantically (`web.select_option`)
- **selector:** select#province
- **text:** ${row.Province}
- **ai_match:** true
```

---

### `web.upload_file`
Sets file paths onto an HTML `<input type="file">` upload element.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression of `<input type="file">` |
| `label` | string | Either | - | Adjacent label identifier |
| `file_path` | string | Yes | - | Path to file to upload (resolved relative to flow bundle or absolute) |

**Example:**
```markdown
### step_upload_tax_form. Upload Tax Form Document (`web.upload_file`)
- **selector:** input#file-upload
- **file_path:** ./assets/tax_form_2026.pdf
```

---

### `web.check`
Checks an HTML checkbox or selects a radio button.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Label identifier |
| `timeout` | number | No | `30000` | Timeout in milliseconds |

**Example:**
```markdown
### step_agree_terms. Agree to Terms and Conditions (`web.check`)
- **selector:** input#agree
```

---

### `web.uncheck`
Unchecks an HTML checkbox element.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `selector` | string | Either | - | CSS selector or XPath expression |
| `label` | string | Either | - | Label identifier |
| `timeout` | number | No | `30000` | Timeout in milliseconds |

**Example:**
```markdown
### step_opt_out. Uncheck Marketing Emails (`web.uncheck`)
- **selector:** input#newsletter
```

---

### `web.screenshot`
Captures a screenshot of the current page.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | No | `"screenshot.png"` | Destination file path (relative to bundle or absolute) |
| `full_page` | boolean | No | `false` | Capture complete scrollable page |

**Example:**
```markdown
### step_capture. Capture Page Screenshot (`web.screenshot`)
- **path:** ./assets/result.png
- **full_page:** false
```

---

### `web.close`
Closes current page, browser context, and terminates Playwright session.

**Parameters:** None.

**Example:**
```markdown
### step_close_browser. Close Browser Session (`web.close`)
```

---

## Data, Excel, and CSV (`excel.*`, `csv.*`)

Provides zero-license tabular data processing via Pandas and OpenPyXL.

### `excel.read`
Reads an Excel sheet into an in-memory list of dictionaries (records). Empty cells are `None` (never `NaN`), and a column of whole numbers stays whole even when some cells are empty (`2023`, not `2023.0`).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string | Yes | - | Path to .xlsx or .xls file (relative paths resolved against bundle) |
| `sheet_name` | string / int | No | `0` | Sheet name or index to read |
| `clean_headers` | boolean | No | `true` | Strip leading and trailing whitespace from column names |
| `as_text` | boolean | No | `false` | Return every cell as text, with `""` for empty cells |

**Example:**
```markdown
### step_read_excel. Read Excel Data (`excel.read`)
- **output_var:** `challenge_data`
- **file_path:** ./assets/challenge.xlsx
- **clean_headers:** true
```

---

### `excel.write`
Writes a list of dictionaries or single dictionary to an Excel spreadsheet. A relative `file_path` is resolved against the flow bundle directory, like `csv.write`, and missing folders are created. Rows are written in the order given, so group them before writing (for example by appending one currency at a time).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string | Yes | - | Output path for generated Excel workbook |
| `data` | list / dict | Yes | `[]` | List of dictionaries or data records to export |
| `sheet_name` | string | No | `"Sheet1"` | Destination sheet name |
| `columns` | list | No | data order | Column order; columns missing from the data are added empty |

**Example:**
```markdown
### step_save_audit. Save Non-Programmers Audit Report (`excel.write`)
- **file_path:** ./output/non_programmers_audit.xlsx
- **data:** ${non_programmers}
- **sheet_name:** AuditReport
- **columns:** ["First Name", "Role in Company"]
```

---

### `csv.read`
Reads a delimiter-separated text file (CSV, TSV, semicolon-separated) into a list of dictionaries. Each column gets one type from its values:

| Column values | Result |
|---|---|
| All whole numbers, such as `2023` | `int`; empty cells `None` |
| Numbers with decimals, such as `15434.75` | `float`; empty cells `None` |
| All `true` / `false` (any case) | `bool`; empty cells `None` |
| Anything else, including codes with a leading zero (`0812345678`, `00100`) and text such as `NA` | text exactly as written; empty cells `None` |

A column with a single non-numeric value stays text, so phone numbers, postal codes, and IDs are never turned into numbers. Set `as_text: true` to get every cell as text instead, with `""` for empty cells.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string | Yes | - | Path to CSV file (resolved against bundle or absolute) |
| `delimiter` | string | No | `","` | Field separator character (e.g. `","`, `";"`, `"\t"`) |
| `encoding` | string | No | `"utf-8-sig"` | File character encoding. The default also reads files saved by Excel with a byte order mark. Thai files from older systems are often `cp874`; the error message says so when the file cannot be read |
| `clean_headers` | boolean | No | `true` | Strip leading and trailing whitespace from column headers |
| `as_text` | boolean | No | `false` | Return every cell as text, with `""` for empty cells |

**Example:**
```markdown
### step_read_csv. Load Customer Records (`csv.read`)
- **output_var:** `customers`
- **file_path:** ./data/customers.csv
- **delimiter:** ,
- **clean_headers:** true
```

---

### `csv.write`
Exports a list of dictionaries or single record to a CSV file. By default the file starts with a UTF-8 byte order mark, so Excel shows Thai and other non-English text correctly when the file is opened by double-clicking. Set `encoding: utf-8` for a system that does not accept the mark.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `file_path` | string | Yes | - | Output CSV file path |
| `data` | list / dict | Yes | `[]` | Records to export |
| `columns` | list | No | `null` | Explicit list and order of column names |
| `encoding` | string | No | `"utf-8-sig"` | File character encoding; `utf-8-sig` is UTF-8 with a byte order mark for Excel |
| `append` | boolean | No | `false` | Add the rows to the end of an existing file. The header is written only when the file is new or empty; the rows follow the existing file's column order, and a column the file does not have stops the step |

**Example:**
```markdown
### step_export_csv. Export Processed Data to CSV (`csv.write`)
- **file_path:** ./output/results.csv
- **data:** ${results}
- **columns:** ["id", "name", "status", "timestamp"]
```

---

## File System Operations (`file.*`)

Built-in operations for file checking, copying, moving, and deletion. Relative paths are automatically resolved relative to the active flow bundle directory (`__flow_dir__`).

### `file.exists`
Checks whether a file or directory exists on the local filesystem, returning a boolean (`true` / `false`).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | - | File or directory path to check |

**Example:**
```markdown
### step_check_file. Check If Input File Exists (`file.exists`)
- **output_var:** `is_input_ready`
- **path:** ./input/data.csv
```

---

### `file.copy`
Copies a file or an entire directory tree to a target destination.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `source` | string | Yes | - | Source file or folder path |
| `destination` | string | Yes | - | Destination file or folder path |
| `overwrite` | boolean | No | `true` | Overwrite destination if it already exists |

**Example:**
```markdown
### step_backup_file. Backup Report (`file.copy`)
- **source:** ./output/report.xlsx
- **destination:** ./backups/report_backup.xlsx
- **overwrite:** true
```

---

### `file.move`
Moves or renames a file or directory.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `source` | string | Yes | - | Source file or folder path |
| `destination` | string | Yes | - | Destination file or folder path |
| `overwrite` | boolean | No | `true` | Overwrite destination if it already exists |

**Example:**
```markdown
### step_archive_file. Move Processed File to Archive (`file.move`)
- **source:** ./input/orders.csv
- **destination:** ./archive/orders_processed.csv
- **overwrite:** true
```

---

### `file.delete`
Deletes a file or recursively removes a directory.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | - | Path of file or directory to remove |
| `missing_ok` | boolean | No | `true` | Do not raise an error if target path does not exist |

**Example:**
```markdown
### step_cleanup_temp. Delete Temporary Files (`file.delete`)
- **path:** ./temp/working_cache.tmp
- **missing_ok:** true
```

---

### `file.zip`
Packs files and folders into one zip file (deflate compression), for example to attach everything a run produced to an email. A folder keeps its name as the top level inside the zip, so `./output` is stored as `output/...`. If the zip file lies inside a folder being packed, it is left out, so `./output` can be zipped into `./output/run.zip` on every run. The zip is written under a temporary name first and renamed when complete, so a failure never leaves a half-written file. Paths are relative to the flow folder.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `source` | string or list | Yes | - | A file or folder, or a list of files and folders. Two entries that would be stored under the same name (for example two `report.csv` files) stop the step with an error |
| `destination` | string | Yes | - | Path of the zip file to create; missing parent folders are created |
| `overwrite` | boolean | No | `true` | Replace an existing zip file. With `false`, an existing file stops the step |

**Example:**
```markdown
### 18. Zip Run Output (`file.zip`)
- **source:** ./output
- **destination:** ./outbox/run.zip
- **output_var:** `packed`

### 19. Email Results (`email.send`)
- **to:** `${config.email.to}`
- **subject:** Insurance packages
- **body:** All files from this run are attached.
- **attachments:** ["${packed.zip_path}"]
```

**Output Format:**
```json
{
  "zip_path": "/home/user/kinenix-flows/tiph/outbox/run.zip",
  "files_added": 7,
  "size_bytes": 184320,
  "status": "zipped"
}
```

---

### `file.unzip`
Extracts a zip file into a folder. Every entry is checked before anything is written: an entry that would land outside the destination folder (for example `../../etc/passwd`) stops the step, and so does an existing file when `overwrite` is `false`. Paths are relative to the flow folder.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `source` | string | Yes | - | Path of the zip file |
| `destination` | string | No | zip path without `.zip` | Folder to extract into; created if missing. `./inbox/orders.zip` extracts into `./inbox/orders` by default |
| `overwrite` | boolean | No | `true` | Replace files that already exist in the destination |

**Example:**
```markdown
### 2. Extract Received Orders (`file.unzip`)
- **source:** ./inbox/orders.zip
- **destination:** ./work/orders
- **output_var:** `extracted`
```

**Output Format:**
```json
{
  "destination": "/home/user/kinenix-flows/orders/work/orders",
  "files": ["orders_2026-10.csv", "notes/readme.txt"],
  "files_extracted": 2,
  "status": "unzipped"
}
```

---

### `file.list`
Lists the files or folders in a folder, so a flow can loop over them with `logic.loop` (for example every CSV that arrived in an inbox) or pick the newest one. Each item carries its name, path, size, and modification time, so no separate "file info" action is needed. Paths are relative to the flow folder. An empty result is an empty list, which a `logic.if` or the `condition` of `flow.fail` can check.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | - | Folder to list; a missing folder stops the step |
| `pattern` | string | No | `*` | File name pattern, for example `*.csv` or `orders_2026-*.xlsx` |
| `recursive` | boolean | No | `false` | Also look in subfolders; `relative_path` then includes the subfolder |
| `type` | string | No | `files` | `files`, `folders`, or `all` |
| `sort_by` | string | No | `name` | `name`, `modified`, or `size` |
| `descending` | boolean | No | `false` | Reverse the order, for example newest or largest first |
| `limit` | integer | No | - | Keep only the first N items after sorting; `1` with `sort_by: modified` and `descending: true` gives the newest file |

**Example:**
```markdown
### 1. Find Order Files (`file.list`)
- **path:** ./inbox
- **pattern:** *.csv
- **sort_by:** modified
- **output_var:** `files`

### 2. Handle Each File (`logic.loop`)
- **items:** `${files}`
- **item_var:** `f`
- **Sub-steps:**
  - Read Orders (`csv.read`):
    - **file_path:** `${f.path}`
    - **output_var:** `orders`
  - Move To Archive (`file.move`):
    - **source:** `${f.path}`
    - **destination:** ./archive/${f.name}
```

**Output Format** (one item per file):
```json
[
  {
    "name": "orders_2026-10.csv",
    "stem": "orders_2026-10",
    "extension": ".csv",
    "path": "/home/user/kinenix-flows/orders/inbox/orders_2026-10.csv",
    "relative_path": "orders_2026-10.csv",
    "is_folder": false,
    "size": 2048,
    "modified": "2026-10-09T08:15:02"
  }
]
```

---

### `file.read_text`
Reads a text file as one string, as a list of lines, or as parsed JSON, for example an email body template, a JSON file from another system, or a list of IDs one per line. The default encoding also reads files saved with a byte order mark (Excel, Notepad). Paths are relative to the flow folder.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | - | File to read |
| `format` | string | No | `text` | `text` returns one string; `lines` returns a list of lines without line breaks (ready for `logic.loop`); `json` returns the parsed object or list |
| `encoding` | string | No | `utf-8-sig` | Text encoding. Thai files from older Windows systems are usually `cp874` (or `tis-620`); the error message suggests this when UTF-8 fails |

**Example:**
```markdown
### 3. Read Email Template (`file.read_text`)
- **path:** ./assets/email_body.txt
- **output_var:** `email_body`

### 4. Read Policy List (`file.read_text`)
- **path:** ./inbox/policies.txt
- **format:** lines
- **output_var:** `policy_ids`
```

---

### `file.write_text`
Writes text to a file, replacing it or adding to its end, for example a run summary, a log line per processed item, or a JSON file for another system. A list or object in `content` is written as formatted JSON (Thai text stays readable). With `append`, the text is added as a line: a line break follows it if it does not already end with one. Missing parent folders are created. Paths are relative to the flow folder.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | - | File to write |
| `content` | string, list, or object | Yes | - | Text to write; a list or object is written as JSON |
| `append` | boolean | No | `false` | Add to the end of the file as a new line instead of replacing it |
| `encoding` | string | No | `utf-8` | Text encoding, for example `cp874` for a system that only reads Thai Windows encoding |

**Example:**
```markdown
### 7. Log Processed Plan (`file.write_text`)
- **path:** ./output/run_log.txt
- **content:** ${plan.brand} ${plan.model}: ${plan_count} packages
- **append:** true
```

**Output Format:**
```json
{
  "path": "/home/user/kinenix-flows/tiph/output/run_log.txt",
  "characters_written": 24,
  "mode": "append",
  "status": "written"
}
```

---

### `file.create_folder`
Creates a folder, including any missing parent folders. An existing folder is not an error. Most actions that write files already create their parent folders; use this for a folder that must exist before anything is written into it, for example a per-run folder that a browser download goes to. Paths are relative to the flow folder.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | - | Folder to create. A file with the same name stops the step |

**Example:**
```markdown
### 1. Prepare Screenshot Folder (`file.create_folder`)
- **path:** ./output/screenshots
```

**Output Format:**
```json
{
  "path": "/home/user/kinenix-flows/tiph/output/screenshots",
  "created": true,
  "status": "created"
}
```

---

## Control Flow and Logic (`logic.*`)

Core orchestration primitives for variable manipulation, loops, conditions, and error recovery.

### Step Resilience and Error Handling

Every step in Kinenix can define an optional `error_handler` strategy to make execution resilient against transient network hiccups or flaky selectors:

**Configuration Fields:**
| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `on_error` | string | No | `"stop"` | What happens after the last attempt: `"fail"` or `"stop"` (the flow fails and `## On Error` runs), `"continue"` (record the failure and go on with the next step; it counts as a failure), `"ignore"` (Kinenix 1.1.0: record the failure and go on, without counting it, for a step whose failure does not matter), `"next_item"` (inside a `logic.loop`: record the failure and go on with the next item, [flow_markdown_spec.md](flow_markdown_spec.md#31-retries-and-on_error-on-a-step)), or `"retry"` (same as `"fail"`; deprecated, removed in 2.0) |
| `max_retries` | number or `${...}` | No | `0` | Extra attempts after the first failure, made before `on_error` decides (e.g. `3` = 1 attempt + 3 retries). Business errors (such as from `flow.fail`) are never retried |
| `retry_interval` | number or `${...}` | No | `1.0` | Delay in seconds between attempts |
| `error_message` | string or `${...}` | No | `null` | Kinenix 1.1.0: the message of the step's failure instead of the action's, in the log, `${error.message}`, and on the Hub. `${error.message}` inside it is the action's own message: `เปิดเว็บไม่ได้: ${error.message}` |
| `fallback_step_id` | string | No | `null` | Deprecated, removed in 2.0: target step ID to execute as a recovery handler upon step failure. Use `on_error: continue` and a next step with a condition on `${error}`, or `## On Error` |

In `flow.md`, write the fields as ordinary step keys. The compiler moves them into `error_handler`; they are not passed to the action. The JSON form `- **error_handler:** {"on_error": "continue", ...}` is also accepted.

Since 0.2.0b4, `max_retries` retries with any `on_error`; before, it worked only with `on_error: retry`. For one place that handles every failure of a flow, use `## On Error` and `## Finally` ([flow_markdown_spec.md](flow_markdown_spec.md#3-failures-retries-on-error-and-finally)).

`on_error: retry` and `fallback_step_id` still work in 1.x; `kinenix validate` and every run warn that they will be removed in Kinenix 2.0.

**Example with retries and a recovery step in `flow.md` (Markdown):**
```markdown
### 1. Fetch Orders API (`http.request`)
- **output_var:** `orders_data`
- **url:** https://api.example.com/orders
- **max_retries:** 3
- **retry_interval:** 2.0
- **on_error:** continue

### 2. Use Offline Cache (`file.read_text`)
- **condition:** `${orders_data} is empty`
- **path:** ./cache/orders.json
- **output_var:** `orders_data`
```

---

### `logic.set_variable`
Assigns a value to a named execution context variable.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Variable name to create or update |
| `value` | any | Yes | Value or evaluated expression |

**Example:**
```markdown
### step_set_counter. Initialize Counter (`logic.set_variable`)
- **name:** processed_count
- **value:** 0
```

---

### `logic.delay`
Pauses execution for a specified duration.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `seconds` | number | No | `1.0` | Sleep duration in seconds |

**Example:**
```markdown
### step_wait. Wait for Page Stabilization (`logic.delay`)
- **seconds:** 2.5
```

---

### `logic.if`
Conditionally branches execution into `sub_steps` (when condition evaluates to true) or `else_steps` (when false).

`on_error`, `max_retries`, and `retry_interval` have no effect on this step, and `kinenix validate` reports them. Put them on the steps under `Sub-steps` and `Else-steps` that may fail.

**Supported Operators:**
- `equals`, `==`, `eq`
- `not_equals`, `!=`, `neq`
- `greater_than`, `>`, `gt`
- `greater_than_or_equal`, `>=`, `gte`
- `less_than`, `<`, `lt`
- `less_than_or_equal`, `<=`, `lte`
- `contains`, `not_contains` (right is part of left)
- `in`, `not_in` (left is part of right; with a list, an item equals left)
- `starts_with`, `ends_with`
- `is_empty`, `is_not_empty`

In `condition`, write the operators as words: `contains`, `not contains`, `in`, `not in`, `starts with`, `ends with`, `is empty`, `is not empty` (see [Conditions](flow_markdown_spec.md#c-conditions)).

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `left` | any | Yes* | Left-hand operand |
| `operator` | string | No (default: equals) | Comparison operator |
| `right` | any | No | Right-hand operand |
| `condition` | string | Yes* | Alternatively, single expression such as `"${val} == target"` |

*\*Note: Either `left` or `condition` parameter is required.*

**Example:**
```markdown
### sub_check_role. Check If Role is Programmer (`logic.if`)
- **left:** ${row.Role in Company}
- **operator:** equals
- **right:** Programmer
- **Sub-steps:**
  - Fill Form (`web.type`):
    - **label:** First Name
    - **text:** ${row.First Name}
- **Else-steps:**
  - Append to Audit (`logic.append`):
    - **target:** non_programmers
    - **item:** {"First Name": "${row.First Name}", "Role": "${row.Role in Company}"}
```

---

### `logic.loop`
Iterates over an array or list of objects, binding each element to an item variable, or repeats its sub-steps a number of times (`times`, Kinenix 1.1.0). `logic.break` leaves it early, and `logic.next` goes on with the next item.

`on_error`, `max_retries`, and `retry_interval` have no effect on this step, and `kinenix validate` reports them. Put them on the sub-steps that may fail; `on_error: next_item` there goes on with the next item.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `items` | list / string | Either | Array or variable reference `${var}` to iterate |
| `times` | number or `${...}` | Either | Kinenix 1.1.0: repeat the sub-steps this many times (0 to 10,000) instead of iterating over `items`; `item_var` holds 1, 2, 3, ... A loop has `items` or `times`, not both. Running out of `times` is not an error |
| `item_var` | string | No (default: item) | Context variable name representing the current iteration item; `${<item_var>_index}` holds its position from 0 |
| `item_label` | string | No | How an item is named in `${error.loop.item}` and in failure records, e.g. `${row.request_id} ${row.brand}`. Default: the item's first three fields |

**Example:**
```markdown
### step_loop_rows. Iterate Dataset Rows (`logic.loop`)
- **items:** ${challenge_data}
- **item_var:** row
- **Sub-steps:**
  - Process Row Item (`logic.if`):
    - **left:** ${row.Status}
    - **operator:** equals
    - **right:** Active
```

**Example: page by page until the last page (Kinenix 1.1.0):**
```markdown
> Requires: kinenix>=1.1.0

### 3. Each Page (`logic.loop`)
- **times:** ${config.max_pages}
- **item_var:** page
- **item_label:** Page ${page}
- **Sub-steps:**
  - Read The Books (`web.get_list`):
    - **selector:** article.product_pod
    - **fields:** {"title": "h3 a@title", "price": ".price_color"}
    - **output_var:** books
    - **on_error:** next_item
  - Keep The Books (`logic.append`):
    - **target:** all_books
    - **item:** ${books}
    - **extend:** true
  - Is There A Next Page (`web.is_visible`):
    - **selector:** li.next a
    - **output_var:** next_visible
  - Last Page (`logic.break`):
    - **condition:** `${next_visible} == false`
  - Next Page (`web.click`):
    - **selector:** li.next a
```

**Output:** `{"total_items_processed": 4, "stopped_early": true}`: how many iterations ran, and whether a `logic.break` ended the loop.

---

### `logic.break`
Kinenix 1.1.0. Leaves the innermost `logic.loop` it is in: the rest of this iteration is skipped, no further iteration starts, and the flow goes on after the loop. Put a `condition` on it to say when; without one it always leaves. It works in loops over `items` and with `times`, inside `logic.if` branches, and in `## On Error` and `## Finally`.

It leaves only a loop of its own flow. In a subflow called for each item, return a value and put `logic.break` in the caller's loop. Outside a loop, `kinenix validate` reports it and a run stops at it with exit code 4. Items the loop does not reach because of a break are not counted as work items. `on_error`, `max_retries`, and `error_message` have no effect on it.

**Parameters:** none.

**Example:**
```markdown
  - Last Page (`logic.break`):
    - **condition:** `${next_visible} == false`
```

**Output:** `{"status": "loop stopped"}`

---

### `logic.next`
Kinenix 1.1.0. Skips the rest of this iteration of the innermost `logic.loop` and goes on with its next item, usually behind a `condition`. The item counts as done, unless one of its steps failed earlier. To skip because a step failed, use `on_error: next_item` on that step instead; the item then counts as failed.

Like `logic.break`, it works only in a loop of its own flow: outside a loop, `kinenix validate` reports it and a run stops at it with exit code 4. `on_error`, `max_retries`, and `error_message` have no effect on it.

**Parameters:** none.

**Example:**
```markdown
  - Skip Out Of Stock (`logic.next`):
    - **condition:** `${book.availability} contains Out of stock`
  - Open The Book (`web.click`):
    - **selector:** h3 a
```

**Output:** `{"status": "next item"}`

---

### `logic.append`
Appends an item, dictionary, or primitive value to a list in context variables. If the target variable does not exist, it initializes an empty list.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `target` | string | Yes | Name of the list variable in context |
| `item` | any | Yes | Item or object to append |
| `extend` | boolean | No | When `true`, `item` must be a list and each of its elements is appended (for example the rows returned by `web.get_table`), instead of the list as one item. Default `false` |

**Example:**
```markdown
### append_record. Add Non-Programmer to List (`logic.append`)
- **target:** non_programmers
- **item:** {"First Name": "${row.First Name}", "Role in Company": "${row.Role in Company}"}

### append_rows. Collect Currency Rows (`logic.append`)
- **target:** fx_rows
- **item:** `${currency_rows}`
- **extend:** true
```

---

## Dates (`date.*`)

Works out dates relative to the day the flow runs, so a scheduled flow always processes the right period without editing its config.

---

### `date.calc`
Starts from a date (today by default), optionally moves it by days, weeks, months, or years, optionally snaps it to the start or end of a week, month, or year, and returns the result split into parts. Steps in order: read `date`, add `add_years` and `add_months`, add `add_weeks` and `add_days`, then apply `snap`. Month arithmetic keeps the day where it can and otherwise uses the last day of the month (31 March minus one month is 28 or 29 February). "Today" is the worker's local date, so set the machine's time zone correctly.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `date` | string | No | `today` | Starting point: `today` (midnight), `now` (current time), an ISO date or date-time such as `2024-12-01` or `2024-12-01T09:30`, or a date in another format together with `input_format` |
| `input_format` | string | No | - | Python `strptime` pattern for reading `date`, for example `%d/%m/%Y` for `31/12/2024` |
| `add_days` | integer | No | `0` | Days to add; negative moves back |
| `add_weeks` | integer | No | `0` | Weeks to add; negative moves back |
| `add_months` | integer | No | `0` | Months to add; negative moves back |
| `add_years` | integer | No | `0` | Years to add; negative moves back |
| `snap` | string | No | - | `start_of_month`, `end_of_month`, `start_of_year`, `end_of_year`, `start_of_week` (Monday), or `end_of_week` (Sunday) |
| `format` | string | No | `%Y-%m-%d` | Python `strftime` pattern for the `text` field of the result, for example `%d-%m-%Y` or `%Y%m%d_%H%M` |

**Example:**
```markdown
### 1. First Day Of Last Month (`date.calc`)
- **add_months:** -1
- **snap:** start_of_month
- **output_var:** `start`

### 2. Last Day Of Last Month (`date.calc`)
- **add_months:** -1
- **snap:** end_of_month
- **format:** %d-%m-%Y
- **output_var:** `end`

### 3. Choose Start Month (`web.select_option`)
- **selector:** `.react-datepicker select >> nth=0`
- **text:** `${start.month_name}`

### 4. Report File Name (`logic.set_variable`)
- **name:** report_path
- **value:** ./output/fx_${start.year}-${start.month}.csv
```

**Output Format** (run on 8 October 2026, step 2 above):
```json
{
  "text": "30-09-2026",
  "date": "2026-09-30",
  "datetime": "2026-09-30T00:00:00",
  "year": 2026,
  "month": 9,
  "day": 30,
  "month_name": "September",
  "month_abbr": "Sep",
  "weekday": "Wednesday",
  "weekday_number": 3,
  "days_in_month": 30,
  "hour": 0,
  "minute": 0
}
```

Month and weekday names are always English, whatever the machine's language. `weekday_number` runs from 1 (Monday) to 7 (Sunday). `year`, `month`, `day`, `hour`, and `minute` are numbers; inside a longer text such as a selector or file name they appear without leading zeros (`9`, not `09`). Use `text` with `format` when leading zeros are needed.

---

## HTTP API Integration (`http.*`)

Enables direct REST API interaction without external browser overhead.

### `http.request`
Executes an HTTP request and outputs status code, response headers, and body. A response with status 400 or higher fails the step, so a server error does not pass unnoticed; `max_retries` and `on_error` apply as for any step. Set `fail_on_error: false` for a flow that checks `status_code` itself.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | Yes | - | Request URL endpoint |
| `method` | string | No | `"GET"` | HTTP method (GET, POST, PUT, DELETE, PATCH) |
| `headers` | dict | No | `{}` | HTTP request headers |
| `payload` | dict / list / string | No | `null` | Request body (a dict or list is sent as JSON, a string as it is) |
| `timeout` | number | No | `30` | Request timeout in seconds |
| `fail_on_error` | boolean | No | `true` | Fail the step on a response with status 400 or higher. With `false` the step succeeds and `status_code` holds the status |

**Example:**
```markdown
### step_send_webhook. Notify Notification Webhook (`http.request`)
- **output_var:** `api_response`
- **url:** https://api.example.com/v1/notify
- **method:** POST
- **headers:** {"Content-Type": "application/json", "Authorization": "Bearer ${env.API_KEY}"}
- **payload:** {"status": "completed", "total_processed": 10}
```

To handle a status yourself, such as a 404 that means the order does not exist yet:

```markdown
### 1. Look Up Order (`http.request`)
- **url:** https://api.example.com/v1/orders/${order_id}
- **fail_on_error:** false
- **output_var:** `order`

### 2. Stop When Missing (`flow.fail`)
- **condition:** `${order.status_code} == 404`
- **message:** Order ${order_id} does not exist
```

---

### `http.download`
Downloads a file from an HTTP/HTTPS URL directly to the filesystem without launching a browser.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | Yes | - | Direct HTTP/HTTPS file URL to download |
| `target_path` | string | Yes | - | Local path to save the downloaded file |
| `timeout` | number | No | `60` | Network download timeout in seconds |

**Example:**
```markdown
### step_download_pdf. Download Invoice PDF (`http.download`)
- **output_var:** `downloaded_file`
- **url:** https://example.com/files/invoice_102.pdf
- **target_path:** ./downloads/invoice_102.pdf
```

---

## Modular Subflows and Flow Control (`flow.*`)

Enables breaking large enterprise automations into clean, isolated, reusable child flows (subflows) located within the same project bundle or across global `@shared/` components. Adopts **Contract-First Design (`flow.return` + `output_var`)**, matching modern AI agent tool-calling paradigms.

### `flow.call`
Executes an external child flow (subflow) within an isolated context.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `flow` | string | Yes | - | Path to the child flow: `./subflows/name.md` (compiled when it runs), `@shared/name.md`, a `.json` file, or a flow name. Without an extension, `.md` is used before `.json` |
| `inputs` | dict | No | `{}` | Values passed into the subflow (evaluated in the parent). Each key should be declared in the subflow's `## Variables`; `kinenix validate` reports undeclared keys. A `config` key is merged over the subflow's config |
| `inherit_config` | boolean | No | `false` | For a shared subflow (`@shared/` or outside the bundle): pass the caller's config, merged over the subflow's own. Subflows of the bundle always get the bundle's config |
| `propagate_sessions` | boolean | No | `true` | Share the browser with the subflow. Afterwards the caller continues on the page the subflow left (a page it went to or switched to, or a browser it opened), and a browser the subflow closed is closed for the caller too. With `false`, the subflow uses its own browser, which is closed when the subflow ends |
| `outputs` | dict | No | `null` | Optional direct mapping from child variables to parent variables |

**Variable Resolution & Priority:**
1. **Subflow Defaults:** Initial variables declared in the subflow definition.
2. **Config:** the bundle's config for a subflow of the bundle; the subflow's own config for a shared one (with `inherit_config`, the caller's config merged over it).
3. **Inputs:** Values explicitly passed via `inputs` (override defaults; an `inputs` `config` is merged over the config).
4. **System Variables:** Internal paths (`__flow_dir__`, `__parent_flow__`) and shared sessions. For a subflow of the bundle, `__flow_dir__` is the bundle folder, so relative paths resolve as in the main flow; for a shared subflow it is the subflow's own folder.

**Safeguards & Protections:**
- **Max Depth:** Enforces maximum call nesting limit (default: 10 levels) to prevent memory exhaustion.
- **Circular Call Detection:** Detects and immediately blocks circular recursion (e.g. A calling B calling A).
- **Browser Safeguard:** If a subflow calls `web.close` while sharing the parent's browser, the engine intercepts the call and protects the parent's active browser session.

**Example:**
```markdown
### step_send_alert. Send Reusable LINE Alert (`flow.call`)
- **output_var:** `alert_result`
- **flow:** @shared/notify_line.json
- **inputs:** {"message": "Invoice #4891 verified successfully", "recipient": "Finance Lead", "alert_level": "SUCCESS"}
```

---

### `flow.return`
Stops subflow execution early and returns a structured payload to the caller's `output_var`.

`on_error`, `max_retries`, and `retry_interval` have no effect on this step, and `kinenix validate` reports them.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `value` | any | Yes | - | Payload (dict, list, string, number, or boolean) returned to parent flow |

**Example:**
```markdown
### step_return_payload. Return Extracted Data (`flow.return`)
- **value:** {"status": "success", "records_count": "${total_count}", "file_path": "${saved_pdf}"}
```

---

### `flow.fail`
Stops the flow on purpose with a clear message, usually behind a `condition`. Use it for business exceptions such as missing or invalid data, so the failure says what is wrong instead of a later step failing with a technical error. A `business` failure is recorded with error type `Business` and is never retried, even when the step has `max_retries`, because the same data fails the same way. A `continue`, `next_item`, or `fallback_step_id` error policy still applies; in a loop, `on_error: next_item` skips the rest of the item and goes on with the next one.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `message` | string | Yes | - | Reason recorded as the error message, in the execution log and the Hub |
| `category` | string | No | `"business"` | `"business"` (not retried) or `"technical"` |

**Example:**
```markdown
### step_check_rows. Stop When No Rates Were Found (`flow.fail`)
- **condition:** `${fx_rows} == []`
- **message:** No exchange rates were found for ${config.start_date.month} ${config.start_date.year}
```

---

## Email Notification (`email.*`)

Enables sending automated email notifications and attachments via SMTP (e.g. Gmail SMTP, Outlook 365, or local enterprise mail servers).

### `email.send`
Constructs and dispatches an email message with support for plain text, HTML body, attachments, CC, and BCC.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `to` | string / list | Yes | - | Primary recipient email address or list of addresses |
| `subject` | string | No | `"Kinenix Notification"` | Subject line of the email |
| `body` | string | No | `""` | Plain-text email message body |
| `html` | string | No | `null` | Optional rich HTML email body |
| `cc` | string / list | No | `null` | Carbon copy recipient address(es) |
| `bcc` | string / list | No | `null` | Blind carbon copy recipient address(es) |
| `attachments` | list | No | `[]` | List of file paths to attach (relative to flow or absolute) |
| `smtp_host` | string | No | `$SMTP_HOST` or `"smtp.gmail.com"` | SMTP server hostname |
| `smtp_port` | number | No | `$SMTP_PORT` or `587` | SMTP port (587 with STARTTLS) |
| `smtp_user` | string | No | see below | Sender username / email address |
| `smtp_password` | string | No | see below | Sender password or app password |
| `use_tls` | boolean | No | `true` | Establish STARTTLS secure connection |
| `dry_run` | boolean | No | `false` | When true, checks recipients and that every attachment exists, without sending |

Any SMTP provider works; the result's `channel` names the server used, for example `SMTP smtp.office365.com:587`. Keep credentials in environment variables, never in `flow.md` or `config.json`. Without `smtp_user` and `smtp_password` parameters, the action uses `SMTP_USER` and `SMTP_PASSWORD` when `SMTP_USER` is set, otherwise `GMAIL_USER` and `GMAIL_APP_PASSWORD`; the two pairs are never mixed.

| Provider | `SMTP_HOST` | `SMTP_PORT` | Notes |
|---|---|---|---|
| Gmail | `smtp.gmail.com` (default) | `587` | Needs 2-Step Verification and an app password |
| Outlook / Microsoft 365 | `smtp.office365.com` | `587` | Many organizations disable password-based SMTP; ask IT to enable SMTP AUTH for the sending mailbox |
| Company mail server | from IT | from IT | Set `use_tls` to match the server |

The message is `multipart/mixed`: the body (plain text, HTML, or both as alternatives) followed by the attachments. Tests send through a local fake SMTP server and check the recipients, headers, body parts, and attachment bytes.

**Example:**
```markdown
### step_send_report. Send Daily Processing Report (`email.send`)
- **output_var:** `email_result`
- **to:** manager@company.com
- **subject:** Daily RPA Processing Summary - [${status}]
- **body:** |
    Hello,

    The automated workflow has completed successfully.
    Processed records: ${count}
- **attachments:** ["./assets/daily_summary.xlsx"]
- **dry_run:** false
```

---

## AI and Local LLM (`ai.*`)

Integrates local LLMs powered by Ollama (or compatible HTTP endpoints like vLLM) for intelligent unstructured text understanding, zero-shot extraction, and decision making without cloud token costs.

### `ai.prompt`
Sends a prompt to an Ollama model with optional JSON schema enforcement and image inputs.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `prompt` | string | Yes | - | Prompt text or user query |
| `model` | string | No | `"qwen2.5:1.5b"` | Local LLM model tag |
| `system` | string | No | `null` | System instruction prompt |
| `format` | string | No | `null` | Set to `"json"` for structured JSON output |
| `image_path` | string | No | - | Path to one image for vision models, relative to the flow bundle |
| `temperature` | number | No | `0.1` | Sampling temperature |
| `base_url` | string | No | `"http://localhost:11434"` | Ollama service base URL |
| `timeout` | number | No | `60` | Request timeout in seconds |

**Example:**
```markdown
### step_summarize_lead. Classify Lead Intent (`ai.prompt`)
- **output_var:** `lead_analysis`
- **model:** qwen2.5:1.5b
- **prompt:** Classify whether this inquiry is urgent: '${email_body}'
- **format:** json
```

---

### `ai.extract`
Specialized action that extracts structured fields directly from raw unstructured text.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | Yes | - | Raw text, email, or OCR string to extract from |
| `schema` | dict | Yes | - | Key-description dictionary of target fields |
| `model` | string | No | `"qwen2.5:1.5b"` | Local LLM model tag |
| `base_url` | string | No | `"http://localhost:11434"` | Ollama service base URL |

**Example:**
```markdown
### step_extract_invoice. Extract Invoice Data (`ai.extract`)
- **output_var:** `invoice`
- **text:** ${ocr_text}
- **schema:** {"invoice_number": "Invoice identifier number", "total_amount": "Total due as float number", "due_date": "Due date in YYYY-MM-DD"}
```

---

### `ai.decide`
Executes rapid, zero-hallucination semantic decisions, intent classification, priority scoring, or boolean validations using **OpenThai-SystemOne** (0.8B) in a single forward pass (<50ms).

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `state` | string / dict | Yes | - | Input context, user message, or record data |
| `question` | dict | Optional | - | Single decision question definition (see below) |
| `questions` | dict | Optional | - | Multi-question dictionary |
| `base_url` | string | No | `"http://localhost:8000"` | OpenThai-SystemOne API base URL |
| `timeout` | number | No | `30` | Request timeout in seconds |
| `fallback_to_ollama` | boolean | No | `true` | Fallback to local Ollama if SystemOne server is offline |

**Question Object Properties:**
* **`type`**: `"choice"` (pick one from list), `"score"` (rate 1-5 or 1-10), or `"noul"` (yes/no).
* **`instructions`**: Guidance string describing what decision to make.
* **`options`**: List of string options (for `choice` type). Automatically converted to criteria.
* **`criteria`**: Key-value mapping of option names to descriptions (or `null`).

**Example (Intent Classification) in `flow.md` (Markdown):**
```markdown
### step_classify_inquiry. Route Customer Inquiry (`ai.decide`)
- **output_var:** `route_decision`
- **state:** ${email.body}
- **question:** {"name": "intent", "type": "choice", "instructions": "ระบุเจตนาหลักของอีเมลฉบับนี้", "options": ["ขอใบเสร็จรับเงิน", "แจ้งปัญหาการใช้งาน", "สอบถามราคา", "ยกเลิกบริการ"]}
```

**Output Format:**
```json
{
  "choice": "ขอใบเสร็จรับเงิน",
  "confidence": 0.94,
  "probabilities": {
    "ขอใบเสร็จรับเงิน": 0.94,
    "แจ้งปัญหาการใช้งาน": 0.03,
    "สอบถามราคา": 0.02,
    "ยกเลิกบริการ": 0.01
  },
  "type": "choice",
  "model": "openthai-systemone"
}
```
