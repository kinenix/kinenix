"""Static checks on a flow before it runs: unknown actions and parameters that no action reads.

A misspelled parameter (for example `timout`) is otherwise ignored silently and the action falls back to
its default, which is hard to notice. These checks only report; callers decide whether to warn or stop.
"""
import ast
import difflib
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set

from .. import actions  # noqa: F401  (imports every action module so the registry is complete)
from ..actions.registry import ActionRegistry
from ..models.flow import FlowDefinition, Step
from . import expressions
from .conditions import grouping_problem
from .evaluator import VariableEvaluator
from .requires import requirement_problem, version_key

# Keys that belong to the step itself; seeing them in parameters means a converted flow or a typo put them there
STEP_LEVEL_KEYS = {
    "on_error": "error_handler",
    "max_retries": "error_handler",
    "retry_interval": "error_handler",
    "fallback_step_id": "error_handler",
    "error_message": "error_handler",
    "output_var": "the step's output_var",
    "condition": "the step's condition",
}


def _walk(steps: Iterable[Step]) -> Iterable[Step]:
    for step in steps or []:
        yield step
        yield from _walk(step.sub_steps)
        yield from _walk(step.else_steps)


def _outside_loops(steps: Iterable[Step]) -> Iterable[Step]:
    """Steps that no logic.loop encloses (logic.if branches are looked into, loop sub-steps are not)."""
    for step in steps or []:
        yield step
        if step.action != "logic.loop":
            yield from _outside_loops(step.sub_steps)
            yield from _outside_loops(step.else_steps)


def _on_error(step: Step) -> str:
    return str(step.error_handler.on_error).strip().lower() if step.error_handler else ""


def leftover_json_flows(md_path: Path) -> List[str]:
    """
    flow.json next to flow.md, or a subflow .json next to its .md: Kinenix reads only the .md files, so these are
    leftovers from Kinenix 0.2.0b3 or older, or written by an assistant following old docs (#105).
    """
    if md_path.name != "flow.md":
        return []
    bundle = md_path.parent
    found = [bundle / "flow.json"] if (bundle / "flow.json").is_file() else []
    subflows = bundle / "subflows"
    if subflows.is_dir():
        found += sorted(p for p in subflows.glob("*.json") if p.with_suffix(".md").is_file())
    return [f"{p.relative_to(bundle).as_posix()} is not read: flows are .md files, and "
            f"{p.with_suffix('.md').relative_to(bundle).as_posix()} is the one that runs. Delete the .json file "
            f"so nobody edits it by mistake. If the project's AGENTS.md still describes JSON flows, refresh it "
            f"with: kinenix init --update-agents {bundle}" for p in found]


def _all_steps(flow: FlowDefinition) -> List[Step]:
    """Steps, On Error, and Finally, in that order."""
    return list(flow.steps) + list(flow.on_error_steps or []) + list(flow.finally_steps or [])


ON_ERROR_VALUES = ("fail", "stop", "retry", "continue", "ignore", "next_item")

# What older Kinenix versions would run wrongly instead of refusing: feature -> (first version that
# understands it, the last version that does not, what the older version does). item_label is only
# ignored by older versions, so it is not listed.
NEWER_FEATURES = {
    "## On Error": ("0.2.0b4", "0.2.0b3", "runs On Error steps as ordinary steps"),
    "## Finally": ("0.2.0b4", "0.2.0b3", "runs Finally steps as ordinary steps"),
    "inherit_config": ("0.2.0b4", "0.2.0b3", "ignores inherit_config"),
    "expressions in ${...}": ("0.3.0b1", "0.2.0b4", "turns expressions such as ${len(rows)} into empty text"),
    "and / or / not in conditions": ("0.3.0b1", "0.2.0b4", "reads and / or / not as part of a value"),
    "on_error: next_item": ("0.4.0b1", "0.3.0b1", "stops the flow at a step with on_error: next_item"),
    "on_error: ignore": ("1.1.0", "1.0.1", "stops the flow at a step with on_error: ignore"),
    "error_message": ("1.1.0", "1.0.1", "ignores error_message and reports the action's own message"),
    "list functions and comparisons in ${...}": (
        "1.1.0", "1.0.1", "stop the step at sort_by, where, sum, and comparisons, and read ${a and b} as empty text"),
}

# Functions added in 1.1.0 (docs/design/list-functions.md)
LIST_FUNCTIONS = {"sort_by", "where", "column", "sum", "min", "max", "average", "unique", "first", "last",
                  "contains", "text", "ifelse"}


REMOVED_IN = "Kinenix 2.0"


def deprecated_uses(flow: FlowDefinition) -> List[str]:
    """Parts of a flow that still work in 1.x but will be removed in 2.0. They are warnings, not problems:
    kinenix validate prints them without failing, and every run logs them."""
    found = []
    for step in _walk(_all_steps(flow)):
        where = f"Step '{step.id}' ({step.name})"
        if _on_error(step) == "retry":
            found.append(f"{where}: on_error retry is deprecated and will be removed in {REMOVED_IN}. "
                         f"It already works like fail: delete the line, or write on_error: fail. "
                         f"max_retries does the retrying.")
        if step.error_handler and step.error_handler.fallback_step_id:
            found.append(f"{where}: fallback_step_id is deprecated and will be removed in {REMOVED_IN}. "
                         f"Use on_error: continue and a next step with a condition on ${{error}}, "
                         f"or recover in ## On Error.")
    return found


def _uses_expressions(steps: List[Step]) -> bool:
    for step in steps:
        for text in _placeholders([step.parameters, step.condition]):
            if not text.startswith("env.") and expressions.problem(text) is None:
                try:
                    if not expressions.is_plain_path(expressions.parse(text)):
                        return True
                except expressions.ExpressionError:
                    pass
    return False


def _uses_list_functions(steps: List[Step]) -> bool:
    for step in steps:
        for text in _placeholders([step.parameters, step.condition]):
            if text.startswith("env.") or expressions.problem(text) is not None:
                continue
            try:
                tree = expressions.parse(text)
            except expressions.ExpressionError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Compare, ast.BoolOp)) or (
                        isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)) or (
                        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in LIST_FUNCTIONS):
                    return True
    return False


def _uses_boolean_conditions(steps: List[Step]) -> bool:
    from .conditions import parse_boolean
    for step in steps:
        for condition in (step.condition, step.parameters.get("condition") if step.action == "logic.if" else None):
            if isinstance(condition, str) and parse_boolean(condition.strip().strip("`"))[0] != "is":
                return True
    return False


def _newer_features(flow: FlowDefinition) -> List[str]:
    used = []
    if flow.on_error_steps:
        used.append("## On Error")
    if flow.finally_steps:
        used.append("## Finally")
    steps = list(_walk(_all_steps(flow)))
    if any(s.action == "flow.call" and "inherit_config" in s.parameters for s in steps):
        used.append("inherit_config")
    if _uses_expressions(steps):
        used.append("expressions in ${...}")
    if _uses_boolean_conditions(steps):
        used.append("and / or / not in conditions")
    if _uses_list_functions(steps):
        used.append("list functions and comparisons in ${...}")
    if any(_on_error(s) == "next_item" for s in steps):
        used.append("on_error: next_item")
    if any(_on_error(s) == "ignore" for s in steps):
        used.append("on_error: ignore")
    if any(s.error_handler and s.error_handler.error_message for s in steps):
        used.append("error_message")
    return used


def _version_problem(flow: FlowDefinition) -> Optional[str]:
    """The flow uses something an older Kinenix would run wrongly, and its `> Requires:` does not exclude that version."""
    used = _newer_features(flow)
    if not used:
        return None
    needed = max((NEWER_FEATURES[f][0] for f in used), key=version_key)
    allowed_old = [f for f in used if requirement_problem(flow.requires, version=NEWER_FEATURES[f][1]) is None]
    if not allowed_old:
        return None
    by_version = {}
    for feature in allowed_old:
        by_version.setdefault(NEWER_FEATURES[feature][1], []).append(NEWER_FEATURES[feature][2])
    effects = "; ".join(f"Kinenix {old} and older {' and '.join(what)}" for old, what in by_version.items())
    fix = "Add" if not flow.requires else "Raise"
    return (f"The flow uses {', '.join(allowed_old)}, which older workers would run wrongly: {effects}. "
            f"{fix} `> Requires: kinenix>={needed}` under the title, so older workers refuse the flow instead.")


def _placeholders(value: Any) -> Iterable[str]:
    """The text inside every ${...} of a parameter value, at any depth."""
    if isinstance(value, str):
        for match in VariableEvaluator.PATTERN.finditer(value):
            yield match.group(1).strip()
    elif isinstance(value, dict):
        for item in value.values():
            yield from _placeholders(item)
    elif isinstance(value, list):
        for item in value:
            yield from _placeholders(item)


def _expression_problems(step: Step, where: str) -> List[str]:
    """Expressions that cannot be read, or that call a function that does not exist (docs/design/expressions.md)."""
    found = []
    for text in _placeholders([step.parameters, step.condition]):
        problem = expressions.problem(text)
        if problem and problem not in found:
            found.append(problem)
    line = f", line {step.line}" if step.line else ""
    return [f"{where}{line}: {problem}" for problem in found]


# Actions the interpreter runs itself, before it reads error_handler: these keys have no effect on them (#168)
NO_ERROR_HANDLER = {
    "logic.if": "Put them on the steps under Sub-steps and Else-steps that may fail.",
    "logic.loop": "Put them on the sub-steps that may fail; on_error: next_item there goes on with the next item.",
    "flow.return": "Delete them; flow.return only ends the flow.",
}


def _ignored_error_handler(step: Step) -> Optional[str]:
    hint = NO_ERROR_HANDLER.get(step.action)
    keys = step.error_handler.model_dump(exclude_defaults=True) if step.error_handler else None
    if not hint or not keys:
        return None
    return f"{', '.join(keys)} has no effect on {step.action}. {hint}"


def validate_flow(flow: FlowDefinition) -> List[str]:
    """Return human-readable problems found in the flow; an empty list means none."""
    issues: List[str] = []
    known_actions = ActionRegistry.list_actions()

    problem = requirement_problem(flow.requires)
    if problem:
        issues.append(problem)
    newer = _version_problem(flow)
    if newer:
        issues.append(newer)

    for step in _outside_loops(_all_steps(flow)):
        if _on_error(step) == "next_item":
            issues.append(f"Step '{step.id}' ({step.name}): on_error next_item is for steps inside a logic.loop; "
                          f"here it would stop the flow like fail. In a subflow called for each item, set "
                          f"on_error: next_item on the flow.call step of the loop instead.")

    for step in _walk(_all_steps(flow)):
        where = f"Step '{step.id}' ({step.name})"
        issues.extend(_expression_problems(step, where))
        for condition in (step.condition, step.parameters.get("condition") if step.action == "logic.if" else None):
            problem = grouping_problem(condition)
            if problem:
                issues.append(f"{where}{f', line {step.line}' if step.line else ''}: {problem}")
        ignored = _ignored_error_handler(step)
        if ignored:
            issues.append(f"{where}{f', line {step.line}' if step.line else ''}: {ignored}")
        on_error = step.error_handler.on_error if step.error_handler else None
        if on_error is not None and str(on_error).strip().lower() not in ON_ERROR_VALUES:
            issues.append(f"{where}: on_error '{on_error}' is not one of {', '.join(ON_ERROR_VALUES)}; "
                          f"it would stop the flow like fail.")
        action_cls = known_actions.get(step.action)
        if action_cls is None:
            close = difflib.get_close_matches(step.action, known_actions, n=1)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            issues.append(f"{where}: unknown action '{step.action}'.{hint}")
            continue

        accepted = action_cls.accepted_parameters
        if accepted is None:
            continue
        # logic.if reads 'condition' as a parameter, so step-level hints apply only to keys it does not accept
        for key in step.parameters:
            if key in accepted:
                continue
            if key in STEP_LEVEL_KEYS:
                issues.append(
                    f"{where}: '{key}' is in parameters, where {step.action} ignores it; "
                    f"it belongs in {STEP_LEVEL_KEYS[key]}. Write it in flow.md and recompile."
                )
                continue
            close = difflib.get_close_matches(key, accepted, n=1)
            hint = f" Did you mean '{close[0]}'?" if close else f" Accepted: {', '.join(accepted) or 'none'}."
            issues.append(f"{where}: {step.action} does not use parameter '{key}'; it would be ignored.{hint}")
    return issues


class _BundleVariables:
    """Just enough of an ExecutionContext for resolving flow.call targets without running anything."""

    def __init__(self, flow_dir: Path, flow_file_dir: Path):
        self._values = {"__flow_dir__": str(flow_dir), "__flow_file_dir__": str(flow_file_dir)}

    def get_variable(self, name: str):
        return self._values.get(name)


def validate_subflows(flow: FlowDefinition, flow_dir: Path, flow_file_dir: Optional[Path] = None,
                      _seen: Optional[Set[Path]] = None) -> List[str]:
    """
    Follows every flow.call whose target is a fixed path, and reports problems in the subflows:
    files that cannot be found, the subflow's own problems (including lines a .md subflow ignores),
    and `inputs` the subflow does not declare in its ## Variables. Targets built from ${...} are skipped.
    """
    from .interpreter import is_shared_subflow, load_subflow, resolve_subflow_path
    from .markdown import markdown_issues

    issues: List[str] = []
    seen = _seen if _seen is not None else set()
    flow_file_dir = flow_file_dir or flow_dir
    for step in _walk(_all_steps(flow)):
        if step.action != "flow.call":
            continue
        target = step.parameters.get("flow")
        where = f"Step '{step.id}' ({step.name})"
        if not isinstance(target, str) or "${" in target:
            continue
        try:
            path = resolve_subflow_path(target, _BundleVariables(flow_dir, flow_file_dir))
        except FileNotFoundError:
            issues.append(f"{where}: subflow '{target}' was not found.")
            continue
        try:
            child = load_subflow(path)
        except Exception as exc:
            issues.append(f"{where}: subflow '{target}' could not be read: {exc}")
            continue

        inputs = step.parameters.get("inputs")
        if isinstance(inputs, dict):
            declared = set(child.variables)
            for key in inputs:
                if key == "config" or key in declared:
                    continue
                close = difflib.get_close_matches(key, declared, n=1)
                hint = (f" Did you mean '{close[0]}'?" if close
                        else f" It declares: {', '.join(sorted(declared)) or 'nothing'}.")
                issues.append(f"{where}: input '{key}' is not declared in the ## Variables of subflow '{target}'.{hint}")

        if path in seen:
            continue  # each subflow is checked once, also when flows call each other in a loop
        seen.add(path)
        prefix = f"Subflow '{target}': "
        if path.suffix.lower() == ".md":
            issues.extend(prefix + issue for issue in markdown_issues(path.read_text(encoding="utf-8-sig")))
        issues.extend(prefix + issue for issue in validate_flow(child))
        shared = is_shared_subflow(target, path, _BundleVariables(flow_dir, flow_file_dir))
        child_dir = path.parent if shared else flow_dir
        issues.extend(validate_subflows(child, child_dir, path.parent, seen))
    return issues
