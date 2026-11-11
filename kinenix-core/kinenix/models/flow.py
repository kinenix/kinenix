from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class VariableDefinition(BaseModel):
    name: str
    value: Any
    description: Optional[str] = None


class ErrorHandlerConfig(BaseModel):
    on_error: str = Field(default="stop", description="After the last attempt: fail (or stop, retry), continue, ignore, or next_item (in a loop)")
    max_retries: Union[int, str] = Field(default=0, description="Retry attempts before on_error decides; a number or ${...}")
    retry_interval: Union[float, str] = Field(default=1.0, description="Seconds to wait between attempts; a number or ${...}")
    fallback_step_id: Optional[str] = Field(default=None, description="Step ID to jump to upon error")
    error_message: Optional[str] = Field(default=None, description="Message of the step's failure instead of the action's; may use ${error.message}")


class Step(BaseModel):
    id: str = Field(..., description="Unique step identifier (e.g. step_1, sub_check_programmer)")
    name: str = Field(..., description="Human-readable name describing what this step does")
    description: Optional[str] = Field(default=None, description="Optional detailed business intent or technical explanation")
    action: str = Field(..., description="Action identifier (e.g. web.open, web.click, web.type, web.get_text, web.screenshot, web.close, excel.read, excel.write, logic.if, logic.loop, logic.append, logic.set_variable, logic.delay, flow.call, flow.return, email.send, http.request)")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Key-value parameters passed to the action")
    output_var: Optional[str] = Field(default=None, description="Variable name to store the return value in context")
    sub_steps: Optional[List["Step"]] = Field(default=None, description="Child steps for logic.loop or when logic.if evaluates to true")
    else_steps: Optional[List["Step"]] = Field(default=None, description="Child steps executed when logic.if evaluates to false")
    error_handler: Optional[ErrorHandlerConfig] = Field(default=None, description="Step-level error handling strategy")
    condition: Optional[str] = Field(default=None, description="Optional execution condition expression (e.g. '${row.Status} == Active')")
    line: Optional[int] = Field(default=None, exclude=True,
                                description="Line of the step heading in its flow.md, for error reports; not part of the compiled form")


Step.model_rebuild()


class ActionConfig(BaseModel):
    name: str = Field(..., description="Registered action name")
    action_class: str = Field(..., description="Python class implementing the action")
    module: str = Field(..., description="Python module path containing the action")
    description: Optional[str] = Field(default=None, description="Action documentation")


class FlowDefinition(BaseModel):
    name: str = Field(..., description="Name of the RPA automation flow")
    description: Optional[str] = Field(default=None, description="High-level description of business purpose and scope")
    version: str = Field(default="1.0.0", description="Semantic version of the flow definition")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Initial context variables accessible via ${var_name}")
    requires: Optional[str] = Field(default=None, description="Kinenix version the flow needs, e.g. kinenix>=0.2.0b4")
    steps: List[Step] = Field(default_factory=list, description="Sequential steps to execute")
    on_error_steps: Optional[List[Step]] = Field(default=None, description="Steps of ## On Error: run once when Steps fail")
    finally_steps: Optional[List[Step]] = Field(default=None, description="Steps of ## Finally: run after Steps and On Error, always")
