import json
import re
from pathlib import Path

import pytest

from kinenix.actions.registry import ActionRegistry
from kinenix.engine.markdown import load_flow, markdown_to_flow
from kinenix.engine.validation import validate_flow
from kinenix.models.flow import FlowDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]


def _flow(steps):
    return FlowDefinition.model_validate({"name": "Demo", "steps": steps})


def test_valid_flow_has_no_issues():
    flow = markdown_to_flow("""# Ok

### 1. Open (`web.open`)
- **url:** https://example.com
- **on_error:** retry
- **max_retries:** 1

### 2. Loop (`logic.loop`)
- **items:** []
- **Sub-steps:**
  - Click (`web.click`):
    - **selector:** button
    - **optional:** true
""")
    assert validate_flow(flow) == []


def test_reports_typos_with_suggestions_in_nested_steps():
    flow = _flow([
        {"id": "s1", "name": "Open", "action": "web.open", "parameters": {"url": "x", "timout": 1}},
        {"id": "s2", "name": "Read", "action": "web.get_tabel", "parameters": {}},
        {"id": "s3", "name": "If", "action": "logic.if", "parameters": {"condition": "true"},
         "else_steps": [{"id": "s3e", "name": "Click", "action": "web.click", "parameters": {"selecter": "b"}}]},
    ])
    issues = validate_flow(flow)
    assert len(issues) == 3
    assert "'timout'" in issues[0] and "Did you mean 'timeout'" in issues[0]
    assert "unknown action 'web.get_tabel'" in issues[1] and "'web.get_table'" in issues[1]
    assert "Step 's3e'" in issues[2] and "'selector'" in issues[2]


def test_step_level_keys_in_parameters_point_to_the_right_place():
    flow = _flow([{"id": "s1", "name": "Open", "action": "web.open",
                   "parameters": {"url": "x", "on_error": "retry", "output_var": "page"}}])
    issues = validate_flow(flow)
    assert "belongs in error_handler" in issues[0]
    assert "belongs in the step's output_var" in issues[1]


def test_every_action_declares_its_parameters():
    # Only the shipped actions; other tests register throwaway actions in the same registry
    undeclared = [name for name, cls in ActionRegistry.list_actions().items()
                  if cls.__module__.startswith("kinenix.actions.") and cls.accepted_parameters is None]
    assert undeclared == [], f"Add accepted_parameters to: {undeclared}"


def test_documented_parameters_are_accepted():
    """Every parameter in docs/actions_reference.md tables must be one the action reads, so docs and code agree."""
    text = (REPO_ROOT / "docs" / "actions_reference.md").read_text(encoding="utf-8")
    sections = re.split(r"^### `([a-z_]+\.[a-z_]+)`\s*$", text, flags=re.M)
    problems = []
    for name, body in zip(sections[1::2], sections[2::2]):
        documented = set(re.findall(r"^\|\s*`([a-zA-Z_]+)`", body.split("**Example")[0], flags=re.M))
        accepted = set(ActionRegistry.get(name).accepted_parameters)
        problems += [f"{name}: {p}" for p in sorted(documented - accepted)]
    assert problems == [], f"Documented but not accepted: {problems}"


def _repo_flows():
    flows = []
    for path in sorted((REPO_ROOT / "flows").rglob("*.md")):
        if path.name == "README.md":
            continue
        if any(part in ("output", "assets", "config") for part in path.relative_to(REPO_ROOT).parts):
            continue
        flows.append(path)
    return flows


@pytest.mark.parametrize("path", _repo_flows(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_repository_flows_are_valid(path, monkeypatch):
    # Like the docs, the examples describe the version being developed, which their `> Requires:` may name
    from kinenix.engine import requires
    monkeypatch.setattr(requires, "__version__", "999.0")
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if "steps" not in data:
            pytest.skip("not a flow definition")
    # Checked in their bundle, so ${names} are checked too (#162): no misspellings, and no hints either
    bundle = path.parent.parent if path.parent.name == "subflows" else path.parent
    hints = []
    assert validate_flow(load_flow(path), bundle, hints) == []
    assert hints == []


def test_every_action_declares_its_side_effects():
    """docs/design/agent-interface.md, section 10: a run can be described and confirmed before it starts."""
    from kinenix.actions.base import SIDE_EFFECT_KINDS
    from kinenix.actions.registry import ActionRegistry

    for name, action in ActionRegistry.list_actions().items():
        if not action.__module__.startswith("kinenix.actions."):
            continue  # actions that tests register
        kinds = action.side_effects
        assert kinds, f"{name} declares no side_effects"
        assert set(kinds) <= set(SIDE_EFFECT_KINDS), f"{name}: unknown kind in {kinds}"
        assert kinds == ("none",) or "none" not in kinds, f"{name}: 'none' cannot be combined with other kinds"
    assert ActionRegistry.get("email.send").side_effects == ("email",)
    assert ActionRegistry.get("web.get_table").side_effects == ("none",)
