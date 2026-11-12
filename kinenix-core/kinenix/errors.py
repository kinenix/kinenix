"""Errors that several parts of Kinenix raise, kept apart so that importing them creates no cycle."""


class FlowStructureError(ValueError):
    """The flow is built wrongly, such as logic.break outside a loop; exit code 4, like an invalid flow."""
