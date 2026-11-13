import logging
import os
import re
import time
import subprocess  # nosec B404: runs only the fixed Playwright install command below
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from playwright.sync_api import sync_playwright, Browser, Page, Playwright

from .base import LOCATOR_PARAMETERS, BaseAction
from .registry import register_action
from ..engine.redaction import MASK, add_secret
from ..models.context import ExecutionContext

logger = logging.getLogger("kinenix")


def _launch_browser_with_auto_install(pw: Playwright, headless: bool) -> Browser:
    if not headless and sys.platform.startswith("linux"):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            logger.warning(
                "No display environment detected ($DISPLAY or $WAYLAND_DISPLAY is unset). "
                "Automatically switching Playwright browser to headless mode for headless Linux/SSH."
            )
            headless = True

    try:
        return pw.chromium.launch(headless=headless)
    except Exception as e:
        err_msg = str(e)
        if "Missing X server" in err_msg or "$DISPLAY" in err_msg:
            logger.warning(
                "Missing X server detected. Retrying Playwright launch in headless mode..."
            )
            return pw.chromium.launch(headless=True)
        if "Executable doesn't exist" in err_msg or "Please run the following command" in err_msg:
            logger.info("Playwright Chromium browser not detected. Installing Chromium automatically (first run only)...")
            res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])  # nosec B603: fixed arguments
            if res.returncode != 0:
                raise RuntimeError(
                    "Failed to auto-install Chromium. Please run in terminal: playwright install chromium"
                ) from e
            try:
                return pw.chromium.launch(headless=headless)
            except Exception as retry_err:
                retry_msg = str(retry_err)
                if "Host system is missing dependencies" in retry_msg or "libraries" in retry_msg.lower():
                    raise RuntimeError(
                        "Chromium installed, but host system is missing OS dependencies. "
                        "Please run in terminal: sudo playwright install-deps chromium"
                    ) from retry_err
                raise
        elif "Host system is missing dependencies" in err_msg:
            raise RuntimeError(
                "Host system is missing dependencies to run Chromium. "
                "Please run in terminal: sudo playwright install-deps chromium"
            ) from e
        raise


def _get_page(context: ExecutionContext) -> Page:
    page = context.get_variable("__playwright_page__")
    if not page:
        raise RuntimeError("No active browser page found. Please execute 'web.open' first.")
    return page


def _resolve_locator(page: Page, parameters: Dict[str, Any]):
    selector = parameters.get("selector")
    label = parameters.get("label")

    if label:
        return page.locator(f"//label[normalize-space()='{label}']/following::input[1]")
    elif selector:
        return page.locator(selector)
    else:
        raise ValueError("Either 'selector' or 'label' parameter is required.")


def _ensure_browser(context: ExecutionContext, headless: bool) -> Browser:
    """The run's browser, started (with Playwright) when none is open yet."""
    pw: Optional[Playwright] = context.get_variable("__playwright_pw__")
    browser: Optional[Browser] = context.get_variable("__playwright_browser__")
    if not pw:
        pw = sync_playwright().start()
        context.set_variable("__playwright_pw__", pw)
    if not browser:
        browser = _launch_browser_with_auto_install(pw, headless=headless)
        context.set_variable("__playwright_browser__", browser)
    return browser


@register_action("web.open")
class WebOpenAction(BaseAction):
    accepted_parameters = ('url', 'headless', 'timeout')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        url = parameters.get("url")
        headless = bool(parameters.get("headless", False))
        timeout = float(parameters.get("timeout", 30000))

        # A 'url' that resolves to nothing (e.g. ${config.url} with a missing config) must fail here,
        # not later on a blank page; omit 'url' entirely to open a blank page on purpose
        if "url" in parameters and not url:
            raise ValueError("web.open: 'url' is empty. Check that the variable it refers to (for example config.url) is set.")

        browser = _ensure_browser(context, headless)
        page = browser.new_page()
        page.set_default_timeout(timeout)
        context.set_variable("__playwright_page__", page)

        if url:
            page.goto(_page_url(url, context), wait_until="networkidle")

        return {"url": url, "headless": headless, "status": "opened"}


WAIT_UNTIL = ("load", "domcontentloaded", "networkidle", "commit")
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _page_url(url: Any, context: ExecutionContext) -> str:
    """
    A URL, or a page saved in the flow's folder: a path without a scheme (tests/pages/quote.html) that names a
    file in the bundle opens as a file:// URL, so a flow can be tested against saved pages on any machine (#106).
    Anything else is passed to the browser unchanged.
    """
    text = str(url).strip()
    if _URL_SCHEME.match(text) and not re.match(r"^[a-zA-Z]:[\\/]", text):
        return text
    path = Path(text)
    if not path.is_absolute():
        flow_dir = context.get_variable("__flow_dir__")
        if flow_dir:
            path = Path(flow_dir) / path
    return path.resolve().as_uri() if path.is_file() else text


@register_action("web.goto")
class WebGotoAction(BaseAction):
    """
    Goes to a URL in the current tab (#58). Unlike web.open, no new tab is opened, so a loop or a subflow
    can return to a page without piling up tabs. Opens the browser and a tab first when none is open.
    """
    accepted_parameters = ('url', 'wait_until', 'timeout', 'headless')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        url = parameters.get("url")
        if not url:
            raise ValueError("web.goto: 'url' is empty. Check that the variable it refers to (for example config.url) is set.")
        wait_until = str(parameters.get("wait_until") or "load").strip().lower()
        if wait_until not in WAIT_UNTIL:
            raise ValueError(f"web.goto: wait_until '{wait_until}' is not one of {', '.join(WAIT_UNTIL)}.")
        timeout = float(parameters.get("timeout", 30000))

        page: Optional[Page] = context.get_variable("__playwright_page__")
        if page is None or page.is_closed():
            browser = _ensure_browser(context, bool(parameters.get("headless", False)))
            page = browser.new_page()
            page.set_default_timeout(timeout)
            context.set_variable("__playwright_page__", page)

        page.goto(_page_url(url, context), wait_until=wait_until, timeout=timeout)
        return {"url": page.url, "title": page.title(), "status": "navigated"}


@register_action("web.click")
class WebClickAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('optional', 'timeout', 'wait_for_response', 'response_timeout')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        locator = _resolve_locator(page, parameters)
        timeout = float(parameters.get("timeout", 30000))
        optional = bool(parameters.get("optional", False))
        # wait_for_response: part of a URL the click is expected to request; the step ends when that
        # response arrives, so the next step sees the new data instead of relying on a fixed delay
        wait_url = parameters.get("wait_for_response")
        try:
            if not wait_url:
                locator.first.click(timeout=timeout)
                return {"action": "web.click", "status": "clicked"}

            response_timeout = float(parameters.get("response_timeout", timeout))
            with page.expect_response(lambda r: str(wait_url) in r.url, timeout=response_timeout) as response_info:
                locator.first.click(timeout=timeout)
            response = response_info.value
            return {"action": "web.click", "status": "clicked",
                    "response_url": response.url, "response_status": response.status}
        except Exception as e:
            if optional:
                logger.info(f"Optional click on '{parameters.get('selector') or parameters.get('label')}' skipped: {e}")
                return {"action": "web.click", "status": "skipped", "reason": str(e)}
            raise


@register_action("web.type")
class WebTypeAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('text', 'secret')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        locator = _resolve_locator(page, parameters)
        text = str(parameters.get("text", ""))
        locator.first.fill(text)
        # Text typed into a password field, or marked secret, is hidden in logs and Hub telemetry
        secret = str(parameters.get("secret", "")).strip().lower() in ("true", "yes", "1")
        if not secret:
            try:
                secret = (locator.first.get_attribute("type") or "").lower() == "password"
            except Exception:
                secret = False
        if secret:
            add_secret(context, text)
            return {"action": "web.type", "text": MASK, "status": "typed"}
        return {"action": "web.type", "text": text, "status": "typed"}


@register_action("web.get_text")
class WebGetTextAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        locator = _resolve_locator(page, parameters)
        text = locator.first.inner_text()
        return text


_TABLE_TO_ROWS_JS = """
table => {
    const clean = el => (el.innerText || '').replace(/\\s+/g, ' ').trim();
    const rows = Array.from(table.querySelectorAll('tr'));
    let headerCells = table.querySelectorAll('thead tr th');
    let bodyRows = Array.from(table.querySelectorAll('tbody tr'));
    if (headerCells.length === 0 && rows.length > 0) {
        headerCells = rows[0].querySelectorAll('th, td');
        bodyRows = rows.slice(1);
    } else if (bodyRows.length === 0) {
        bodyRows = rows.filter(r => r.querySelector('td'));
    }
    const headers = Array.from(headerCells).map((c, i) => clean(c) || `Column ${i + 1}`);
    const data = bodyRows
        .map(r => Array.from(r.querySelectorAll('th, td')).map(clean))
        .filter(cells => cells.some(v => v !== ''));
    return {headers, data};
}
"""


PAGING_PARAMETERS = ('next_selector', 'max_pages')
DEFAULT_MAX_PAGES = 20

_IS_DISABLED_JS = """
el => {
    const off = e => !!e && (e.disabled === true || e.getAttribute('aria-disabled') === 'true'
        || e.classList.contains('disabled') || e.classList.contains('is-disabled'));
    return off(el) || off(el.parentElement) || off(el.parentElement && el.parentElement.parentElement);
}
"""


def _next_is_available(page: Page, next_selector: str) -> bool:
    """The "next page" control exists, is visible, and is not disabled (attribute, aria, or a disabled class
    on it or on its parents, as DataTables and Bootstrap pagination do)."""
    control = page.locator(next_selector).first
    if control.count() == 0 or not control.is_visible():
        return False
    return not control.evaluate(_IS_DISABLED_JS)


ITEM_ERROR_VALUES = ("fail", "skip")


class ListRuleBusinessError(ValueError):
    """A list that breaks a rule of its step (min_rows, required_fields, a number field) with rule_error: business:
    recorded as error type Business and not retried (#146)."""


def _rule_error(parameters: Dict[str, Any], action: str) -> str:
    """`rule_error`: technical (default) or business, for the failures of min_rows, required fields, and numbers."""
    from .flow_control import error_category
    return error_category(parameters.get("rule_error"), "technical", f"{action}: rule_error")


def _broken_rule(message: str, category: str) -> ValueError:
    return ListRuleBusinessError(message) if category == "business" else ValueError(message)


def _on_item_error(parameters: Dict[str, Any], action: str) -> str:
    """`on_item_error`: fail (default) stops the step at the first item that cannot be read; skip leaves it out (#192)."""
    value = str(parameters.get("on_item_error") or "fail").strip().lower()
    if value not in ITEM_ERROR_VALUES:
        raise ValueError(f"{action}: on_item_error must be fail or skip, not '{parameters.get('on_item_error')}'.")
    return value


def _report_skipped(action: str, skipped: List[str], total: int) -> None:
    """One warning for the items left out with on_item_error: skip, with the first reasons, so none is lost silently."""
    if not skipped:
        return
    shown = "; ".join(skipped[:5]) + (f"; and {len(skipped) - 5} more" if len(skipped) > 5 else "")
    logger.warning(f"{action}: skipped {len(skipped)} of {total} item(s) (on_item_error: skip): {shown}")


def _read_pages(page: Page, parameters: Dict[str, Any], action: str,
                read: Callable[[], List[Any]], signature: Callable[[], str]) -> List[Any]:
    """
    Reads one page, then follows `next_selector` until it is gone or disabled, waiting each time until the
    content has really changed. More pages than `max_pages` is an error, never a silent cut.
    """
    rows = list(read())
    next_selector = parameters.get("next_selector")
    if not next_selector:
        return rows
    max_pages = int(parameters.get("max_pages", DEFAULT_MAX_PAGES))
    timeout = float(parameters.get("timeout", 30000))
    pages = 1
    while _next_is_available(page, next_selector):
        if pages >= max_pages:
            raise ValueError(f"{action}: there are more than max_pages ({max_pages}) pages; "
                             f"raise max_pages to read them all, so that no page is left out without notice.")
        before = signature()
        page.locator(next_selector).first.click()
        deadline = time.monotonic() + timeout / 1000
        while signature() == before:
            if time.monotonic() > deadline:
                raise TimeoutError(f"{action}: the content did not change within {timeout:.0f} ms after clicking "
                                   f"'{next_selector}' (page {pages + 1}).")
            page.wait_for_timeout(100)
        rows.extend(read())
        pages += 1
    return rows


@register_action("web.get_table")
class WebGetTableAction(BaseAction):
    """Reads an HTML <table> into a list of row dicts keyed by the header cells, following its pages when asked."""
    accepted_parameters = LOCATOR_PARAMETERS + ('columns', 'numeric_columns', 'add_columns', 'min_rows', 'timeout',
                                                'on_item_error', 'rule_error') + PAGING_PARAMETERS
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        on_item_error = _on_item_error(parameters, "web.get_table")
        rule_error = _rule_error(parameters, "web.get_table")
        locator = _resolve_locator(page, parameters).first
        timeout = float(parameters.get("timeout", 30000))
        columns = parameters.get("columns")
        add_columns = parameters.get("add_columns") or {}
        min_rows = int(parameters.get("min_rows", 0))

        locator.wait_for(state="attached", timeout=timeout)
        headers: List[str] = []

        def read_page() -> List[Dict[str, Any]]:
            table = locator.evaluate(_TABLE_TO_ROWS_JS)
            headers[:] = table["headers"]
            return [dict(zip(table["headers"], cells)) for cells in table["data"]]

        rows = _read_pages(page, parameters, "web.get_table", read_page, lambda: locator.inner_text())

        # columns: a list keeps those columns in that order; a dict also renames {source: target}
        if columns:
            mapping = columns if isinstance(columns, dict) else {name: name for name in columns}
            missing = [name for name in mapping if name not in headers]
            if missing:
                raise ValueError(f"web.get_table: column(s) {missing} not found; table headers are {headers}")
            rows = [{target: row.get(source, "") for source, target in mapping.items()} for row in rows]

        # numeric_columns: convert cell text such as "1,234.50" to numbers; blank cells become None
        numeric_columns = parameters.get("numeric_columns") or []
        if rows:
            missing = [name for name in numeric_columns if name not in rows[0]]
            if missing:
                raise ValueError(f"web.get_table: numeric column '{missing[0]}' not found; columns are {list(rows[0])}")
        kept, skipped = [], []
        for number, row in enumerate(rows, start=1):
            try:
                for name in numeric_columns:
                    text = str(row[name]).replace(",", "").strip()
                    if text in ("", "-"):
                        row[name] = None
                        continue
                    try:
                        row[name] = float(text)
                    except ValueError:
                        raise _broken_rule(f"web.get_table: row {number}: value '{row[name]}' in column "
                                           f"'{name}' is not a number", rule_error) from None
            except ValueError as e:
                if on_item_error != "skip":
                    raise
                skipped.append(str(e).replace("web.get_table: ", ""))
                continue
            kept.append(row)
        _report_skipped("web.get_table", skipped, len(rows))
        rows = kept

        if add_columns:
            if not isinstance(add_columns, dict):
                raise ValueError("web.get_table: 'add_columns' must be a mapping of column name to value.")
            rows = [{**add_columns, **row} for row in rows]

        if len(rows) < min_rows:
            raise _broken_rule(
                f"web.get_table: expected at least {min_rows} row(s) in '{parameters.get('selector')}', found {len(rows)}.",
                rule_error)
        return rows


_FIELD_ATTRIBUTE = re.compile(r"^(?P<selector>.*?)@(?P<attribute>[\w-]+)$")


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split())


@register_action("web.get_list")
class WebGetListAction(BaseAction):
    """
    Reads repeated elements, such as product cards or search results, into a list of rows (#55): one row per
    element matching `selector`, one value per field, each field found inside that element.
    """
    accepted_parameters = ('selector', 'fields', 'numeric_fields', 'required_fields', 'add_columns', 'min_rows',
                           'timeout', 'on_item_error', 'rule_error') + PAGING_PARAMETERS
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        selector = parameters.get("selector")
        if not selector:
            raise ValueError("web.get_list: 'selector' (the repeated element, such as a card) is required.")
        fields = parameters.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError('web.get_list: \'fields\' must map column names to selectors inside each element, '
                             'for example {"name": "h3", "price": ".price", "link": "a@href"}.')
        numeric = list(parameters.get("numeric_fields") or [])
        required = list(parameters.get("required_fields") or [])
        on_item_error = _on_item_error(parameters, "web.get_list")
        rule_error = _rule_error(parameters, "web.get_list")
        unknown = [name for name in numeric + required if name not in fields]
        if unknown:
            raise ValueError(f"web.get_list: {unknown} are not in fields ({', '.join(fields)}).")
        add_columns = parameters.get("add_columns") or {}
        if not isinstance(add_columns, dict):
            raise ValueError("web.get_list: 'add_columns' must be a mapping of column name to value.")
        min_rows = int(parameters.get("min_rows", 0))
        timeout = float(parameters.get("timeout", 30000))

        items = page.locator(selector)
        try:
            items.first.wait_for(state="attached", timeout=timeout)
        except Exception:
            if min_rows > 0:
                raise _broken_rule(f"web.get_list: no element matches '{selector}' within {timeout:.0f} ms.", rule_error)

        def read_field(item, spec: str) -> str:
            match = _FIELD_ATTRIBUTE.match(spec or "")
            inner, attribute = (match.group("selector").strip(), match.group("attribute")) if match else ((spec or "").strip(), None)
            target = item if inner in ("", ".") else item.locator(inner).first
            if target is not item and target.count() == 0:
                return ""
            if attribute:
                return _clean(target.get_attribute(attribute))
            return _clean(target.inner_text())

        def read_page() -> List[Dict[str, Any]]:
            rows = []
            for index in range(items.count()):
                item = items.nth(index)
                rows.append({name: read_field(item, spec) for name, spec in fields.items()})
            return rows

        rows = _read_pages(page, parameters, "web.get_list", read_page, lambda: "\n".join(items.all_inner_texts()))

        from ..engine.expressions import parse_number
        kept, skipped = [], []
        for number, row in enumerate(rows, start=1):
            try:
                for name in required:
                    if row[name] == "":
                        raise _broken_rule(f"web.get_list: item {number} has no '{name}' (selector "
                                           f"'{fields[name]}'); the item reads {row}.", rule_error)
                # Blank and "-" become None, as in web.get_table; text with no number in it is an error
                for name in numeric:
                    try:
                        row[name] = parse_number(row[name]) if row[name] not in ("", "-") else None
                    except ValueError as e:
                        raise _broken_rule(f"web.get_list: item {number}, field '{name}': {e}", rule_error) from None
            except ValueError as e:
                if on_item_error != "skip":
                    raise
                # The reason without the item's whole content, which may hold personal data
                skipped.append(str(e).replace("web.get_list: ", "").split("; the item reads")[0])
                continue
            kept.append(row)
        _report_skipped("web.get_list", skipped, len(rows))
        rows = kept
        if add_columns:
            rows = [{**add_columns, **row} for row in rows]
        if len(rows) < min_rows:
            raise _broken_rule(f"web.get_list: expected at least {min_rows} item(s) matching '{selector}', "
                               f"found {len(rows)}.", rule_error)
        return rows


_CHOOSE_SEARCH_INPUTS = "[cmdk-input], input[role=combobox], [role=combobox] input, input[type=search], [role=dialog] input, [role=listbox] input"
# Options of the open dropdown, not the <option> elements of native selects elsewhere on the page
_OUTSIDE_NATIVE_SELECT = "xpath=//*[not(ancestor::select)]"


CHOOSE_MATCH = ("exact", "contains", "loose")
_LOOSE_IGNORED = re.compile(r"[\s\-_.,/:()]+")


def _loose(text: str) -> str:
    """HR-V, hr v, and HRV compare equal: spaces, hyphens, dots, and similar marks and case are ignored."""
    return _LOOSE_IGNORED.sub("", text).casefold()


def _choose_label(labels: List[str], option: str, match: str) -> Optional[str]:
    """
    The option to pick among the labels shown, or None. An exact name always wins. loose: the one label equal
    to the option apart from spaces, marks, and case; several such labels are an error, never a guess (#107).
    contains: the first label containing the option, ignoring case.
    """
    if option in labels:
        return option
    if match == "contains":
        return next((label for label in labels if option.lower() in label.lower()), None)
    if match == "loose":
        found = list(dict.fromkeys(label for label in labels if _loose(label) == _loose(option)))
        if len(found) > 1:
            raise ValueError(f"web.choose: option '{option}' matches several options loosely: {', '.join(found)}; "
                             f"give the exact name.")
        return found[0] if found else None
    return None


@register_action("web.choose")
class WebChooseAction(BaseAction):
    """
    Picks an option in a dropdown (#57): a custom one (Radix/shadcn Select, cmdk combobox, Headless UI, MUI),
    by clicking the trigger, optionally typing into its search box, and clicking the option with that name;
    or a native <select>. When the option is missing, the error lists the options that are there.
    match: exact (default), contains, or loose (#107); exact: false is the older spelling of contains.
    """
    accepted_parameters = LOCATOR_PARAMETERS + ('option', 'match', 'search', 'search_text', 'search_selector',
                                                'exact', 'timeout')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        option = parameters.get("option")
        if option is None or str(option).strip() == "":
            raise ValueError("web.choose: 'option' is empty. Check the value or the variable it refers to.")
        option = _clean(str(option))
        match = str(parameters.get("match") or "").strip().lower()
        if not match:
            exact = str(parameters.get("exact", True)).strip().lower() not in ("false", "0", "no")
            match = "exact" if exact else "contains"
        if match not in CHOOSE_MATCH:
            raise ValueError(f"web.choose: match '{match}' is not one of {', '.join(CHOOSE_MATCH)}.")
        search = str(parameters.get("search", False)).strip().lower() in ("true", "1", "yes")
        timeout = float(parameters.get("timeout", 10000))

        trigger = _resolve_locator(page, parameters).first
        trigger.wait_for(state="visible", timeout=timeout)

        if trigger.evaluate("el => el.tagName.toLowerCase()") == "select":
            labels = [_clean(t) for t in trigger.locator("option").all_inner_texts()]
            chosen = _choose_label(labels, option, match)
            if chosen is None:
                raise ValueError(f"web.choose: option '{option}' not found; available: {', '.join(labels[:30])}")
            trigger.select_option(label=chosen)
            return {"option": chosen, "status": "chosen"}

        trigger.click()
        if search:
            box_selector = parameters.get("search_selector")
            box = page.locator(box_selector).first if box_selector else page.locator(_CHOOSE_SEARCH_INPUTS).first
            box.wait_for(state="visible", timeout=timeout)
            box.fill(str(parameters.get("search_text") or option))

        # Options of the open list (not of native selects elsewhere on the page), read until the one wanted
        # shows up: lists that load or filter as you type fill in over a moment
        options = page.get_by_role("option").and_(page.locator(_OUTSIDE_NATIVE_SELECT))
        deadline = time.monotonic() + timeout / 1000
        labels: List[str] = []
        while True:
            labels = [label for label in (_clean(t) for t in options.all_inner_texts()) if label]
            chosen = _choose_label(labels, option, match)
            if chosen is not None or time.monotonic() > deadline:
                break
            page.wait_for_timeout(100)
        if chosen is None:
            if not labels and search:
                typed = str(parameters.get("search_text") or option)
                raise ValueError(f"web.choose: the search box shows no options for '{typed}'. The site filters by "
                                 f"what is typed: set search_text to the start of the name as the site writes it "
                                 f"(for example its first two letters), and keep match: loose to pick it.")
            if not labels:
                raise ValueError("web.choose: no options appeared after clicking the dropdown; check the selector "
                                 "of the trigger, or set search: true if the list needs typing first.")
            raise ValueError(f"web.choose: option '{option}' not found; available: {', '.join(labels[:30])}")
        page.get_by_role("option", name=chosen, exact=True).and_(page.locator(_OUTSIDE_NATIVE_SELECT)).first.click()
        return {"option": chosen, "status": "chosen"}


@register_action("web.screenshot")
class WebScreenshotAction(BaseAction):
    accepted_parameters = ('path', 'full_page')
    side_effects = ('files',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        path_str = parameters.get("path", "screenshot.png")
        full_page = bool(parameters.get("full_page", False))

        target_path = Path(path_str)
        if not target_path.is_absolute():
            flow_dir_str = context.get_variable("__flow_dir__")
            if flow_dir_str:
                target_path = Path(flow_dir_str) / path_str

        target_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target_path), full_page=full_page)
        return {"screenshot_path": str(target_path)}


@register_action("web.download")
class WebDownloadAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('target_path', 'timeout')
    side_effects = ('web', 'files')

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        selector = parameters.get("selector")
        target_path_str = parameters.get("target_path", "downloads/downloaded_file")
        timeout = float(parameters.get("timeout", 30000))

        target_path = Path(target_path_str)
        if not target_path.is_absolute():
            flow_dir_str = context.get_variable("__flow_dir__")
            if flow_dir_str:
                target_path = Path(flow_dir_str) / target_path_str

        target_path.parent.mkdir(parents=True, exist_ok=True)

        if not selector:
            raise ValueError("Parameter 'selector' is required for action 'web.download'.")

        locator = _resolve_locator(page, parameters).first

        # Check if the element has an href attribute to download directly via browser session
        href = locator.get_attribute("href")
        if href:
            # Resolve relative URL against current page URL
            from urllib.parse import urljoin
            full_url = urljoin(page.url, href)
            response = page.context.request.get(full_url, timeout=timeout)
            if response.status >= 400:
                raise RuntimeError(f"Failed to download from '{full_url}', HTTP status {response.status}")
            target_path.write_bytes(response.body())
        else:
            # If it's a button or trigger that initiates a browser download event
            with page.expect_download(timeout=timeout) as download_info:
                locator.click()
            download = download_info.value
            download.save_as(str(target_path))

        file_size = target_path.stat().st_size
        return {
            "status": "downloaded",
            "file_path": str(target_path),
            "file_size": file_size
        }


@register_action("web.close")
class WebCloseAction(BaseAction):
    accepted_parameters = ()
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        if context.get_variable("__shared_browser__"):
            logger.warning(
                "Safeguard: 'web.close' was invoked inside a subflow sharing parent browser session. "
                "Skipping browser closure to protect parent workflow."
            )
            return {"status": "skipped", "reason": "protected_shared_browser"}

        browser: Optional[Browser] = context.get_variable("__playwright_browser__")
        pw: Optional[Playwright] = context.get_variable("__playwright_pw__")

        if browser:
            browser.close()
            context.set_variable("__playwright_browser__", None)
            context.set_variable("__playwright_page__", None)

        if pw:
            pw.stop()
            context.set_variable("__playwright_pw__", None)

        return {"status": "closed"}


@register_action("web.wait_for")
class WebWaitForAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('state', 'timeout')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        selector = parameters.get("selector")
        label = parameters.get("label")
        state = parameters.get("state", "visible")
        timeout = float(parameters.get("timeout", 30000))

        if selector or label:
            locator = _resolve_locator(page, parameters)
            locator.first.wait_for(state=state, timeout=timeout)
            return {"action": "web.wait_for", "state": state, "status": "ready"}
        else:
            page.wait_for_timeout(timeout)
            return {"action": "web.wait_for", "timeout_ms": timeout, "status": "waited"}


@register_action("web.is_visible")
class WebIsVisibleAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('timeout',)
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        locator = _resolve_locator(page, parameters)
        timeout = float(parameters.get("timeout", 2000))
        try:
            if timeout <= 0:
                return locator.first.is_visible()
            locator.first.wait_for(state="visible", timeout=timeout)
            return True
        except Exception:
            return False


@register_action("web.get_attribute")
class WebGetAttributeAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('attribute', 'name')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        attr_name = parameters.get("attribute") or parameters.get("name")
        if not attr_name:
            raise ValueError("Parameter 'attribute' is required for action 'web.get_attribute'.")

        locator = _resolve_locator(page, parameters)
        val = locator.first.get_attribute(attr_name)
        return val


@register_action("web.press")
class WebPressAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('key',)
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        key = parameters.get("key")
        if not key:
            raise ValueError("Parameter 'key' is required for action 'web.press'.")

        selector = parameters.get("selector")
        label = parameters.get("label")

        if selector or label:
            locator = _resolve_locator(page, parameters)
            locator.first.press(key)
        else:
            page.keyboard.press(key)

        return {"action": "web.press", "key": key, "status": "pressed"}


@register_action("web.scroll")
class WebScrollAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('direction', 'amount')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        selector = parameters.get("selector")
        label = parameters.get("label")

        if selector or label:
            locator = _resolve_locator(page, parameters)
            locator.first.scroll_into_view_if_needed()
            return {"action": "web.scroll", "target": "element", "status": "scrolled"}

        direction = str(parameters.get("direction", "down")).lower()
        amount = int(parameters.get("amount", 500))

        if direction == "bottom":
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "top":
            page.evaluate("window.scrollTo(0, 0)")
        elif direction == "up":
            page.evaluate(f"window.scrollBy(0, -{amount})")
        else:  # down
            page.evaluate(f"window.scrollBy(0, {amount})")

        return {"action": "web.scroll", "direction": direction, "amount": amount, "status": "scrolled"}


@register_action("web.hover")
class WebHoverAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('timeout',)
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        timeout = float(parameters.get("timeout", 30000))
        locator = _resolve_locator(page, parameters)
        locator.first.hover(timeout=timeout)
        return {"action": "web.hover", "status": "hovered"}


@register_action("web.switch_tab")
class WebSwitchTabAction(BaseAction):
    accepted_parameters = ('index', 'title', 'url_pattern')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        browser: Optional[Browser] = context.get_variable("__playwright_browser__")
        if not browser or not browser.contexts:
            raise RuntimeError("No active browser context found. Cannot switch tab.")

        browser_context = browser.contexts[0]
        pages = browser_context.pages
        if not pages:
            raise RuntimeError("No open tabs/pages found in browser.")

        target_page = None
        index = parameters.get("index")
        url_pattern = parameters.get("url_pattern")
        title = parameters.get("title")

        if index is not None:
            idx = int(index)
            if 0 <= idx < len(pages) or -len(pages) <= idx < 0:
                target_page = pages[idx]
            else:
                raise IndexError(f"Tab index {idx} out of range (total open tabs: {len(pages)}).")
        elif url_pattern:
            for p in pages:
                if url_pattern in p.url:
                    target_page = p
                    break
            if not target_page:
                raise ValueError(f"No tab found matching url_pattern: '{url_pattern}'.")
        elif title:
            for p in pages:
                if title.lower() in p.title().lower():
                    target_page = p
                    break
            if not target_page:
                raise ValueError(f"No tab found matching title: '{title}'.")
        else:
            target_page = pages[-1]

        target_page.bring_to_front()
        context.set_variable("__playwright_page__", target_page)
        return {
            "action": "web.switch_tab",
            "title": target_page.title(),
            "url": target_page.url,
            "status": "switched"
        }


@register_action("web.select_option")
class WebSelectOptionAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('value', 'text', 'label_text', 'index', 'ai_match', 'base_url', 'systemone_url', 'fallback_to_ollama', 'timeout')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        locator = _resolve_locator(page, parameters)

        val = parameters.get("value")
        text = parameters.get("label_text") or parameters.get("text")
        index = parameters.get("index")
        ai_match = bool(parameters.get("ai_match", False))

        if ai_match:
            from .ai_systemone import call_systemone_api

            target_query = str(text if text is not None else (val if val is not None else "")).strip()
            if not target_query:
                raise ValueError("Parameter 'text' or 'value' is required when 'ai_match' is enabled.")

            # Extract options from DOM via Playwright evaluate
            dom_options = locator.first.evaluate("""
                el => {
                    if (!el || !el.options) return [];
                    return Array.from(el.options).map(o => ({
                        value: o.value,
                        text: (o.text || '').trim()
                    }));
                }
            """)

            if not dom_options:
                raise RuntimeError("No <option> elements found in the target select element.")

            # Fast-path: Check exact match first
            exact_match = None
            for opt in dom_options:
                opt_text = opt.get("text", "")
                opt_val = opt.get("value", "")
                if target_query.lower() in (opt_text.lower(), opt_val.lower()):
                    exact_match = opt
                    break

            if exact_match:
                selected = locator.first.select_option(value=exact_match["value"])
                return {
                    "action": "web.select_option",
                    "selected": selected,
                    "matched_text": exact_match["text"],
                    "ai_match": True,
                    "confidence": 1.0,
                    "match_type": "exact",
                    "status": "selected"
                }

            # AI Semantic Matching using OpenThai-SystemOne
            base_url = str(parameters.get("systemone_url") or parameters.get("base_url") or "http://localhost:8000")
            criteria = {opt["text"]: None for opt in dom_options if opt.get("text")}

            sys_resp = call_systemone_api(
                state=target_query,
                questions={
                    "selected_option": {
                        "type": "choice",
                        "instructions": "เลือกตัวเลือกจากรายการที่ตรงกับความหมายของข้อความที่ระบุมากที่สุด",
                        "criteria": criteria
                    }
                },
                base_url=base_url,
                timeout=float(parameters.get("timeout", 30.0)),
                fallback_to_ollama=bool(parameters.get("fallback_to_ollama", True))
            )

            matched_label = sys_resp.get("answers", {}).get("selected_option", {}).get("choice")
            confidence = sys_resp.get("answers", {}).get("selected_option", {}).get("confidence")

            if not matched_label:
                raise RuntimeError(
                    f"AI semantic matching failed to resolve option for '{target_query}'."
                )

            # Match to value or label
            matched_opt = next((o for o in dom_options if o.get("text") == matched_label), None)
            if matched_opt and matched_opt.get("value"):
                selected = locator.first.select_option(value=matched_opt["value"])
            else:
                selected = locator.first.select_option(label=matched_label)

            return {
                "action": "web.select_option",
                "selected": selected,
                "matched_text": matched_label,
                "confidence": confidence,
                "ai_match": True,
                "match_type": "semantic",
                "status": "selected"
            }

        if val is not None:
            selected = locator.first.select_option(value=str(val))
        elif text is not None:
            selected = locator.first.select_option(label=str(text))
        elif index is not None:
            selected = locator.first.select_option(index=int(index))
        else:
            raise ValueError("One of 'value', 'text', or 'index' is required for action 'web.select_option'.")

        return {"action": "web.select_option", "selected": selected, "status": "selected"}


@register_action("web.upload_file")
class WebUploadFileAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('file_path', 'path')
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        file_path_str = parameters.get("file_path") or parameters.get("path")
        if not file_path_str:
            raise ValueError("Parameter 'file_path' is required for action 'web.upload_file'.")

        target_path = Path(file_path_str)
        if not target_path.is_absolute():
            flow_dir_str = context.get_variable("__flow_dir__")
            if flow_dir_str:
                target_path = Path(flow_dir_str) / file_path_str

        if not target_path.exists():
            raise FileNotFoundError(f"File to upload not found: {target_path}")

        locator = _resolve_locator(page, parameters)
        locator.first.set_input_files(str(target_path.resolve()))

        return {
            "action": "web.upload_file",
            "file_path": str(target_path.resolve()),
            "status": "uploaded"
        }


@register_action("web.check")
class WebCheckAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('timeout',)
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        timeout = float(parameters.get("timeout", 30000))
        locator = _resolve_locator(page, parameters)
        locator.first.check(timeout=timeout)
        return {"action": "web.check", "status": "checked"}


@register_action("web.uncheck")
class WebUncheckAction(BaseAction):
    accepted_parameters = LOCATOR_PARAMETERS + ('timeout',)
    side_effects = ('web',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        page = _get_page(context)
        timeout = float(parameters.get("timeout", 30000))
        locator = _resolve_locator(page, parameters)
        locator.first.uncheck(timeout=timeout)
        return {"action": "web.uncheck", "status": "unchecked"}

