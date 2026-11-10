import json
import pytest
from pathlib import Path

from kinenix.models.flow import FlowDefinition, Step
from kinenix.engine.markdown import (
    flow_to_markdown,
    markdown_to_flow,
    load_flow,
    flow_to_json_text,
    export_json_to_markdown,
    format_value,
    markdown_issues,
    parse_value,
)


def test_markdown_to_flow_basic():
    md = """# My Test Flow
> Description: Automate sample website login
> Version: 1.2.0

## Variables
- `login_url`: https://example.com/login
- `retry_count`: 3
- `is_active`: true

## Steps

### 1. Open Website (`web.open`)
- **url:** ${login_url}
- **headless:** true

### 2. Enter Username (`web.type`)
- **selector:** #username
- **text:** admin
- **output_var:** `last_status`
"""
    flow = markdown_to_flow(md)
    assert flow.name == "My Test Flow"
    assert flow.description == "Automate sample website login"
    assert flow.version == "1.2.0"
    assert flow.variables["login_url"] == "https://example.com/login"
    assert flow.variables["retry_count"] == 3
    assert flow.variables["is_active"] is True

    assert len(flow.steps) == 2
    assert flow.steps[0].id == "step_1"
    assert flow.steps[0].name == "Open Website"
    assert flow.steps[0].action == "web.open"
    assert flow.steps[0].parameters["url"] == "${login_url}"
    assert flow.steps[0].parameters["headless"] is True

    assert flow.steps[1].id == "step_2"
    assert flow.steps[1].name == "Enter Username"
    assert flow.steps[1].action == "web.type"
    assert flow.steps[1].parameters["selector"] == "#username"
    assert flow.steps[1].parameters["text"] == "admin"
    assert flow.steps[1].output_var == "last_status"


def test_nested_sub_steps_and_else():
    md = """# Nested Flow
> Description: Flow with loops and conditions
> Version: 1.0.0

## Steps

### 1. Loop Records (`logic.loop`)
- **items:** ${records}
- **item_var:** row
- **Sub-steps:**
  - Check Status (`logic.if`):
    - **condition:** ${row.status} == 'OK'
    - **Sub-steps:**
      - Process Row (`web.type`):
        - **text:** ${row.name}
    - **Else-steps:**
      - Log Warning (`logic.append`):
        - **target:** errors
        - **item:** ${row.name}
"""
    flow = markdown_to_flow(md)
    assert len(flow.steps) == 1
    step_1 = flow.steps[0]
    assert step_1.action == "logic.loop"
    assert step_1.sub_steps is not None
    assert len(step_1.sub_steps) == 1

    if_step = step_1.sub_steps[0]
    assert if_step.action == "logic.if"
    assert if_step.condition == "${row.status} == 'OK'"
    assert if_step.sub_steps is not None
    assert len(if_step.sub_steps) == 1
    assert if_step.sub_steps[0].action == "web.type"
    assert if_step.sub_steps[0].parameters["text"] == "${row.name}"

    assert if_step.else_steps is not None
    assert len(if_step.else_steps) == 1
    assert if_step.else_steps[0].action == "logic.append"
    assert if_step.else_steps[0].parameters["target"] == "errors"


def test_roundtrip_equality():
    flow = FlowDefinition(
        name="Roundtrip Test",
        description="Verify roundtrip serialization",
        version="2.0.0",
        variables={"count": 5, "flag": False},
        steps=[
            Step(
                id="step_1",
                name="Start Step",
                action="logic.delay",
                parameters={"seconds": 1.5},
            ),
            Step(
                id="step_2",
                name="Call API",
                action="http.request",
                parameters={"url": "https://api.example.com", "method": "GET"},
                output_var="api_response",
            ),
        ],
    )

    md_text = flow_to_markdown(flow)
    reloaded_flow = markdown_to_flow(md_text)

    assert reloaded_flow.name == flow.name
    assert reloaded_flow.description == flow.description
    assert reloaded_flow.version == flow.version
    assert reloaded_flow.variables == flow.variables
    assert len(reloaded_flow.steps) == len(flow.steps)
    assert reloaded_flow.steps[0].action == flow.steps[0].action
    assert reloaded_flow.steps[0].parameters == flow.steps[0].parameters
    assert reloaded_flow.steps[1].output_var == flow.steps[1].output_var


def test_parse_quote_requests_flow_md():
    md_path = Path(__file__).resolve().parent.parent.parent / "flows" / "examples" / "quote_requests" / "flow.md"
    assert md_path.exists(), f"Missing reference flow.md at {md_path}"

    flow = load_flow(md_path)
    assert flow.name == "Motor Insurance Quote Requests"
    assert flow.version == "1.0.0"
    assert {"packages", "failed"} <= set(flow.variables)
    assert [s.action for s in flow.steps] == ["csv.read", "flow.fail", "logic.loop", "csv.write", "csv.write", "email.send"]
    assert len(flow.on_error_steps) == 2 and len(flow.finally_steps) == 1

    # Step 3: a loop whose sub-steps skip an item, call a subflow, and collect results
    loop_step = flow.steps[2]
    assert [s.action for s in loop_step.sub_steps] == [
        "logic.append", "flow.fail", "logic.set_variable", "flow.call", "logic.append", "logic.append"]
    skip, call = loop_step.sub_steps[1], loop_step.sub_steps[3]
    assert skip.condition and skip.error_handler.on_error == "next_item"
    assert call.error_handler.on_error == "continue"


def test_compile_and_export_cli_functions(tmp_path):
    sample_md = """# CLI Test
> Description: Testing CLI compilation
> Version: 1.0.0

## Steps

### 1. Delay Step (`logic.delay`)
- **seconds:** 1
"""
    md_file = tmp_path / "flow.md"
    md_file.write_text(sample_md, encoding="utf-8")

    # The compiled form, as `kinenix compile` shows it
    json_out = tmp_path / "compiled.json"
    json_out.write_text(flow_to_json_text(load_flow(md_file)), encoding="utf-8")
    assert not (tmp_path / "flow.json").exists()

    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["name"] == "CLI Test"
    assert data["steps"][0]["action"] == "logic.delay"
    assert data["steps"][0]["parameters"]["seconds"] == 1

    # Export back to Markdown
    exported_md = tmp_path / "flow_exported.md"
    export_json_to_markdown(json_out, output_md_path=exported_md)
    assert exported_md.exists()

    # Re-read and check
    re_flow = load_flow(exported_md)
    assert re_flow.name == "CLI Test"
    assert re_flow.steps[0].action == "logic.delay"


def test_condition_backtick_stripping():
    md = """# Condition Test
> Description: Testing condition with backticks
> Version: 1.0.0

## Steps

### 1. Conditional Action (`logic.delay`)
- **condition:** `${has_cookie_banner} == true`
- **seconds:** 1
"""
    flow = markdown_to_flow(md)
    assert flow.steps[0].condition == "${has_cookie_banner} == true"
    
    from kinenix.engine.interpreter import FlowInterpreter
    fi = FlowInterpreter()
    assert fi._evaluate_condition_expr("`true == true`") is True
    assert fi._evaluate_condition_expr("`false == true`") is False




@pytest.mark.parametrize("text, expected", [
    ("0012", "0012"), ("-007", "-007"), ("0", 0), ("-0", 0), ("120", 120), ("-15", -15), ("0.5", 0.5),
])
def test_codes_with_a_leading_zero_stay_text(text, expected):
    # #103: a branch code or postal code such as 0012 keeps its zero
    assert parse_value(text) == expected and type(parse_value(text)) is type(expected)
    assert parse_value(format_value(expected)) == expected


def test_json_like_values_that_are_not_json_are_reported():
    # #103: they are read as text, so an action expecting a dict or list would fail later at run time
    issues = markdown_issues("""# T

## Steps

### 1. Add (`logic.append`)
- **target:** rows
- **item:** {"net": ${number(inv.amount)}}
- **items:** [1, 2,]
- **fine:** {"net": "${number(inv.amount)}"}
- **text:** ${a} and [b]
- **selector:** [data-testid=carBrand]
- **other:** `[role=option] >> nth=0`
- **ids:** ["${a}", ${b}]
""")
    assert len(issues) == 3  # CSS attribute selectors are not lists
    assert issues[0].startswith("Line 7: 'item' in step 'Add' looks like JSON but is not valid JSON")
    assert 'for example {"net": "${number(inv.amount)}"}' in issues[0]
    assert issues[1].startswith("Line 8: 'items' in step 'Add'") and "${" not in issues[1]
    assert issues[2].startswith("Line 13: 'ids' in step 'Add'")
