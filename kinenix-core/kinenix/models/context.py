from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def local_now() -> datetime:
    """Current local time with its UTC offset, so receivers such as the Hub can convert it to UTC."""
    return datetime.now().astimezone()


class StepResult(BaseModel):
    step_id: str = Field(..., description="Unique step identifier")
    step_name: str = Field(..., description="Step name")
    action: Optional[str] = Field(default=None, description="Action executed by this step")
    status: str = Field(..., description="Execution status: success, failed, skipped")
    start_time: datetime = Field(..., description="Timestamp when step started")
    end_time: datetime = Field(..., description="Timestamp when step finished")
    duration_seconds: float = Field(..., description="Execution duration in seconds")
    section: str = Field(default="steps", description="Section of flow.md the step is in: steps, on_error, or finally")
    output: Optional[Any] = Field(default=None, description="Output payload returned by the action")
    error_message: Optional[str] = Field(default=None, description="Error message if step failed")
    error_type: Optional[str] = Field(default=None, description="Error classification: Technical or Business")
    line: Optional[int] = Field(default=None, description="Line of the step heading in its flow.md")
    path: Optional[str] = Field(default=None, description="Flow > loop or condition > subflow > step, for finding the step")
    subflow: Optional[str] = Field(default=None, description="Name of the subflow the step ran in, or empty")
    loop: Optional[Dict[str, Any]] = Field(default=None, description="Innermost loop item: index (from 1), of, item")
    retries: int = Field(default=0, description="Retries made before the step succeeded or failed")
    failure: Optional[Dict[str, Any]] = Field(
        default=None,
        description="For a failed step: exception, root_cause, suggested_fix, screenshot, handled "
                    "(stopped, continued, fallback, next_item), from_subflow (the failure is the subflow step's, recorded there)")


class ExecutionMetrics(BaseModel):
    total_steps: int = Field(default=0, description="Total number of steps evaluated")
    successful_steps: int = Field(default=0, description="Number of successfully executed steps")
    failed_steps: int = Field(default=0, description="Number of failed steps")
    skipped_steps: int = Field(default=0, description="Number of skipped steps")
    total_duration_seconds: float = Field(default=0.0, description="Total flow run duration in seconds")
    hours_saved: float = Field(default=0.0, description="Estimated manual labour hours saved")
    cost_saved: float = Field(default=0.0, description="Estimated operational cost saved")


def is_ignored(result: "StepResult") -> bool:
    """A failed step with on_error: ignore: recorded, but not counted as a failure (#197)."""
    return result.status == "failed" and (result.failure or {}).get("handled") == "ignored"


def counts_as_failed(result: "StepResult") -> bool:
    return result.status == "failed" and not is_ignored(result)


class FailureDetails(BaseModel):
    failed_step_id: str = Field(..., description="ID of the step that triggered the failure")
    failed_step_name: str = Field(..., description="Human-readable name of the failed step")
    action: str = Field(..., description="Action that failed (e.g. web.click, excel.read)")
    error_type: str = Field(default="Technical", description="Classification: Technical or Business exception")
    exception_class: str = Field(..., description="Python exception class name (e.g. FileNotFoundError, TimeoutError)")
    error_message: str = Field(..., description="Original error message")
    root_cause: str = Field(..., description="Direct summary of the root cause for AI and human diagnosis")
    suggested_fix: str = Field(..., description="Actionable recommendation to resolve the failure")
    error_screenshot_path: Optional[str] = Field(default=None, description="Path to screenshot captured at moment of failure if browser was active")
    section: str = Field(default="steps", description="Section of flow.md the failed step is in: steps, on_error, or finally")


class ExecutionContext(BaseModel):
    flow_name: str = Field(..., description="Name of the executed workflow")
    run_id: Optional[str] = Field(default=None, description="Id of the run (${run.id}), shared with its subflows")
    kinenix_version: Optional[str] = Field(default=None, description="Kinenix version that ran the flow")
    items: Optional[Dict[str, int]] = Field(
        default=None, description="Work items: iterations of loops with item_label (total, done, failed)")
    start_time: datetime = Field(default_factory=local_now, description="Workflow start timestamp")
    variables: Dict[str, Any] = Field(default_factory=dict, description="In-memory variables captured during execution")
    step_results: List[StepResult] = Field(default_factory=list, description="Detailed per-step execution log")
    metrics: ExecutionMetrics = Field(default_factory=ExecutionMetrics, description="Aggregated run metrics and telemetry")
    is_completed: bool = Field(default=False, description="Whether the workflow completed all steps successfully")
    has_error: bool = Field(default=False, description="Whether an unhandled error occurred during execution")
    interrupted: bool = Field(default=False, description="Whether the run was stopped on request before its steps ended")
    failure_details: Optional[FailureDetails] = Field(default=None, description="Structured root-cause diagnosis if has_error is true")

    @property
    def is_partial(self) -> bool:
        """
        The run finished, but work items or steps failed on the way (handled by on_error: continue or next_item).
        Same rule as run_status in kinenix-hub (services/run_records.py), so the exit code and the Hub agree.
        """
        if self.has_error or self.interrupted:
            return False
        return (self.items or {}).get("failed", 0) > 0 or any(counts_as_failed(r) for r in self.step_results)

    def set_variable(self, name: str, value: Any) -> None:
        self.variables[name] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)
