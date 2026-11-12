"""0.4.0b1: web.choose, web.get_list, and paged web.get_table in a real browser, against local pages."""
import pytest

from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import markdown_to_flow

# A Radix/shadcn-style Select: a button opens a listbox of role=option items (and a hidden native select that
# must not be used), and a cmdk-style combobox: a button opens a search box that filters the options.
DROPDOWNS = """<!doctype html><html><body>
<button id="brand" data-testid="carBrand" aria-haspopup="listbox">Choose brand</button>
<select aria-hidden="true" tabindex="-1" style="position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0,0,0,0)"><option>HONDA</option></select>
<div id="brand-list" role="listbox" hidden>
  <div role="option">HONDA</div><div role="option">HONDA BIGWING</div><div role="option">HYUNDAI</div><div role="option">ISUZU</div>
</div>
<button id="model">Choose model</button>
<div id="model-pop" hidden><input cmdk-input placeholder="Search"><div id="model-list" role="listbox"></div></div>
<select id="native"><option>Bangkok</option><option>Chiang Mai</option><option>Phuket</option></select>
<p>Brand: <span id="brand-value"></span> Model: <span id="model-value"></span></p>
<script>
  const brand = document.getElementById('brand'), list = document.getElementById('brand-list');
  brand.onclick = () => { setTimeout(() => list.hidden = false, 150); };
  list.querySelectorAll('[role=option]').forEach(o => o.onclick = () => {
    document.getElementById('brand-value').textContent = o.textContent; brand.textContent = o.textContent; list.hidden = true; });
  const models = ['HR-V', 'CITY', 'CIVIC', 'ACCORD'];
  const pop = document.getElementById('model-pop'), input = pop.querySelector('input'), mlist = document.getElementById('model-list');
  const render = q => { mlist.innerHTML = ''; models.filter(m => m.toLowerCase().includes(q.toLowerCase())).forEach(m => {
      const d = document.createElement('div'); d.setAttribute('role', 'option'); d.textContent = m;
      d.onclick = () => { document.getElementById('model-value').textContent = m; pop.hidden = true; }; mlist.appendChild(d); }); };
  document.getElementById('model').onclick = () => { pop.hidden = false; input.value = ''; render(''); input.focus(); };
  input.oninput = () => render(input.value);
</script></body></html>"""

CARDS = """<!doctype html><html><body>
<div class="card"><h3>Package A</h3><span class="price">15,434.75 บาท/ปี</span><a href="/a">Details</a><div class="tag">Popular</div></div>
<div class="card"><h3>Package B</h3><span class="price">8,200 บาท/ปี</span><a href="/b">Details</a></div>
<div class="card"><h3>Package C</h3><span class="price">-</span><a href="/c">Details</a></div>
</body></html>"""

# DataTables-like paging: 7 rows, 3 per page, the "Next" link becomes disabled on the last page
PAGED = """<!doctype html><html><body>
<table id="t"><thead><tr><th>ID</th><th>Due Date</th></tr></thead><tbody></tbody></table>
<ul class="pagination"><li id="next-li"><a id="next" class="paginate_button next" href="#">Next</a></li></ul>
<div id="cards"></div>
<button id="more">More</button>
<script>
  const rows = [['1','25-10-2026'],['2','03-11-2026'],['3','12-12-2026'],['4','01-10-2026'],['5','15-11-2026'],['6','20-01-2027'],['7','30-10-2026']];
  let page = 0;
  const show = () => {
    document.querySelector('#t tbody').innerHTML = rows.slice(page*3, page*3+3).map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('');
    document.getElementById('cards').innerHTML = rows.slice(page*3, page*3+3).map(r => `<div class="item"><b>${r[0]}</b></div>`).join('');
    const last = page*3+3 >= rows.length;
    document.getElementById('next').classList.toggle('disabled', last);
    document.getElementById('more').disabled = last;
  };
  const next = e => { if (e) e.preventDefault(); if (page*3+3 < rows.length) { setTimeout(() => { page++; show(); }, 120); } };
  document.getElementById('next').onclick = next;
  document.getElementById('more').onclick = () => next();
  show();
</script></body></html>"""


@pytest.fixture
def pages(tmp_path, chromium):
    urls = {}
    for name, html in (("dropdowns", DROPDOWNS), ("cards", CARDS), ("paged", PAGED)):
        path = tmp_path / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        urls[name] = path.as_uri()
    return urls


def _run(steps, url, config=None):
    flow = f"# Web\n\n## Steps\n\n### 1. Open (`web.open`)\n- **url:** {url}\n- **headless:** true\n\n{steps}"
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(
        markdown_to_flow(flow), initial_vars={"config": config or {}})
    return context


def _ok(context):
    assert not context.has_error, context.failure_details and context.failure_details.error_message
    return context


def test_choose_in_a_custom_select_and_a_search_combobox(pages):
    context = _ok(_run("""### 2. Brand (`web.choose`)
- **selector:** `[data-testid=carBrand]`
- **option:** ${config.brand}
- **output_var:** `brand`

### 3. Model (`web.choose`)
- **selector:** `#model`
- **option:** hr-v
- **search:** true
- **exact:** false

### 4. Read (`web.get_text`)
- **selector:** p
- **output_var:** `shown`
""", pages["dropdowns"], {"brand": "HONDA"}))
    assert context.get_variable("brand") == {"option": "HONDA", "status": "chosen"}  # not HONDA BIGWING
    assert context.get_variable("shown") == "Brand: HONDA Model: HR-V"


def test_choose_in_a_native_select(pages):
    context = _ok(_run("""### 2. City (`web.choose`)
- **selector:** `#native`
- **option:** chiang
- **exact:** false
- **output_var:** `chosen`
""", pages["dropdowns"]))
    assert context.get_variable("chosen") == {"option": "Chiang Mai", "status": "chosen"}
    page = context.get_variable("__playwright_page__")
    assert page is None or page.is_closed() or page.locator("#native").input_value() == "Chiang Mai"


@pytest.mark.parametrize("steps, message", [
    ("- **selector:** `[data-testid=carBrand]`\n- **option:** HONDAX\n- **timeout:** 1500",
     "option 'HONDAX' not found; available: HONDA, HONDA BIGWING, HYUNDAI, ISUZU"),
    ("- **selector:** `#native`\n- **option:** Hat Yai", "option 'Hat Yai' not found; available: Bangkok, Chiang Mai, Phuket"),
    # exact by default: "HR" is not "HR-V"
    ("- **selector:** `#model`\n- **option:** HR\n- **timeout:** 1500",
     "option 'HR' not found; available: HR-V, CITY, CIVIC, ACCORD"),
    ("- **selector:** p\n- **option:** HONDA\n- **timeout:** 1500", "no options appeared after clicking"),
    ("- **selector:** `[data-testid=carBrand]`\n- **option:** ${config.missing}", "'option' is empty"),
])
def test_choose_says_what_is_there_when_the_option_is_missing(pages, steps, message):
    context = _run(f"### 2. Choose (`web.choose`)\n{steps}\n", pages["dropdowns"])
    assert context.has_error
    error = context.failure_details.error_message
    # the list of what is there ends the message: options of other dropdowns on the page are not in it
    assert error.endswith(message) if "available" in message else message in error


def test_get_list_reads_cards(pages):
    context = _ok(_run("""### 2. Packages (`web.get_list`)
- **selector:** `.card`
- **fields:** {"name": "h3", "price": ".price", "link": "a@href", "tag": ".tag", "text": "."}
- **numeric_fields:** ["price"]
- **required_fields:** ["name"]
- **add_columns:** {"request_id": "R001"}
- **min_rows:** 2
- **output_var:** `packages`
""", pages["cards"]))
    packages = context.get_variable("packages")
    assert [p["name"] for p in packages] == ["Package A", "Package B", "Package C"]
    assert [p["price"] for p in packages] == [15434.75, 8200, None]
    assert packages[0]["link"] == "/a" and packages[0]["tag"] == "Popular" and packages[1]["tag"] == ""
    assert packages[0]["request_id"] == "R001" and packages[0]["text"].startswith("Package A")


@pytest.mark.parametrize("extra, message", [
    ('- **fields:** {"name": "h3", "tag": ".tag"}\n- **required_fields:** ["tag"]', "item 2 has no 'tag'"),
    ('- **fields:** {"name": "h3"}\n- **min_rows:** 5', "expected at least 5 item(s)"),
    ('- **fields:** {"name": "h3"}\n- **numeric_fields:** ["price"]', "['price'] are not in fields"),
    ('- **fields:** {"name": "h3"}\n- **numeric_fields:** ["name"]', "contains no number"),
    ('- **fields:** h3', "'fields' must map column names"),
])
def test_get_list_errors(pages, extra, message):
    context = _run(f"### 2. Packages (`web.get_list`)\n- **selector:** `.card`\n{extra}\n", pages["cards"])
    assert context.has_error and message in context.failure_details.error_message


def test_get_table_reads_every_page(pages):
    context = _ok(_run("""### 2. Invoices (`web.get_table`)
- **selector:** `#t`
- **next_selector:** `#next`
- **output_var:** `invoices`

### 3. Due In October Or November (`logic.loop`)
- **items:** `${invoices}`
- **item_var:** `inv`
- **Sub-steps:**
  - Keep (`logic.append`):
    - **condition:** `${inv.Due Date} contains -10- or ${inv.Due Date} contains -11-`
    - **target:** `due`
    - **item:** `${inv.ID}`
""", pages["paged"]))
    assert [r["ID"] for r in context.get_variable("invoices")] == ["1", "2", "3", "4", "5", "6", "7"]
    assert context.get_variable("due") == ["1", "2", "4", "5", "7"]


def test_get_list_reads_every_page_with_a_disabled_button(pages):
    context = _ok(_run("""### 2. Items (`web.get_list`)
- **selector:** `.item`
- **fields:** {"id": "b"}
- **next_selector:** `#more`
- **output_var:** `items`
""", pages["paged"]))
    assert [r["id"] for r in context.get_variable("items")] == ["1", "2", "3", "4", "5", "6", "7"]


def test_more_pages_than_max_pages_is_an_error(pages):
    context = _run("""### 2. Invoices (`web.get_table`)
- **selector:** `#t`
- **next_selector:** `#next`
- **max_pages:** 2
""", pages["paged"])
    assert context.has_error and "more than max_pages (2) pages" in context.failure_details.error_message


def test_loose_match_ignores_spaces_marks_and_case(pages):
    # #107: people write HRV, hr-v, or HR V; the site says HR-V
    context = _ok(_run("""### 2. Brand (`web.choose`)
- **selector:** `[data-testid=carBrand]`
- **option:** honda
- **match:** loose
- **output_var:** `brand`

### 3. Model (`web.choose`)
- **selector:** `#model`
- **option:** ${config.model}
- **match:** loose
- **search:** true
- **search_text:** hr
- **output_var:** `model`

### 4. City (`web.choose`)
- **selector:** `#native`
- **option:** chiangmai
- **match:** loose
""", pages["dropdowns"], {"model": "HRV"}))
    assert context.get_variable("brand")["option"] == "HONDA"  # not HONDA BIGWING
    assert context.get_variable("model")["option"] == "HR-V"


@pytest.mark.parametrize("steps, message", [
    ("- **selector:** `#model`\n- **option:** HRV\n- **match:** loose\n- **search:** true\n- **timeout:** 1500",
     "the search box shows no options for 'HRV'"),  # the site's own filter hides HR-V when HRV is typed
    ("- **selector:** `[data-testid=carBrand]`\n- **option:** HONDA\n- **match:** fuzzy", "match 'fuzzy' is not one of"),
])
def test_loose_match_problems(pages, steps, message):
    context = _run(f"### 2. Choose (`web.choose`)\n{steps}\n", pages["dropdowns"])
    assert context.has_error and message in context.failure_details.error_message


def test_several_loose_matches_are_an_error_not_a_guess():
    from kinenix.actions.web_playwright import _choose_label
    with pytest.raises(ValueError, match="matches several options loosely: HR-V, H.R.V; give the exact name"):
        _choose_label(["HR-V", "H.R.V", "CITY"], "hrv", "loose")
    assert _choose_label(["HR-V", "H.R.V"], "HR-V", "loose") == "HR-V"  # an exact name wins
    assert _choose_label(["CITY", "CITY HATCHBACK"], "city", "loose") == "CITY"
    assert _choose_label(["CITY HATCHBACK"], "hatch", "contains") == "CITY HATCHBACK"


# on_item_error (#192) ------------------------------------------------------------------------------------

MESSY = """<!doctype html><html><body>
<table id="t"><thead><tr><th>Title</th><th>Price</th></tr></thead><tbody>
<tr><td>A</td><td>51.77</td></tr><tr><td>B</td><td>N/A</td></tr><tr><td>C</td><td>-</td></tr></tbody></table>
<article class="book"><h3>A Light in the Attic</h3><p class="price">£51.77</p></article>
<article class="book"><h3></h3><p class="price">£53.74</p></article>
<article class="book"><h3>Soumission</h3><p class="price">N/A</p></article>
<article class="book"><h3>Sharp Objects</h3><p class="price">£47.82</p></article>
</body></html>"""


@pytest.fixture
def messy(tmp_path, chromium):
    path = tmp_path / "messy.html"
    path.write_text(MESSY, encoding="utf-8")
    return path.as_uri()


BOOKS_STEP = """### 2. Books (`web.get_list`)
- **selector:** `article.book`
- **fields:** {"title": "h3", "price": ".price"}
- **required_fields:** ["title"]
- **numeric_fields:** ["price"]
- **output_var:** `books`
"""


def test_get_list_skips_items_that_cannot_be_read_and_says_so(messy, caplog):
    context = _ok(_run(BOOKS_STEP + "- **on_item_error:** skip\n", messy))
    assert [b["title"] for b in context.get_variable("books")] == ["A Light in the Attic", "Sharp Objects"]
    assert [b["price"] for b in context.get_variable("books")] == [51.77, 47.82]
    warning = next(r.getMessage() for r in caplog.records if "skipped 2 of 4 item(s)" in r.getMessage())
    assert "item 2 has no 'title'" in warning and "item 3, field 'price'" in warning
    assert "£53.74" not in warning  # the reason, not the item's content


def test_get_list_still_fails_by_default(messy):
    context = _run(BOOKS_STEP, messy)
    assert context.has_error and "item 2 has no 'title'" in context.failure_details.error_message


def test_min_rows_counts_the_items_that_are_kept(messy):
    context = _run(BOOKS_STEP + "- **on_item_error:** skip\n- **min_rows:** 3\n", messy)
    assert context.has_error and "expected at least 3 item(s)" in context.failure_details.error_message


def test_get_table_skips_rows_with_a_number_that_cannot_be_read(messy, caplog):
    context = _ok(_run("""### 2. Prices (`web.get_table`)
- **selector:** `#t`
- **numeric_columns:** ["Price"]
- **on_item_error:** skip
- **output_var:** `rows`
""", messy))
    assert context.get_variable("rows") == [{"Title": "A", "Price": 51.77}, {"Title": "C", "Price": None}]
    assert any("skipped 1 of 3 item(s)" in r.getMessage() and "row 2" in r.getMessage() for r in caplog.records)


def test_a_wrong_on_item_error_value_says_which_values_work(messy):
    context = _run(BOOKS_STEP + "- **on_item_error:** ignore\n", messy)
    assert context.has_error and "on_item_error must be fail or skip" in context.failure_details.error_message
