"""Exit codes of the kinenix, kinenix hub, and kinenix-worker commands (stable for all of 1.x).

A scheduler, a CI job, or an AI agent can tell from the code alone whether to try again later (1, 6), whether
a person must look at the data (3), the failed items (8), or the flow (4), or whether Kinenix must be upgraded (5).
Design: docs/design/agent-interface.md, section 4. Reference: docs/cli_guide.md, Exit codes.
"""
from typing import Any

OK = 0             # Success: nothing failed
TECHNICAL = 1      # The run failed for a technical reason: timeout, element not found, file locked
USAGE = 2          # Wrong use of the command: unknown option, missing argument, bad --vars (argparse also uses 2)
BUSINESS = 3       # The run stopped on a business rule (flow.fail): the data did not pass
INVALID_FLOW = 4   # The flow is invalid: kinenix validate problems, an expression error, an unknown action
NEWER_KINENIX = 5  # The flow needs a newer Kinenix (> Requires:)
UNREACHABLE = 6    # The Hub or another service cannot be reached, or refused the key
NOT_FOUND = 7      # No such flow, run, execution, file, table, or view
PARTIAL = 8        # The run finished, but items or steps failed on the way (on_error continue or next_item)
INTERRUPTED = 130  # Stopped on request: Ctrl+C or SIGTERM

# Failures that mean the flow itself must be fixed, wherever they are raised during a run
_INVALID_FLOW_EXCEPTIONS = {"ExpressionError", "ExpressionSyntaxError", "ConditionError", "FlowStructureError"}


def for_run(context: Any) -> int:
    """The exit code of a finished run, from its ExecutionContext."""
    if getattr(context, "interrupted", False):
        return INTERRUPTED
    if not getattr(context, "has_error", False):
        return PARTIAL if getattr(context, "is_partial", False) else OK
    details = getattr(context, "failure_details", None)
    if details is None or details.section == "finally":
        # The steps passed and only the clean-up failed: the data and the flow are fine, try again
        return TECHNICAL
    if details.action == "flow.requires":
        return NEWER_KINENIX
    if details.error_type == "Business":
        return BUSINESS
    message = details.error_message or ""
    if details.exception_class in _INVALID_FLOW_EXCEPTIONS or (
            details.exception_class == "KeyError" and "is not registered in ActionRegistry" in message):
        return INVALID_FLOW
    return TECHNICAL
