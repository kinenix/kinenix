import time
from typing import Any, Dict

from .base import BaseAction
from ..engine import stopping
from .registry import register_action
from ..models.context import ExecutionContext
from ..errors import FlowStructureError


@register_action("logic.set_variable")
class SetVariableAction(BaseAction):
    accepted_parameters = ('name', 'value')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        name = parameters.get("name")
        value = parameters.get("value")
        if name:
            context.set_variable(name, value)
        return value


@register_action("logic.delay")
class DelayAction(BaseAction):
    accepted_parameters = ('seconds',)
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        seconds = float(parameters.get("seconds", 1.0))
        if (context.get_variable("__section__") or "steps") == "steps":
            if stopping.wait(seconds):
                raise stopping.RunStopped()  # The delay did not end, so the run is not finished, even on the last step
        else:
            time.sleep(seconds)
        return {"delayed_seconds": seconds}


@register_action("logic.if")
class IfAction(BaseAction):
    """Conditional branching action. Handled with sub_steps by FlowInterpreter."""
    accepted_parameters = ('condition', 'left', 'operator', 'right')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        return {"action": "logic.if"}


@register_action("logic.loop")
class LoopAction(BaseAction):
    """Loop iteration action: over `items`, or `times` iterations. Handled with sub_steps by FlowInterpreter."""
    accepted_parameters = ('items', 'times', 'item_var', 'item_label')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        return {"action": "logic.loop"}


@register_action("logic.break")
class BreakAction(BaseAction):
    """
    Leaves the innermost logic.loop (docs/design/loop-control.md). Inside a loop FlowInterpreter handles it
    and never calls this; reaching execute means the step is outside any loop of its flow.
    """
    accepted_parameters = ()
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        raise FlowStructureError("logic.break is outside a logic.loop; it can only leave a loop of its own flow, "
                                 "not the loop of a flow that called this one.")


@register_action("logic.next")
class NextAction(BaseAction):
    """
    Skips the rest of this iteration of the innermost logic.loop, which counts as done (docs/design/loop-control.md).
    Inside a loop FlowInterpreter handles it; reaching execute means the step is outside any loop of its flow.
    """
    accepted_parameters = ()
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        raise FlowStructureError("logic.next is outside a logic.loop; it can only skip to the next item of a loop "
                                 "of its own flow, not of a flow that called this one.")


@register_action("logic.append")
class AppendAction(BaseAction):
    """Appends an item to a list or datatable in context variables."""
    accepted_parameters = ('target', 'var_name', 'list_var', 'item', 'extend')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        target = parameters.get("target") or parameters.get("var_name") or parameters.get("list_var")
        item = parameters.get("item")
        if not target:
            raise ValueError("logic.append requires 'target' parameter specifying variable name")

        current = context.get_variable(target)
        if current is None:
            current = []
            context.set_variable(target, current)
        elif not isinstance(current, list):
            raise TypeError(f"Target variable '{target}' must be a list, got {type(current).__name__}")

        # extend: true adds each element of a list item (e.g. the rows from web.get_table) instead of the list itself
        if parameters.get("extend"):
            if not isinstance(item, list):
                raise TypeError(f"logic.append with 'extend' requires a list item, got {type(item).__name__}")
            current.extend(item)
            return {"target": target, "total_items": len(current), "appended_count": len(item)}

        current.append(item)
        return {"target": target, "total_items": len(current), "appended": item}

