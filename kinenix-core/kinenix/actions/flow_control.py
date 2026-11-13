from typing import Any, Dict
from .base import BaseAction
from .registry import register_action
from ..models.context import ExecutionContext


class SubflowExecutionError(RuntimeError):
    """Raised when a child subflow execution fails with an unhandled error."""
    def __init__(self, message: str, subflow_name: str = "", failed_step_id: str = "", child_context: Any = None):
        super().__init__(message)
        self.subflow_name = subflow_name
        self.failed_step_id = failed_step_id
        self.child_context = child_context
        # Keeps the child's error type, so a business error inside a subflow stays Business in the parent
        details = getattr(child_context, "failure_details", None)
        self.error_type = getattr(details, "error_type", None)


class BusinessRuleError(RuntimeError):
    """A business exception: the data or situation breaks a rule. Recorded as error type Business and never retried."""


class FlowFailedError(RuntimeError):
    """A technical failure raised on purpose by flow.fail with category 'technical'."""


# What other RPA tools call a System or Application Exception is a technical error in Kinenix (docs/logging.md)
CATEGORY_ALIASES = {"business": "business", "technical": "technical", "system": "technical"}


def error_category(value: Any, default: str, where: str) -> str:
    """'business' or 'technical' from a category parameter; 'system' is accepted for 'technical'."""
    text = str(value if value not in (None, "") else default).strip().lower()
    if text not in CATEGORY_ALIASES:
        raise ValueError(f"{where} must be business or technical (system means technical), not '{value}'.")
    return CATEGORY_ALIASES[text]


def is_business_error(exc: BaseException) -> bool:
    """
    Business exceptions are recognized by class name, so actions can define their own *Business* errors,
    or by an error_type of "Business" carried over from a subflow.
    """
    return "Business" in type(exc).__name__ or getattr(exc, "error_type", None) == "Business"


@register_action("flow.fail")
class FlowFailAction(BaseAction):
    """
    Stops the flow with a clear message, typically under a condition, for example when expected data is missing.
    Parameters:
      - message: Text recorded as the error message and shown to whoever handles the failure.
      - category: 'business' (default, not retried) or 'technical' ('system' is accepted for 'technical').
    """
    accepted_parameters = ('message', 'category')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        message = str(parameters.get("message") or "Flow stopped by flow.fail")
        if error_category(parameters.get("category"), "business", "flow.fail: category") == "business":
            raise BusinessRuleError(message)
        raise FlowFailedError(message)


@register_action("flow.call")
class FlowCallAction(BaseAction):
    """
    Executes an external child flow (subflow) within an isolated context.
    Main execution logic is handled by FlowInterpreter._handle_flow_call_step.
    """
    accepted_parameters = ('flow', 'inputs', 'outputs', 'propagate_sessions', 'inherit_config')
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        return {"action": "flow.call"}


@register_action("flow.return")
class FlowReturnAction(BaseAction):
    """
    Outputs a structured return payload from a subflow and triggers early exit.
    Parameters:
      - value: Payload (dict, list, string, number, or primitive) to return to caller.
    """
    accepted_parameters = ('value',)
    side_effects = ('none',)

    def execute(self, parameters: Dict[str, Any], context: ExecutionContext) -> Any:
        value = parameters.get("value")
        context.set_variable("__return_value__", value)
        context.set_variable("__early_exit__", True)
        return {"returned": value}
