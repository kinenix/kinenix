import time
from typing import Any, Dict

from .base import BaseAction
from ..engine import stopping
from .registry import register_action
from ..models.context import ExecutionContext


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
    """Loop iteration action. Handled with sub_steps by FlowInterpreter."""
    accepted_parameters = ('items', 'item_var', 'item_label')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        return {"action": "logic.loop"}


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

