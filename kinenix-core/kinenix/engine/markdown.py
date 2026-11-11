import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..models.flow import FlowDefinition, Step, ErrorHandlerConfig


_ACTION_REGEX = re.compile(r"\(\s*`?([a-zA-Z0-9_\.]+)`?\s*\)")
_STEP_HEADING_REGEX = re.compile(
    r"^###\s+(?:(?P<idx>[\w\.\-]+)\.\s+)?(?P<name>.+?)\s*\(\s*`?(?P<action>[a-zA-Z0-9_\.]+)`?\s*\)\s*$"
)
_CHILD_STEP_REGEX = re.compile(
    r"^-\s+(?:(?P<idx>[\w\.\-]+)\.\s+)?(?P<name>.+?)\s*\(\s*`?(?P<action>[a-zA-Z0-9_\.]+)`?\s*\)\s*:?\s*$"
)
_PARAM_REGEX = re.compile(
    r"^-\s+\*\*(?P<key>[a-zA-Z0-9_]+):?\*\*:?\s*(?P<val>.*)$"
)
_ALT_PARAM_REGEX = re.compile(
    r"^-\s+(?P<key>[a-zA-Z0-9_]+):\s*(?P<val>.*)$"
)
_SUB_STEPS_REGEX = re.compile(
    r"^-\s+\*\*(?:Sub-steps|sub_steps):?\*\*:?\s*$", re.IGNORECASE
)
_ELSE_STEPS_REGEX = re.compile(
    r"^-\s+\*\*(?:Else-steps|else_steps):?\*\*:?\s*$", re.IGNORECASE
)
_ALT_SUB_STEPS_REGEX = re.compile(
    r"^-\s+(?:Sub-steps|sub_steps):\s*$", re.IGNORECASE
)
_ALT_ELSE_STEPS_REGEX = re.compile(
    r"^-\s+(?:Else-steps|else_steps):\s*$", re.IGNORECASE
)

# Step keys that configure retry and failure behavior; they belong to Step.error_handler, not to the
# action parameters, because the interpreter reads them from error_handler only
ERROR_HANDLER_KEYS = ("on_error", "max_retries", "retry_interval", "fallback_step_id", "error_message")


# `## On Error` and `## Finally` hold steps that run when Steps fail, and after everything (docs/flow_markdown_spec.md)
SECTION_TITLES = {"on error": "on_error", "onerror": "on_error", "finally": "finally"}
SECTION_ID_PREFIX = {"steps": "step_", "on_error": "on_error_", "finally": "finally_"}
SECTION_HEADINGS = {"steps": "Steps", "on_error": "On Error", "finally": "Finally"}


# A parameter written as `- **body:** |` takes the indented lines below it as its value
BLOCK_MARKER = "|"

Line = Tuple[int, str, int]  # (indent, stripped text, line number)


def _block_value(body_lines: List[Line], start: int, key_indent: int) -> Tuple[Optional[str], int]:
    """
    Reads a multi-line value: the blank or more deeply indented lines from `start` on. Their common
    indentation is removed, relative indentation and blank lines inside are kept, and blank lines at
    the end are dropped. Returns (None, start) when no indented line follows, so a lone `|` stays a value.
    """
    end = start
    while end < len(body_lines) and (not body_lines[end][1] or body_lines[end][0] > key_indent):
        end += 1
    collected = body_lines[start:end]
    while collected and not collected[-1][1]:
        collected.pop()
    if not collected:
        return None, start
    base = min(indent for indent, text, _ in collected if text)
    text = "\n".join(" " * (indent - base) + line if line else "" for indent, line, _ in collected)
    return text, start + len(collected)


def _json_issue(lineno: int, key: str, val_raw: str, val: Any, step_name: str) -> Optional[str]:
    """A value written as {...} or [...] that is not valid JSON is read as text; say so instead of failing later."""
    text = val_raw.strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        text = text[1:-1].strip()
    # [data-testid=x] is a CSS selector, not a list: a JSON list starts with a value ("a", 1, {, [, or ${...})
    looks_like_list = text.startswith("[") and text.endswith("]") and re.match(r'^\[\s*["\d\-{\[$\]]', text)
    if not isinstance(val, str) or not ((text.startswith("{") and text.endswith("}")) or looks_like_list):
        return None
    try:
        json.loads(text)
    except ValueError as e:
        hint = (' Put quotes around ${...} inside JSON, for example {"net": "${number(inv.amount)}"}.'
                if "${" in text else "")
        return (f"Line {lineno}: '{key}' in step '{step_name}' looks like JSON but is not valid JSON ({e}), "
                f"so it is read as text.{hint}")
    return None


def _stray_line_issue(lineno: int, text: str, step_name: str) -> str:
    shown = text if len(text) <= 60 else text[:57] + "..."
    return (f"Line {lineno}: '{shown}' in step '{step_name}' is not a parameter and was ignored. "
            f"For a value with several lines, write the parameter as `- **name:** |` and indent the lines below it.")


def _param_lines(pad: str, key: str, value: Any) -> List[str]:
    """Markdown lines for one parameter; text with line breaks is written as a `|` block."""
    if isinstance(value, str) and "\n" in value:
        inner = pad + "    "
        return [f"{pad}- **{key}:** {BLOCK_MARKER}"] + [inner + line if line else "" for line in value.split("\n")]
    return [f"{pad}- **{key}:** {format_value(value)}"]


def _error_handler_lines(step: Step, pad: str) -> List[str]:
    if not step.error_handler:
        return []
    values = step.error_handler.model_dump(exclude_defaults=True)
    return [f"{pad}- **{key}:** {format_value(values[key])}" for key in ERROR_HANDLER_KEYS if key in values]


def parse_value(val_str: str) -> Any:
    """Parse a string into a typed Python value (bool, int, float, json, or str)."""
    val_str = val_str.strip()
    if not val_str:
        return ""

    # Strip enclosing inline backticks, e.g. `challenge_data` -> challenge_data
    if val_str.startswith("`") and val_str.endswith("`") and len(val_str) >= 2:
        val_str = val_str[1:-1].strip()

    # Booleans and Null
    low = val_str.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None

    # Integers; codes with a leading zero ("0012", a postal code) stay text so the zero is kept
    if re.match(r"^-?\d+$", val_str) and not re.match(r"^-?0\d", val_str):
        try:
            return int(val_str)
        except ValueError:
            pass

    # Floats
    if re.match(r"^-?\d+\.\d+$", val_str):
        try:
            return float(val_str)
        except ValueError:
            pass

    # JSON Objects / Arrays
    if (val_str.startswith("{") and val_str.endswith("}")) or (val_str.startswith("[") and val_str.endswith("]")):
        try:
            return json.loads(val_str)
        except Exception:  # nosec B110: not JSON, so the value stays text
            pass

    # Quoted strings: "string" or 'string'
    if (val_str.startswith('"') and val_str.endswith('"')) or (val_str.startswith("'") and val_str.endswith("'")):
        if len(val_str) >= 2:
            return val_str[1:-1]

    return val_str


def format_value(val: Any) -> str:
    """Format a Python value into markdown representation."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if val is None:
        return "null"
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, (int, float)):
        return str(val)
    text = str(val)
    # Text that would read back as another type ("100", "true", "null", "[1]") keeps its quotes,
    # so converting a flow to Markdown never changes a value's type
    if parse_value(text) != text:
        return json.dumps(text, ensure_ascii=False)
    # A variable expression like ${foo} and other plain text stay as they are
    return text


def _parse_sub_steps_block(lines: List[Line], parent_id: str, issues: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Recursively parse indented sub-steps from lines formatted as: (indent, raw_stripped_text, line_number).
    Blank lines are kept, because they belong to multi-line values.
    """
    if not lines:
        return []

    # Filter out blank lines
    non_blank = [item for item in lines if item[1]]
    if not non_blank:
        return []

    min_indent = min(item[0] for item in non_blank)
    
    # Group steps at min_indent
    steps: List[Dict[str, Any]] = []
    current_step_lines: List[Tuple[int, str, int]] = []
    current_match = None

    def finalize_step(match, body_lines, step_idx, line):
        idx_val = match.group("idx")
        name = match.group("name").strip()
        action = match.group("action").strip()

        step_id = idx_val if idx_val else f"{parent_id}_{step_idx}"
        if not step_id.startswith("step_") and not step_id.startswith("sub_"):
            step_id = f"sub_{step_id}"

        step_dict: Dict[str, Any] = {
            "id": step_id,
            "name": name,
            "action": action,
            "parameters": {},
            "line": line,
        }

        # Parse body_lines
        i = 0
        while i < len(body_lines):
            indent, text, lineno = body_lines[i]
            
            # Check for Sub-steps:
            sub_match = _SUB_STEPS_REGEX.match(text) or _ALT_SUB_STEPS_REGEX.match(text)
            else_match = _ELSE_STEPS_REGEX.match(text) or _ALT_ELSE_STEPS_REGEX.match(text)

            if not text:
                i += 1
                continue

            if sub_match:
                # Collect all subsequent lines that have higher indentation
                sub_lines = []
                i += 1
                while i < len(body_lines) and (body_lines[i][0] > indent or not body_lines[i][1]):
                    sub_lines.append(body_lines[i])
                    i += 1
                sub_parsed = _parse_sub_steps_block(sub_lines, parent_id=step_id, issues=issues)
                if sub_parsed:
                    step_dict["sub_steps"] = sub_parsed
                continue

            elif else_match:
                else_lines = []
                i += 1
                while i < len(body_lines) and (body_lines[i][0] > indent or not body_lines[i][1]):
                    else_lines.append(body_lines[i])
                    i += 1
                else_parsed = _parse_sub_steps_block(else_lines, parent_id=f"{step_id}_else", issues=issues)
                if else_parsed:
                    step_dict["else_steps"] = else_parsed
                continue

            # Check for parameters
            param_match = _PARAM_REGEX.match(text) or _ALT_PARAM_REGEX.match(text)
            if param_match:
                key = param_match.group("key")
                val_raw = param_match.group("val")
                val = parse_value(val_raw)
                if val_raw.strip() == BLOCK_MARKER:
                    block, next_i = _block_value(body_lines, i + 1, indent)
                    if block is not None:
                        val_raw, val = block, block
                        i = next_i - 1

                if key == "output_var":
                    step_dict["output_var"] = str(val) if val is not None else None
                elif key == "condition":
                    cond_val = str(val_raw).strip()
                    if cond_val.startswith("`") and cond_val.endswith("`") and len(cond_val) >= 2:
                        cond_val = cond_val[1:-1].strip()
                    step_dict["condition"] = cond_val
                elif key == "description":
                    step_dict["description"] = str(val)
                elif key == "id":
                    step_dict["id"] = str(val)
                elif key in ERROR_HANDLER_KEYS:
                    step_dict.setdefault("error_handler", {})[key] = val
                elif key == "error_handler" and isinstance(val, dict):
                    step_dict.setdefault("error_handler", {}).update(val)
                else:
                    step_dict["parameters"][key] = val
                problem = _json_issue(lineno, key, val_raw, val, name) if issues is not None else None
                if problem:
                    issues.append(problem)
            elif issues is not None:
                issues.append(_stray_line_issue(lineno, text, name))
            i += 1

        return step_dict

    child_counter = 1
    current_line = 0
    for indent, text, lineno in lines:
        if text and indent == min_indent:
            match = _CHILD_STEP_REGEX.match(text)
            if match:
                if current_match:
                    steps.append(finalize_step(current_match, current_step_lines, child_counter, current_line))
                    child_counter += 1
                current_match = match
                current_line = lineno
                current_step_lines = []
                continue
        if current_match:
            current_step_lines.append((indent, text, lineno))
        elif text and issues is not None:
            issues.append(
                f"Line {lineno}: '{text[:60]}' is not a sub-step. Under `- **Sub-steps:**`, each sub-step is a "
                f"bullet with its action, `  - Name (`action.name`):`, and its parameters are indented below it.")

    if current_match:
        steps.append(finalize_step(current_match, current_step_lines, child_counter, current_line))

    return steps


def markdown_to_flow(md_content: str, issues: Optional[List[str]] = None) -> FlowDefinition:
    """
    Parses a Flow Markdown specification string into a validated FlowDefinition.
    Adheres strictly to docs/flow_markdown_spec.md. When `issues` is a list, lines that were ignored
    (text under a step that is not a parameter) are reported in it.
    """
    # Tabs count as four spaces, so indentation typed with Tab works like spaces
    lines = [line.expandtabs(4) for line in md_content.splitlines()]
    
    flow_name = "Untitled Flow"
    description: Optional[str] = None
    version = "1.0.0"
    requires: Optional[str] = None
    variables: Dict[str, Any] = {}

    in_variables_section = False
    in_steps_section = False
    section = "steps"  # which list the following step headings belong to: steps, on_error, or finally

    # (section, heading line, heading match, body lines)
    raw_steps: List[Tuple[str, int, re.Match, List[Line]]] = []
    current_step_match: Optional[re.Match] = None
    current_step_line = 0
    current_step_lines: List[Tuple[int, str, int]] = []

    def flush() -> None:
        nonlocal current_step_match, current_step_lines
        if current_step_match:
            raw_steps.append((section, current_step_line, current_step_match, current_step_lines))
        current_step_match = None
        current_step_lines = []

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        # 1. Level 1 Heading: Flow Title
        if stripped.startswith("# ") and not in_steps_section:
            flow_name = stripped[2:].strip()
            continue

        # 2. Blockquotes: Description and Version
        if stripped.startswith(">") and not in_steps_section:
            quote_text = stripped[1:].strip()
            if quote_text.lower().startswith("description:"):
                description = quote_text[len("description:"):].strip()
            elif quote_text.lower().startswith("version:"):
                version = quote_text[len("version:"):].strip()
            elif quote_text.lower().startswith("requires:"):
                requires = quote_text[len("requires:"):].strip()
            continue

        # 3. Section headers
        if stripped.startswith("## "):
            sec_title = stripped[3:].strip().lower()
            sec_key = re.sub(r"[\s_-]+", " ", sec_title)
            if sec_key in SECTION_TITLES:
                flush()
                section = SECTION_TITLES[sec_key]
                in_steps_section = True
                in_variables_section = False
                continue
            if "variable" in sec_title:
                in_variables_section = True
                in_steps_section = False
                continue
            elif "step" in sec_title:
                flush()
                section = "steps"
                in_steps_section = True
                in_variables_section = False
                continue

        # 4. Variables section
        if in_variables_section and not in_steps_section:
            if stripped.startswith("-"):
                # Format: - `var_name`: value or - var_name: value
                v_match = re.match(r"^-\s+(?:`(?P<key>[^`]+)`|(?P<key2>[a-zA-Z0-9_]+)):\s*(?P<val>.*)$", stripped)
                if v_match:
                    k = v_match.group("key") or v_match.group("key2")
                    v_raw = v_match.group("val")
                    variables[k] = parse_value(v_raw)
                continue

        # 5. Steps section: Level 3 Headings
        step_match = _STEP_HEADING_REGEX.match(stripped)
        if not step_match and in_steps_section and stripped.startswith("### "):
            if issues is not None:
                issues.append(
                    f"Line {lineno}: step heading '{stripped[:60]}' has no action, so it is not a step. "
                    f"Put the action in parentheses at the end: `### 1. Open Page (`web.open`)`.")
            flush()
            continue
        if step_match:
            in_steps_section = True
            in_variables_section = False
            flush()
            current_step_match = step_match
            current_step_line = lineno
            continue

        if in_steps_section and current_step_match:
            current_step_lines.append((indent, stripped, lineno))

    flush()

    # Process all steps; ids are step_N, on_error_N, or finally_N, numbered per section
    compiled: Dict[str, List[Dict[str, Any]]] = {"steps": [], "on_error": [], "finally": []}
    step_counters = {"steps": 1, "on_error": 1, "finally": 1}

    for step_section, heading_line, match, body_lines in raw_steps:
        idx_val = match.group("idx")
        name = match.group("name").strip()
        action = match.group("action").strip()
        prefix = SECTION_ID_PREFIX[step_section]

        if idx_val:
            if idx_val.isdigit():
                step_id = f"{prefix}{idx_val}"
            else:
                step_id = idx_val
        else:
            step_id = f"{prefix}{step_counters[step_section]}"

        step_counters[step_section] += 1

        step_dict: Dict[str, Any] = {
            "id": step_id,
            "name": name,
            "action": action,
            "parameters": {},
            "line": heading_line,
        }

        i = 0
        while i < len(body_lines):
            indent, text, lineno = body_lines[i]
            if not text:
                i += 1
                continue

            sub_match = _SUB_STEPS_REGEX.match(text) or _ALT_SUB_STEPS_REGEX.match(text)
            else_match = _ELSE_STEPS_REGEX.match(text) or _ALT_ELSE_STEPS_REGEX.match(text)

            if sub_match:
                sub_lines = []
                i += 1
                while i < len(body_lines) and (body_lines[i][0] > indent or not body_lines[i][1]):
                    sub_lines.append(body_lines[i])
                    i += 1
                sub_parsed = _parse_sub_steps_block(sub_lines, parent_id=f"sub_{step_id}", issues=issues)
                if sub_parsed:
                    step_dict["sub_steps"] = sub_parsed
                continue

            elif else_match:
                else_lines = []
                i += 1
                while i < len(body_lines) and (body_lines[i][0] > indent or not body_lines[i][1]):
                    else_lines.append(body_lines[i])
                    i += 1
                else_parsed = _parse_sub_steps_block(else_lines, parent_id=f"sub_{step_id}_else", issues=issues)
                if else_parsed:
                    step_dict["else_steps"] = else_parsed
                continue

            param_match = _PARAM_REGEX.match(text) or _ALT_PARAM_REGEX.match(text)
            if param_match:
                key = param_match.group("key")
                val_raw = param_match.group("val")
                val = parse_value(val_raw)
                if val_raw.strip() == BLOCK_MARKER:
                    block, next_i = _block_value(body_lines, i + 1, indent)
                    if block is not None:
                        val_raw, val = block, block
                        i = next_i - 1

                if key == "output_var":
                    step_dict["output_var"] = str(val) if val is not None else None
                elif key == "condition":
                    cond_val = str(val_raw).strip()
                    if cond_val.startswith("`") and cond_val.endswith("`") and len(cond_val) >= 2:
                        cond_val = cond_val[1:-1].strip()
                    step_dict["condition"] = cond_val
                elif key == "description":
                    step_dict["description"] = str(val)
                elif key == "id":
                    step_dict["id"] = str(val)
                elif key in ERROR_HANDLER_KEYS:
                    step_dict.setdefault("error_handler", {})[key] = val
                elif key == "error_handler" and isinstance(val, dict):
                    step_dict.setdefault("error_handler", {}).update(val)
                else:
                    step_dict["parameters"][key] = val
                problem = _json_issue(lineno, key, val_raw, val, name) if issues is not None else None
                if problem:
                    issues.append(problem)
            elif issues is not None:
                issues.append(_stray_line_issue(lineno, text, name))
            i += 1

        compiled[step_section].append(step_dict)

    flow_payload = {
        "name": flow_name,
        "description": description,
        "version": version,
        "requires": requires,
        "variables": variables,
        "steps": compiled["steps"],
        "on_error_steps": compiled["on_error"] or None,
        "finally_steps": compiled["finally"] or None,
    }

    return FlowDefinition.model_validate(flow_payload)


def _serialize_sub_steps(steps: List[Step], indent_spaces: int = 2) -> List[str]:
    """Serializes child steps recursively with indentation."""
    lines: List[str] = []
    pad = " " * indent_spaces
    param_pad = " " * (indent_spaces + 2)

    for s in steps:
        lines.append(f"{pad}- {s.name} (`{s.action}`):")
        if s.description:
            lines.append(f"{param_pad}- **description:** {s.description}")
        if s.condition:
            lines.append(f"{param_pad}- **condition:** {s.condition}")
        if s.output_var:
            lines.append(f"{param_pad}- **output_var:** `{s.output_var}`")
        for k, v in s.parameters.items():
            lines.extend(_param_lines(param_pad, k, v))
        lines.extend(_error_handler_lines(s, param_pad))

        if s.sub_steps:
            lines.append(f"{param_pad}- **Sub-steps:**")
            lines.extend(_serialize_sub_steps(s.sub_steps, indent_spaces=indent_spaces + 4))
        if s.else_steps:
            lines.append(f"{param_pad}- **Else-steps:**")
            lines.extend(_serialize_sub_steps(s.else_steps, indent_spaces=indent_spaces + 4))

    return lines


def flow_to_markdown(flow: FlowDefinition) -> str:
    """
    Serializes a FlowDefinition into a formatted flow.md specification string.
    Adheres strictly to docs/flow_markdown_spec.md.
    """
    doc: List[str] = []

    # Title & Metadata
    doc.append(f"# {flow.name}")
    if flow.description:
        doc.append(f"> Description: {flow.description}")
    doc.append(f"> Version: {flow.version}")
    if flow.requires:
        doc.append(f"> Requires: {flow.requires}")
    doc.append("")

    # Variables
    if flow.variables:
        doc.append("## Variables")
        for k, v in flow.variables.items():
            doc.append(f"- `{k}`: {format_value(v)}")
        doc.append("")

    for section, steps in (("steps", flow.steps), ("on_error", flow.on_error_steps), ("finally", flow.finally_steps)):
        if section == "steps" or steps:
            doc.extend(_section_lines(section, steps or []))

    return "\n".join(doc).rstrip() + "\n"


def _section_lines(section: str, steps: List[Step]) -> List[str]:
    """Markdown for one step section (## Steps, ## On Error, ## Finally)."""
    doc = [f"## {SECTION_HEADINGS[section]}", ""]
    prefix = SECTION_ID_PREFIX[section]
    for idx, step in enumerate(steps, start=1):
        step_idx_str = str(idx)
        if step.id and step.id.startswith(prefix) and step.id[len(prefix):].isdigit():
            step_idx_str = step.id[len(prefix):]
        elif step.id:
            step_idx_str = step.id

        doc.append(f"### {step_idx_str}. {step.name} (`{step.action}`)")
        
        if step.description:
            doc.append(f"- **description:** {step.description}")
        if step.condition:
            doc.append(f"- **condition:** {step.condition}")
        if step.output_var:
            doc.append(f"- **output_var:** `{step.output_var}`")
        for k, v in step.parameters.items():
            doc.extend(_param_lines("", k, v))
        doc.extend(_error_handler_lines(step, ""))

        if step.sub_steps:
            doc.append("- **Sub-steps:**")
            doc.extend(_serialize_sub_steps(step.sub_steps, indent_spaces=2))
        if step.else_steps:
            doc.append("- **Else-steps:**")
            doc.extend(_serialize_sub_steps(step.else_steps, indent_spaces=2))

        doc.append("")
    return doc


def markdown_issues(md_content: str) -> List[str]:
    """Problems in a flow.md: lines the compiler ignores, step headings without an action, no steps at all."""
    issues: List[str] = []
    flow = markdown_to_flow(md_content, issues=issues)
    if not flow.steps:
        issues.append("No steps found. Write each step as a heading under `## Steps`: "
                      "`### 1. Step name (`action.name`)`, for example `### 1. Open Page (`web.open`)`.")
    return issues


JSON_FLOW_NOT_RUN = ("Flows are written in flow.md; {path} is a JSON flow, which Kinenix no longer reads. "
                     "Convert it once with: kinenix export-md {path}")


def load_flow(path_or_content: Union[str, Path]) -> FlowDefinition:
    """
    Loads a flow from:
    - a flow .md file
    - a bundle directory containing flow.md
    - Markdown text
    A JSON flow file raises an error that explains how to convert it (`kinenix export-md`).
    """
    if isinstance(path_or_content, Path) or (isinstance(path_or_content, str) and "\n" not in path_or_content and Path(path_or_content).exists()):
        p = Path(path_or_content).resolve()
        if p.is_dir():
            if (p / "flow.md").is_file():
                return markdown_to_flow((p / "flow.md").read_text(encoding="utf-8-sig"))
            if (p / "flow.json").is_file():
                raise ValueError(JSON_FLOW_NOT_RUN.format(path=p / "flow.json"))
            raise FileNotFoundError(f"No flow.md found in bundle directory: {p}")
        if p.suffix.lower() == ".md":
            return markdown_to_flow(p.read_text(encoding="utf-8-sig"))
        if p.suffix.lower() == ".json":
            raise ValueError(JSON_FLOW_NOT_RUN.format(path=p))
        raise ValueError(f"Unsupported flow file extension: {p.suffix} (expected .md)")

    return markdown_to_flow(str(path_or_content))


def flow_to_json_text(flow: FlowDefinition) -> str:
    """The compiled form of a flow as JSON text, for inspection (`kinenix compile`). Kinenix does not run it."""
    return json.dumps(flow.model_dump(exclude_none=True), indent=2, ensure_ascii=False) + "\n"


def export_json_to_markdown(json_path: Path, output_md_path: Optional[Path] = None) -> Path:
    """
    Converts a flow.json file (from Kinenix 0.2.0b3 or older) into flow.md, once.
    """
    json_path = json_path.resolve()
    if not json_path.is_file():
        raise FileNotFoundError(f"JSON flow file not found: {json_path}")

    raw = json.loads(json_path.read_text(encoding="utf-8-sig"))
    flow = FlowDefinition.model_validate(raw)
    md_text = flow_to_markdown(flow)

    if output_md_path is None:
        output_md_path = json_path.with_suffix(".md") if json_path.name != "flow.json" else json_path.parent / "flow.md"
    else:
        output_md_path = output_md_path.resolve()

    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text(md_text, encoding="utf-8")
    return output_md_path
