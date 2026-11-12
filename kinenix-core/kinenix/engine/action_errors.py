"""Plain-language causes for the error messages Kinenix actions raise themselves (#219).

web_errors.py reads Playwright's messages; this module reads the fixed messages of Kinenix's own actions, such
as web.choose when the option is not on the page, so that root_cause names the value and the step and
suggested_fix says what to change. The facts come from the message, written when the step failed; nothing is
guessed, and the full message stays in error_message. explain() returns None for any other message, and the
caller keeps its own wording.
"""
import re
from typing import Callable, List, Optional, Pattern, Tuple

from .web_errors import Explanation

_HTTP_CAUSES = {
    400: "the request was not accepted (HTTP 400): a parameter or the payload is not what the service expects",
    401: "the service asked for a login (HTTP 401): the key or password is missing or wrong",
    403: "the service refused access (HTTP 403): the account has no permission, or the key is wrong",
    404: "the address was not found (HTTP 404): the URL is wrong, or the record it points to does not exist",
    408: "the service gave up waiting for the request (HTTP 408)",
    409: "the request conflicts with the current state (HTTP 409), for example a record that already exists",
    422: "the service could not use the data sent (HTTP 422): a field is missing or has the wrong form",
    429: "too many requests (HTTP 429): the service limits how often it may be called",
}
_HTTP_FIXES = {
    401: "Check the key or password the request sends; read it from an environment variable, never from flow.md.",
    403: "Check the account's permissions and the key the request sends.",
    404: "Check the URL and the values put into it (an id from the input data, a config value).",
    429: "Call less often: add a logic.delay between requests, or retry later (max_retries with retry_interval).",
}


def _choose_not_found(m: re.Match, step: str) -> Explanation:
    option, available = m.group(1), m.group(2).strip()
    offered = f"The page offers: {available}." if available else "The page showed no options at all."
    return Explanation(
        f"The value '{option}' is not one of the options in step '{step}'. {offered}",
        "Check this item's input data, or whether the website changed its list. When the input writes names "
        "differently from the website on purpose, change the value before this step, or use match: loose when "
        "only spaces, hyphens, or case differ.")


def _choose_several(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"The value '{m.group(1)}' matches more than one option in step '{step}': {m.group(2)}.",
        "Give the exact name as the website writes it, or use match: exact.")


def _choose_search_empty(m: re.Match, step: str) -> Explanation:
    return Explanation(f"The search box in step '{step}' showed no options for '{m.group(1)}'.", m.group(2).strip())


def _choose_no_options(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"No options appeared after step '{step}' clicked the dropdown.",
        "Compare the dropdown's selector with the page in the screenshot, and let the page finish loading before "
        "this step; set search: true if the list needs typing first.")


def _empty_parameter(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"The parameter '{m.group(2)}' of step '{step}' was empty when the step ran.",
        "Check the value in flow.md and that the variable it refers to (a config value, a column of the input "
        "file, an output_var of an earlier step) is set for this item.")


def _list_none(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"Step '{step}' found no element matching '{m.group(1)}' within {int(m.group(2)) / 1000:g} s.",
        "Compare the selector with the page in the screenshot: the page may have changed, or a different page is "
        "shown (an error, a login, no results). Raise timeout if the page is only slow.")


def _too_few(m: re.Match, step: str) -> Explanation:
    kind = "items" if m.group(1) == "web.get_list" else "rows"
    return Explanation(
        f"Step '{step}' read {m.group(4)} {kind} from '{m.group(3)}', fewer than min_rows ({m.group(2)}).",
        "If the page really had nothing to read (an empty category, no results today), lower min_rows or check for "
        "that case before this step. Otherwise the page was not ready or the selector changed: compare it with "
        "the screenshot.")


def _item_field_missing(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"Item {m.group(1)} on the page has no '{m.group(2)}' (selector '{m.group(3)}'), which step '{step}' "
        f"requires.",
        "If some items really lack it, set on_item_error: skip to leave those items out, or take the field out of "
        "required_fields. If every item should have it, update the field's selector.")


def _table_columns(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"The table read in step '{step}' has no column {m.group(1)}; its headers are {m.group(2)}.",
        "The website changed its table, or the names in columns differ from the headers: use the names shown.")


def _no_page(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"Step '{step}' needs an open browser page, but none was open.",
        "Add a web.open before this step, or check whether an earlier web.close or a subflow closed the browser.")


def _exists(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"'{m.group(1)}' already exists, and step '{step}' does not overwrite it.",
        "Set overwrite: true, delete the old file in an earlier step, or put the date or ${run.id} in the name.")


def _encoding(m: re.Match, step: str) -> Explanation:
    return Explanation(
        f"Step '{step}' could not read {m.group(1)} as {m.group(2)}: the file uses another encoding.",
        "Set the encoding parameter. Thai files from older systems are often 'cp874' or 'tis-620'; a file saved "
        "from Excel as UTF-8 is 'utf-8-sig'.")


def _http(m: re.Match, step: str) -> Explanation:
    status = int(m.group(2))
    if status in _HTTP_CAUSES:
        cause = _HTTP_CAUSES[status]
    elif status >= 500:
        cause = f"the service had an error of its own (HTTP {status}); the request may be fine"
    else:
        cause = f"the service answered HTTP {status}"
    if status in _HTTP_FIXES:
        fix = _HTTP_FIXES[status]
    elif status >= 500:
        fix = "Retry later (max_retries with retry_interval); if it keeps failing, ask the service's owner."
    else:
        fix = "Compare the request (method, URL, headers, payload) with the service's documentation."
    return Explanation(f"In step '{step}', {m.group(1)}: {cause}.", fix)


_RULES: List[Tuple[Pattern, Callable[[re.Match, str], Explanation]]] = [
    (re.compile(r"web\.choose: option '(.*?)' not found; available: (.*)", re.S), _choose_not_found),
    (re.compile(r"web\.choose: option '(.*?)' matches several options loosely: (.*?); give the exact name", re.S),
     _choose_several),
    (re.compile(r"web\.choose: the search box shows no options for '(.*?)'\. (.*)", re.S), _choose_search_empty),
    (re.compile(r"web\.choose: no options appeared after clicking the dropdown"), _choose_no_options),
    (re.compile(r"(web\.\w+): '(\w+)' is empty\."), _empty_parameter),
    (re.compile(r"web\.get_list: no element matches '(.*?)' within (\d+) ms\."), _list_none),
    (re.compile(r"(web\.get_list|web\.get_table): expected at least (\d+) (?:item|row)\(s\) (?:matching|in) "
                r"'(.*?)', found (\d+)\."), _too_few),
    (re.compile(r"web\.get_list: item (\d+) has no '(.*?)' \(selector '(.*?)'\)"), _item_field_missing),
    (re.compile(r"web\.get_table: column\(s\) (.*?) not found; table headers are (.*)", re.S), _table_columns),
    (re.compile(r"No active browser page found"), _no_page),
    (re.compile(r"(?:Destination|Zip file|File) already exists and overwrite is false: (.*)"), _exists),
    (re.compile(r"Could not read (.*?) as (\S+?)\. "), _encoding),
    (re.compile(r"^(\w+ \S+) answered HTTP (\d{3})"), _http),
]


def explain(message: str, step_name: str) -> Optional[Explanation]:
    """root_cause and suggested_fix for a known Kinenix action error message, or None."""
    if not message:
        return None
    for pattern, build in _RULES:
        found = pattern.search(message)
        if found:
            return build(found, step_name)
    return None
