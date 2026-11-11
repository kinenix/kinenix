import json
import os
import secrets
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .conditions import (ConditionError, compare_order, grouping_problem, is_order_operator, parse_boolean,
                         resolve_condition, values_equal)
from .evaluator import VariableEvaluator
from .logger import ExecutionLogger
from .markdown import JSON_FLOW_NOT_RUN, SECTION_HEADINGS, markdown_to_flow
from .redaction import NOT_SECRET_ENV, Redactor
from .web_errors import explain as explain_web_error
from .requires import requirement_problem
from .stopping import RunStopped, stop_requested
from .stopping import wait as wait_or_stop
from .. import __version__
from ..actions.registry import ActionRegistry
from ..envfile import read_env_file
from ..actions.flow_control import SubflowExecutionError, is_business_error
from ..models.context import ExecutionContext, StepResult, FailureDetails, local_now
from ..models.flow import FlowDefinition, Step


def _flow_file(path: Path) -> Optional[Path]:
    """The flow file at path, or path + .md."""
    if path.is_file():
        return path.resolve()
    candidate = path.with_name(path.name + ".md")
    if candidate.is_file():
        return candidate.resolve()
    return None


def load_subflow(path: Path) -> FlowDefinition:
    """Subflows are flow.md files, compiled in memory on every call; JSON flows are not read."""
    if path.suffix.lower() == ".json":
        raise ValueError(JSON_FLOW_NOT_RUN.format(path=path))
    return markdown_to_flow(path.read_text(encoding="utf-8-sig"))


def is_shared_subflow(flow_target: Any, resolved_path: Path, context: Any) -> bool:
    """@shared/ components, and flow files outside the caller's bundle, keep their own folder and config."""
    if str(flow_target).strip().startswith("@shared/"):
        return True
    bundle_dir = context.get_variable("__flow_dir__") if context is not None else None
    if not bundle_dir:
        return True
    bundle = Path(bundle_dir).resolve()
    return bundle != resolved_path.parent and bundle not in resolved_path.parents


def new_run_id(started: datetime) -> str:
    """Sortable and readable, e.g. 20261014T054855-qhzk. The T and the letters keep runs of digits short,
    so redaction never takes an id for a card or phone number (it did: 20261014-054855-43ac became [card]ac)."""
    return f"{started:%Y%m%dT%H%M%S}-{''.join(secrets.choice(string.ascii_lowercase) for _ in range(4))}"


def _is_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


def resolve_subflow_path(flow_target: str, context: Any) -> Path:
    """Finds the file of a flow.call target; context only needs get_variable (used by validation too)."""
    target_str = str(flow_target).strip()

    # 1. Namespace @shared/
    if target_str.startswith("@shared/"):
        rel_shared = target_str[8:]
        flow_dir_str = context.get_variable("__flow_dir__")
        candidates = []
        if flow_dir_str:
            p = Path(flow_dir_str).resolve()
            for parent in [p] + list(p.parents):
                candidates.append(parent / "flows" / "@shared" / rel_shared)
                candidates.append(parent / "@shared" / rel_shared)
        candidates.append(Path.cwd() / "flows" / "@shared" / rel_shared)
        candidates.append(Path.home() / ".kinenix" / "flows" / "@shared" / rel_shared)
        for c in candidates:
            found = _flow_file(c)
            if found:
                return found

    # 2. Relative to the bundle folder, then to the folder of the calling flow file
    #    (a subflow that calls a sibling file by a path relative to itself)
    for base_var in ("__flow_dir__", "__flow_file_dir__"):
        base_str = context.get_variable(base_var)
        if base_str:
            found = _flow_file((Path(base_str) / target_str).resolve())
            if found:
                return found

    # A path written relative to the bundle (./subflows/x.md) means that file only. Looking further, in the
    # current folder or among the flows by name, could run another flow that happens to share the name
    # (docs/design/threat-model.md, T1)
    has_bundle = context.get_variable("__flow_dir__") or context.get_variable("__flow_file_dir__")
    if has_bundle and target_str.startswith(("./", "../", ".\\", "..\\")):
        raise FileNotFoundError(f"Subflow file not found: '{flow_target}' (relative to the bundle folder)")

    # 3. Direct path or relative to current working directory
    found = _flow_file(Path(target_str).resolve())
    if found:
        return found

    # 4. Fallback to CLI search
    try:
        from ..cli import resolve_flow_path
        resolved = resolve_flow_path(target_str)
        if resolved and resolved.is_file():
            return resolved.resolve()
    except Exception:  # nosec B110: not found by name either; the caller reports the subflow as missing
        pass

    raise FileNotFoundError(f"Subflow file not found: '{flow_target}'")


class _NextItem(Exception):
    """on_error: next_item (#102): the failure is recorded, and the innermost logic.loop goes on with its next item."""


class FlowInterpreter:
    """
    Interpreter that parses FlowDefinition, evaluates expressions, and executes steps sequentially.
    Supports modular subflow execution (flow.call), early exit (flow.return), and hierarchical logging.
    """

    def __init__(
        self,
        logger: Optional[ExecutionLogger] = None,
        max_depth: int = 10,
        call_stack: Optional[List[str]] = None,
        auto_close_browser: bool = True
    ):
        self.logger = logger or ExecutionLogger()
        self.max_depth = max_depth
        self.finishing = False  # A subflow called from On Error or Finally runs to its end
        self.call_stack: List[str] = call_stack or []
        self.auto_close_browser = auto_close_browser
        self._step_map: Dict[str, Step] = {}

    def _build_step_map(self, steps: List[Step]) -> Dict[str, Step]:
        step_map: Dict[str, Step] = {}
        for s in steps:
            step_map[s.id] = s
            if s.sub_steps:
                step_map.update(self._build_step_map(s.sub_steps))
            if s.else_steps:
                step_map.update(self._build_step_map(s.else_steps))
        return step_map

    def _cleanup_resources(self, context: ExecutionContext) -> None:
        """
        Safely closes external resources (Playwright browser, driver instances)
        to prevent zombie / orphan processes upon flow completion or failure.
        Only executed at the root flow level (not inside subflows sharing parent resources).
        """
        if self.call_stack or context.get_variable("__shared_browser__"):
            return

        if not self.auto_close_browser:
            return
        self._close_browser(context)

    _BROWSER_KEYS = ("__playwright_pw__", "__playwright_browser__", "__playwright_page__")

    def _take_browser_back(self, context: ExecutionContext, child_context: ExecutionContext, shared: bool) -> None:
        """
        After a subflow (#58). A shared browser comes back as the subflow left it: the page it went to or
        switched to (so screenshots and later steps see the right page), a browser it opened (so the run
        closes it at the end), or nothing when it closed the browser. A subflow that does not share the
        browser closes any browser it opened itself, so no browser process is left behind.
        """
        if shared:
            for key in self._BROWSER_KEYS:
                context.set_variable(key, child_context.get_variable(key))
        elif self.auto_close_browser:
            borrowed = child_context.get_variable("__playwright_pw__") is context.get_variable("__playwright_pw__")
            self._close_browser(child_context, stop_playwright=not borrowed)

    def _close_browser(self, context: ExecutionContext, stop_playwright: bool = True) -> None:
        """Closes the browser and stops Playwright (unless it belongs to the caller), if this context holds them."""
        browser = context.get_variable("__playwright_browser__")
        pw = context.get_variable("__playwright_pw__")

        if browser:
            try:
                is_connected = getattr(browser, "is_connected", None)
                if is_connected is None or (callable(is_connected) and is_connected()):
                    browser.close()
                    self.logger.logger.info("Auto-cleanup: Closed active Playwright browser.")
            except Exception as e:
                self.logger.logger.debug(f"Auto-cleanup: Error closing browser: {e}")
            finally:
                context.set_variable("__playwright_browser__", None)
                context.set_variable("__playwright_page__", None)

        if pw and stop_playwright:
            try:
                pw.stop()
                self.logger.logger.info("Auto-cleanup: Stopped Playwright instance.")
            except Exception as e:
                self.logger.logger.debug(f"Auto-cleanup: Error stopping Playwright: {e}")
            finally:
                context.set_variable("__playwright_pw__", None)

    def _try_capture_failure_screenshot(self, step: Step, context: ExecutionContext) -> Optional[str]:
        try:
            page = context.get_variable("__playwright_page__")
            if page and hasattr(page, "screenshot"):
                is_closed = getattr(page, "is_closed", lambda: False)
                if callable(is_closed) and is_closed():
                    return None

                config_data = context.get_variable("config") or {}
                error_dir_str = config_data.get("error_dir") or config_data.get("error_screenshot_dir")
                if isinstance(error_dir_str, str):
                    error_dir_str = VariableEvaluator.evaluate_value(error_dir_str, context.variables)

                flow_dir_str = context.get_variable("__flow_dir__")
                base_dir = Path(flow_dir_str) if flow_dir_str else Path.cwd()

                if error_dir_str:
                    err_dir = Path(error_dir_str)
                    if not err_dir.is_absolute():
                        err_dir = (base_dir / error_dir_str).resolve()
                else:
                    err_dir = (base_dir / "output" / "errors").resolve()

                err_dir.mkdir(parents=True, exist_ok=True)
                timestamp_str = local_now().strftime("%Y%m%d_%H%M%S")
                clean_step_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in step.id)
                shot_path = err_dir / f"error_{clean_step_id}_{timestamp_str}.png"

                page.screenshot(path=str(shot_path), full_page=True)
                shot_path_str = str(shot_path.resolve())
                context.set_variable("__last_error_screenshot__", shot_path_str)
                self.logger.logger.warning(f"Auto-captured failure screenshot: {shot_path_str}")
                return shot_path_str
        except Exception as snap_err:
            self.logger.logger.debug(f"Failed to auto-capture failure screenshot: {str(snap_err)}")
        return None

    def _diagnose_failure(self, step: Step, exc: Exception, context: Optional[ExecutionContext] = None) -> FailureDetails:
        exc_class = type(exc).__name__
        err_msg = str(exc)
        error_type = "Business" if is_business_error(exc) else "Technical"

        error_screenshot_path = None
        child = getattr(exc, "child_context", None)
        if isinstance(exc, SubflowExecutionError) and child is not None:
            # The subflow took the screenshot when its step failed (#54)
            child_details = getattr(child, "failure_details", None)
            error_screenshot_path = getattr(child_details, "error_screenshot_path", None)
        elif context:
            error_screenshot_path = self._try_capture_failure_screenshot(step, context)

        if error_type == "Business" and not isinstance(exc, SubflowExecutionError):
            # flow.fail: the flow stopped on purpose; it is not a defect in the step
            root_cause = f"Business rule in step '{step.name}' was not met: {err_msg}"
            suggested_fix = "Check the input data of this item, or change the condition in flow.md if the rule itself is wrong."
        elif isinstance(exc, SubflowExecutionError):
            # The subflow's own diagnosis says what happened; repeat it with where (#111)
            child_details = getattr(child, "failure_details", None)
            if child_details is not None and child_details.root_cause:
                root_cause = (f"In subflow '{exc.subflow_name}', step '{child_details.failed_step_name}': "
                              f"{child_details.root_cause}")
                suggested_fix = child_details.suggested_fix or ""
            else:
                root_cause = f"Subflow execution failed in '{exc.subflow_name}': {err_msg}"
                suggested_fix = f"Inspect child subflow '{exc.subflow_name}' definition and input parameters passed in step '{step.id}'."
        elif explain_web_error(err_msg) is not None:
            # Known Playwright patterns: what blocked the click, what was not found, why the site failed (#111)
            root_cause, suggested_fix = explain_web_error(err_msg)
        elif isinstance(exc, FileNotFoundError) or ("not found" in err_msg.lower() and "file" in err_msg.lower()):
            root_cause = f"Required file was not found during execution of step '{step.name}'."
            suggested_fix = "Verify the target file path exists and that relative paths are correctly anchored to the flow project directory."
        elif "timeout" in err_msg.lower() or "waiting for" in err_msg.lower():
            root_cause = f"Operation timed out waiting for element or network response in step '{step.name}' (Action: {step.action})."
            suggested_fix = "Verify target web page/API is reachable, inspect selector validity, or increase action timeout parameter."
        elif "locator" in err_msg.lower() or "strict mode violation" in err_msg.lower() or "selector" in err_msg.lower():
            root_cause = f"Web element could not be uniquely located on page in step '{step.name}'."
            suggested_fix = "Check DOM changes on target page and update selector/label to be more resilient."
        elif isinstance(exc, KeyError):
            root_cause = f"Referenced variable or key {err_msg} is missing from execution context."
            suggested_fix = "Ensure preceding steps initialize this variable or verify variable expression spelling."
        else:
            root_cause = f"{exc_class} in step '{step.name}' ({step.action}): {err_msg}"
            suggested_fix = f"Inspect input parameters to step '{step.id}' ({step.action}) and verify prerequisite conditions."

        return FailureDetails(
            failed_step_id=step.id,
            failed_step_name=step.name,
            action=step.action,
            error_type=error_type,
            exception_class=exc_class,
            error_message=err_msg,
            root_cause=root_cause,
            suggested_fix=suggested_fix,
            error_screenshot_path=error_screenshot_path,
            section=(context.get_variable("__section__") if context else None) or "steps"
        )

    def run_flow(self, flow_def: FlowDefinition, initial_vars: Optional[Dict[str, Any]] = None) -> ExecutionContext:
        context = ExecutionContext(flow_name=flow_def.name)

        # One Redactor per top-level run, shared with its subflows through the logger; actions reach it
        # through the context to hide values they handle (docs/logging.md, Redaction)
        if not self.call_stack:
            self.logger.redactor = Redactor()
        redactor = self.logger.redactor
        context.set_variable("__redactor__", redactor)
        redactor.add_env_references(json.dumps(flow_def.model_dump(exclude_none=True), ensure_ascii=False, default=str))

        # A flow that needs a newer Kinenix is not run at all: this version could misread its sections
        problem = requirement_problem(flow_def.requires)
        if problem:
            context.has_error = True
            context.failure_details = FailureDetails(
                failed_step_id="flow_requires",
                failed_step_name="Kinenix version check",
                action="flow.requires",
                exception_class="VersionError",
                error_message=problem,
                root_cause=problem,
                suggested_fix="Upgrade Kinenix on this machine: pipx upgrade kinenix (or pip install -U kinenix)."
            )
            self.logger.logger.error(problem)
            context.variables.pop("__redactor__", None)
            self._finish(context)
            return context

        # 1. Flow definition default variables (base priority)
        if flow_def.variables:
            for k, v in flow_def.variables.items():
                context.set_variable(k, v)

        # 2. Set initial caller variables (e.g. __flow_dir__)
        if initial_vars:
            for k, v in initial_vars.items():
                context.set_variable(k, v)

        # 3. Auto-load project configuration (config.json & .env) from flow bundle directory
        # A subflow of the same bundle receives the caller's config instead of reading the files again
        flow_dir_str = context.get_variable("__flow_dir__")
        if flow_dir_str and not context.get_variable("__bundle_config_from_caller__"):
            self._load_bundle_configs(Path(flow_dir_str), context)

        # 4. Caller explicit initial_vars take highest priority. A `config` from the caller (a local
        # subflow's bundle config, inherit_config, or inputs) is merged over the loaded config, key by key
        if initial_vars:
            for k, v in initial_vars.items():
                if k == "config" and isinstance(v, dict):
                    self._apply_config_data(dict(v), context)
                else:
                    context.set_variable(k, v)
        redactor.configure(context.get_variable("config"))

        # ${run}: one id per top-level run, shared with subflows (for paths such as ./output/${run.id}/).
        # ${run.status} is running, then success, failed, or interrupted before Finally runs
        run_info = context.get_variable("run") if self.call_stack else None
        if not isinstance(run_info, dict) or not run_info.get("id"):
            started = local_now()
            # The CLI makes the id before the run, so `Run <id>` is the first line it prints
            run_id = (initial_vars or {}).get("__run_id__") if not self.call_stack else None
            run_info = {"id": run_id or new_run_id(started), "flow": flow_def.name,
                        "started": started.isoformat(timespec="seconds")}
        run_info = {**run_info, "status": "running"}
        if not self.call_stack:
            log_path = self.logger.start_run(context, run_info["id"])
            run_info["log_path"] = str(log_path) if log_path else ""
            context.set_variable("__items__", {"total": 0, "done": 0, "failed": 0})
        context.set_variable("run", run_info)
        context.run_id = run_info["id"]
        context.kinenix_version = __version__
        # Where a step is: flow > loop or if > subflow > ..., for ${error.path}
        if not isinstance(context.get_variable("__location__"), list):
            context.set_variable("__location__", [flow_def.name])
        context.set_variable("__section__", "steps")

        # Build step map and validate any fallback_step_id upfront
        all_steps = list(flow_def.steps) + list(flow_def.on_error_steps or []) + list(flow_def.finally_steps or [])
        self._step_map = self._build_step_map(all_steps)
        for s_id, s in self._step_map.items():
            if s.error_handler and s.error_handler.fallback_step_id:
                fb_target = s.error_handler.fallback_step_id
                if fb_target not in self._step_map:
                    raise ValueError(
                        f"Step '{s_id}' specifies fallback_step_id '{fb_target}' which does not exist in flow definition."
                    )
        from .validation import deprecated_uses  # imported here: validation imports every action module
        for notice in deprecated_uses(flow_def):
            self.logger.logger.warning(f"{flow_def.name}: {notice}")

        start_time = local_now()

        try:
            try:
                for step in flow_def.steps:
                    if context.get_variable("__early_exit__"):
                        break
                    self._execute_step(step, context)
                context.is_completed = True
            except RunStopped:
                # Not a failure, so On Error does not run; Finally does
                context.interrupted = True
                run_info["status"] = "interrupted"
                self.logger.logger.warning(f"{flow_def.name}: stopped on request; the remaining steps are skipped")
            except Exception as e:
                context.has_error = True
                self._flow_failed(e, context)
                run_info["status"] = "failed"
                self._run_section("on_error", flow_def.on_error_steps, context)
            if not context.has_error and not context.interrupted:
                run_info["status"] = "success"
            self._run_section("finally", flow_def.finally_steps, context)
            if context.has_error and not context.interrupted:
                run_info["status"] = "failed"
        finally:
            self._cleanup_resources(context)
            context.variables.pop("__redactor__", None)

        end_time = local_now()
        total_duration = (end_time - start_time).total_seconds()

        context.metrics.total_steps = len(context.step_results)
        context.metrics.successful_steps = sum(1 for r in context.step_results if r.status == "success")
        context.metrics.failed_steps = sum(1 for r in context.step_results if r.status == "failed")
        context.metrics.skipped_steps = sum(1 for r in context.step_results if r.status == "skipped")
        context.metrics.total_duration_seconds = total_duration
        items = context.get_variable("__items__")
        if not self.call_stack and isinstance(items, dict) and items.get("total"):
            context.items = dict(items)

        self._finish(context)
        return context

    def _finish(self, context: ExecutionContext) -> None:
        """The log file and Hub telemetry are written once per run, by the main flow; subflow steps are in it (#62)."""
        if not self.call_stack:
            self.logger.log_execution_summary(context)

    def _flow_failed(self, e: Exception, context: ExecutionContext) -> None:
        """Steps stopped with an exception: record the failure (if the step did not) and log it."""
        if context.failure_details is None:
            context.failure_details = FailureDetails(
                failed_step_id="flow_run",
                failed_step_name="Flow Execution",
                action="flow.run",
                error_type="Technical",
                exception_class=type(e).__name__,
                error_message=str(e),
                root_cause=f"Flow stopped: {str(e)}",
                suggested_fix="Inspect execution logs and subflow definitions.",
                section=context.get_variable("__section__") or "steps"
            )
        message = self.logger.redactor.redact_text(str(e))
        if self.call_stack:
            # The calling flow.call step decides what happens next (stop, continue, or fallback)
            self.logger.logger.error(f"Subflow '{context.flow_name}' stopped: {message}")
        else:
            self.logger.logger.error(f"Steps stopped: {message}")

    def _run_section(self, section: str, steps: Optional[List[Step]], context: ExecutionContext) -> None:
        """
        Runs ## On Error or ## Finally. A failing step is recorded and the rest of the section still runs;
        On Error never runs again because of it. A failure in Finally makes a successful run fail.
        """
        if not steps:
            return
        self.logger.logger.info(f"Running {SECTION_HEADINGS[section]} ({len(steps)} step{'' if len(steps) == 1 else 's'})")
        context.set_variable("__early_exit__", False)  # a flow.return in Steps does not skip Finally
        context.set_variable("__section__", section)
        try:
            for step in steps:
                if context.get_variable("__early_exit__"):
                    break
                try:
                    self._execute_step(step, context)
                except Exception as e:
                    if section == "finally" and not context.has_error:
                        context.has_error = True
                        context.is_completed = False
                        context.failure_details = context.get_variable("__last_failure__") or context.failure_details
                        if context.failure_details is None:
                            self._flow_failed(e, context)
        finally:
            context.set_variable("__section__", "steps")

    def _failure_count(self, context: ExecutionContext) -> int:
        """Failures recorded so far in this run, including those inside subflows."""
        return int(context.get_variable("__failures__") or 0)

    def _handler_number(self, value: Any, kind: type, name: str, step: Step, context: ExecutionContext) -> Any:
        """max_retries or retry_interval, which may be written as ${...}."""
        resolved = VariableEvaluator.evaluate_value(value, context.variables)
        try:
            return max(kind(0), kind(resolved))
        except (TypeError, ValueError):
            raise ValueError(f"Step '{step.id}' ({step.name}): {name} must be a number, not '{resolved}'.")

    def _record(self, context: ExecutionContext, result: StepResult, step: Step) -> None:
        result.section = context.get_variable("__section__") or "steps"
        location = context.get_variable("__location__") or [context.flow_name]
        loops = context.get_variable("__loops__") or []
        result.line = step.line
        result.path = " > ".join([str(part) for part in location] + [step.name])
        result.subflow = context.flow_name if context.get_variable("__is_subflow__") else None
        result.loop = dict(loops[-1]) if loops else None
        results = context.step_results
        results.append(result)
        self.logger.log_step_result(result)

    def _error_info(self, step: Step, exc: Exception, diag: FailureDetails, retries: int,
                    context: ExecutionContext) -> Dict[str, Any]:
        """The ${error} fields (docs/flow_markdown_spec.md), redacted."""
        child = getattr(exc, "child_context", None)
        if isinstance(exc, SubflowExecutionError) and child is not None:
            inner = child.get_variable("error")
            if isinstance(inner, dict):
                return inner  # the step that failed inside the subflow, with the path through it
        location = context.get_variable("__location__") or [context.flow_name]
        loops = context.get_variable("__loops__") or []
        info = {
            "message": str(exc),
            "type": diag.error_type,
            "exception": diag.exception_class,
            "step_id": step.id,
            "step_name": step.name,
            "action": step.action,
            "section": context.get_variable("__section__") or "steps",
            "path": " > ".join([str(part) for part in location] + [step.name]),
            "subflow": context.flow_name if context.get_variable("__is_subflow__") else "",
            "line": step.line,
            "loop": dict(loops[-1]) if loops else {},
            "retries": retries,
            "root_cause": diag.root_cause,
            "suggested_fix": diag.suggested_fix,
            "screenshot": diag.error_screenshot_path or "",
        }
        return self.logger.redactor.redact(info)

    def _item_label(self, template: Any, item_var: str, item: Any, context: ExecutionContext) -> str:
        """How a loop item is named in ${error.loop.item}: item_label, else its first three fields. Redacted."""
        shown = self.logger.redactor.redact(item)
        if template not in (None, ""):
            label = VariableEvaluator.evaluate_value(template, {**context.variables, item_var: shown})
        elif isinstance(shown, dict):
            values = [v for v in shown.values()
                      if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip()]
            label = " ".join(str(v) for v in values[:3])
        else:
            label = shown
        return str(label)[:200]

    def _stop_if_requested(self, context: ExecutionContext) -> None:
        """Ends ## Steps when a stop was requested. On Error and Finally, and what they call, run to their end."""
        if stop_requested() and not self.finishing and (context.get_variable("__section__") or "steps") == "steps":
            raise RunStopped()

    def _execute_step(self, step: Step, context: ExecutionContext) -> None:
        if context.get_variable("__early_exit__"):
            return
        self._stop_if_requested(context)

        self.logger.log_step_start(step.id, step.name, step.action)
        start_time = local_now()

        # For logic.if, `condition` chooses the branch (see _handle_if_step). As a step gate it would skip
        # the step, and Else-steps would never run
        if step.condition and step.action != "logic.if":
            if not self._condition_holds(step.condition, context.variables):
                result = StepResult(
                    step_id=step.id,
                    step_name=step.name,
                    action=step.action,
                    status="skipped",
                    start_time=start_time,
                    end_time=local_now(),
                    duration_seconds=0.0,
                    output={"skipped_reason": f"Condition '{step.condition}' not met"}
                )
                self._record(context, result, step)
                return

        # Parameters are evaluated only for a step that runs, so its condition can guard them (#145). A loop's
        # item_label names each item and is evaluated per item, once <item_var> and <item_var>_index exist
        params = step.parameters
        if step.action == "logic.loop":
            params = {k: v for k, v in params.items() if k != "item_label"}
        evaluated_params = VariableEvaluator.evaluate_value(params, context.variables)

        if step.action == "logic.loop":
            self._handle_loop_step(step, evaluated_params, context, start_time)
            return

        if step.action == "logic.if":
            self._handle_if_step(step, evaluated_params, context, start_time)
            return

        if step.action == "flow.return":
            self._handle_flow_return_step(step, evaluated_params, context, start_time)
            return

        def _invoke_step_action() -> Any:
            if step.action == "flow.call":
                self._handle_flow_call_step(step, evaluated_params, context, start_time, retries=attempt)
                return None
            action_cls = ActionRegistry.get(step.action)
            action_instance = action_cls()
            output = action_instance.execute(evaluated_params, context)
            if step.output_var:
                # Also when the action returned nothing: a loop must not keep the previous item's value (#159)
                context.set_variable(step.output_var, output)
            return output

        # max_retries always retries first; on_error then decides what happens after the last attempt (#52)
        handler = step.error_handler
        max_retries = self._handler_number(handler.max_retries, int, "max_retries", step, context) if handler else 0
        retry_interval = (self._handler_number(handler.retry_interval, float, "retry_interval", step, context)
                          if handler else 1.0)

        attempt = 0
        last_error = None
        results_before = len(context.step_results)
        failures_before = self._failure_count(context)
        while attempt <= max_retries:
            try:
                output = _invoke_step_action()
                if step.action == "flow.call":
                    return  # _handle_flow_call_step recorded the step with the subflow's result
                end_time = local_now()
                duration = (end_time - start_time).total_seconds()

                result = StepResult(
                    step_id=step.id,
                    step_name=step.name,
                    action=step.action,
                    status="success",
                    start_time=start_time,
                    end_time=end_time,
                    duration_seconds=duration,
                    output=output,
                    retries=attempt
                )
                self._record(context, result, step)
                return
            except Exception as e:
                # A stop also ends the browser, so what failed here is usually the stop, not the step
                self._stop_if_requested(context)
                last_error = e
                # Business errors (bad data, a rule not met) fail the same way on every attempt
                if attempt < max_retries and not is_business_error(e):
                    # Only the last attempt counts, as for any step: a subflow already added this one's steps (#167)
                    del context.step_results[results_before:]
                    context.set_variable("__failures__", failures_before)
                    attempt += 1
                    self.logger.logger.warning(
                        f"Step '{step.id}' ({step.name}) failed attempt {attempt}/{max_retries + 1}: "
                        f"{self.logger.redactor.redact_text(str(e))}. "
                        f"Retrying in {retry_interval}s..."
                    )
                    wait_or_stop(retry_interval)
                    self._stop_if_requested(context)
                else:
                    break

        if step.output_var:
            context.set_variable(step.output_var, None)  # A failed step has no result, not an earlier one (#159)

        end_time = local_now()
        duration = (end_time - start_time).total_seconds()
        failure_diag = self._diagnose_failure(step, last_error, context)
        context.set_variable("__last_failure__", failure_diag)
        # ${error} describes the failure in Steps; failures inside On Error and Finally do not replace it
        if (context.get_variable("__section__") or "steps") == "steps":
            context.set_variable("error", self._error_info(step, last_error, failure_diag, attempt, context))

        section = context.get_variable("__section__") or "steps"
        on_error = str(handler.on_error).strip().lower() if handler else ""
        if handler and handler.fallback_step_id:
            handled = "fallback"
        elif on_error == "next_item" and context.get_variable("__loop_depth__"):
            handled = "next_item"  # outside a loop, next_item stops the run like fail (kinenix validate says so)
        elif on_error == "continue" or section != "steps":
            handled = "continued"  # On Error and Finally go on with their next step
        else:
            handled = "stopped"
        # A failed subflow recorded its own failing step; this flow decides how it was handled
        child = getattr(last_error, "child_context", None)
        origin = child.get_variable("__stopping_result__") if isinstance(last_error, SubflowExecutionError) and child else None
        if isinstance(origin, StepResult) and origin.failure:
            origin.failure["handled"] = handled
        else:
            origin = None
            context.set_variable("__failures__", (context.get_variable("__failures__") or 0) + 1)

        result = StepResult(
            step_id=step.id,
            step_name=step.name,
            action=step.action,
            status="failed",
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            error_message=str(last_error),
            error_type=failure_diag.error_type,
            retries=attempt,
            failure={
                "exception": failure_diag.exception_class,
                "root_cause": failure_diag.root_cause,
                "suggested_fix": failure_diag.suggested_fix,
                "screenshot": failure_diag.error_screenshot_path or "",
                "handled": handled,
                "from_subflow": origin is not None,
            }
        )
        self._record(context, result, step)
        if handled == "stopped":
            context.set_variable("__stopping_result__", origin or result)

        if step.error_handler and step.error_handler.fallback_step_id:
            fallback_id = step.error_handler.fallback_step_id
            fallback_step = self._step_map.get(fallback_id)
            if not fallback_step:
                raise ValueError(
                    f"Fallback step '{fallback_id}' for failed step '{step.id}' not found in flow definition."
                )

            self.logger.logger.info(
                f"Step '{step.id}' failed. Executing fallback recovery step '{fallback_id}' ({fallback_step.name})."
            )
            self._execute_step(fallback_step, context)
            return

        if on_error == "continue":
            return
        if handled == "next_item":
            raise _NextItem(str(last_error)) from last_error

        # The failure that stops Steps is the run's failure, also after earlier failures that were continued
        if (context.get_variable("__section__") or "steps") == "steps":
            context.failure_details = failure_diag
        raise last_error

    def _handle_loop_step(self, step: Step, evaluated_params: Dict[str, Any], context: ExecutionContext, start_time: datetime) -> None:
        items = evaluated_params.get("items", [])
        item_var = evaluated_params.get("item_var", "item")
        sub_steps = step.sub_steps or []

        if not isinstance(items, list):
            items = [items]

        loops = list(context.get_variable("__loops__") or [])
        location = list(context.get_variable("__location__") or [context.flow_name])
        context.set_variable("__location__", location + [step.name])
        # Loops of this flow only: a subflow called inside a loop starts outside any loop of its own
        depth = int(context.get_variable("__loop_depth__") or 0)
        context.set_variable("__loop_depth__", depth + 1)
        # A loop with item_label works through items; the run counts them as done or failed
        counts = context.get_variable("__items__")
        counted = (step.parameters.get("item_label") not in (None, "") and isinstance(counts, dict)
                   and (context.get_variable("__section__") or "steps") == "steps")
        if counted:
            counts["total"] += len(items)
        try:
            for index, item in enumerate(items):
                if context.get_variable("__early_exit__"):
                    break
                context.set_variable(item_var, item)
                context.set_variable(f"{item_var}_index", index)
                label = self._item_label(step.parameters.get("item_label"), item_var, item, context)
                context.set_variable("__loops__", loops + [{"index": index + 1, "of": len(items), "item": label}])
                failures_before = self._failure_count(context)
                try:
                    for sub_step in sub_steps:
                        if context.get_variable("__early_exit__"):
                            break
                        self._execute_step(sub_step, context)
                except _NextItem:
                    pass  # the failure was recorded; the item counts as failed below
                except Exception:
                    if counted:
                        counts["failed"] += 1
                    raise
                if counted:
                    counts["failed" if self._failure_count(context) > failures_before else "done"] += 1
        finally:
            context.set_variable("__loops__", loops)
            context.set_variable("__location__", location)
            context.set_variable("__loop_depth__", depth)

        end_time = local_now()
        duration = (end_time - start_time).total_seconds()

        result = StepResult(
            step_id=step.id,
            step_name=step.name,
            action=step.action,
            status="success",
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            output={"total_items_processed": len(items)}
        )
        self._record(context, result, step)

    def _handle_if_step(self, step: Step, evaluated_params: Dict[str, Any], context: ExecutionContext, start_time: datetime) -> None:
        left = evaluated_params.get("left")
        operator = evaluated_params.get("operator", "equals")
        right = evaluated_params.get("right")

        # The raw text is used, not evaluated_params, so the expression is split before variables are replaced
        raw_condition = step.parameters.get("condition", step.condition)
        if raw_condition is not None and "left" not in evaluated_params:
            condition_met = self._condition_holds(raw_condition, context.variables)
        else:
            condition_met = self._evaluate_condition(left, operator, right)

        sub_steps = step.sub_steps or []
        else_steps = step.else_steps or []
        executed_count = 0
        branch = "none"
        status = "skipped"
        location = list(context.get_variable("__location__") or [context.flow_name])
        context.set_variable("__location__", location + [step.name])
        try:
            if condition_met:
                for sub_step in sub_steps:
                    if context.get_variable("__early_exit__"):
                        break
                    self._execute_step(sub_step, context)
                executed_count = len(sub_steps)
                branch = "then"
                status = "success"
            elif else_steps:
                for else_step in else_steps:
                    if context.get_variable("__early_exit__"):
                        break
                    self._execute_step(else_step, context)
                executed_count = len(else_steps)
                branch = "else"
                status = "success"
        finally:
            context.set_variable("__location__", location)

        end_time = local_now()
        duration = (end_time - start_time).total_seconds()

        result = StepResult(
            step_id=step.id,
            step_name=step.name,
            action=step.action,
            status=status,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            output={
                "condition_met": condition_met,
                "branch_executed": branch,
                "left": left,
                "operator": operator,
                "right": right,
                "executed_steps": executed_count
            }
        )
        self._record(context, result, step)

    def _apply_config_data(self, config_data: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # 1. Align website <-> target_url synonyms
        if "website" in config_data and "target_url" not in config_data:
            config_data["target_url"] = config_data["website"]
        elif "target_url" in config_data and "website" not in config_data:
            config_data["website"] = config_data["target_url"]

        # 2. Synchronize credentials if present in config
        if "smtp_user" in config_data and config_data["smtp_user"]:
            os.environ.setdefault("GMAIL_USER", str(config_data["smtp_user"]))
            os.environ.setdefault("SMTP_USER", str(config_data["smtp_user"]))
        if "smtp_password" in config_data and config_data["smtp_password"]:
            os.environ.setdefault("GMAIL_APP_PASSWORD", str(config_data["smtp_password"]))
            os.environ.setdefault("SMTP_PASSWORD", str(config_data["smtp_password"]))

        # 3. Merge with existing config (e.g. from flow definition default variables)
        existing_config = context.get_variable("config")
        if isinstance(existing_config, dict):
            merged_config = {**existing_config, **config_data}
        else:
            merged_config = config_data

        context.set_variable("config", merged_config)
        for k, v in merged_config.items():
            context.set_variable(k, v)
        return merged_config

    def _load_bundle_configs(self, flow_dir: Path, context: ExecutionContext) -> None:
        if not flow_dir.is_dir():
            return

        # 1. Primary Check: config/config.json then config.json
        config_candidates = [
            flow_dir / "config" / "config.json",
            flow_dir / "config.json"
        ]
        config_file = next((p for p in config_candidates if p.is_file()), None)

        template_candidates = [
            flow_dir / "config" / "config.template.json",
            flow_dir / "config.template.json"
        ]
        template_file = next((p for p in template_candidates if p.is_file()), None)

        if config_file:
            try:
                config_data = json.loads(config_file.read_text(encoding="utf-8-sig"))
                if isinstance(config_data, dict):
                    applied = self._apply_config_data(config_data, context)
                    self.logger.logger.info(f"Loaded project configuration from {config_file.name} ({len(applied)} keys)")
            except Exception as e:
                self.logger.logger.warning(f"Failed to load config from {config_file}: {str(e)}")
        elif template_file:
            self.logger.logger.warning(
                f"Configuration file 'config.json' was not found in '{flow_dir.name}'. "
                f"Falling back to default '{template_file.name}'. "
                f"(Tip: Copy '{template_file.name}' to 'config.json' to customize your project settings)."
            )
            try:
                config_data = json.loads(template_file.read_text(encoding="utf-8-sig"))
                if isinstance(config_data, dict):
                    applied = self._apply_config_data(config_data, context)
            except Exception as e:
                self.logger.logger.warning(f"Failed to load template config from {template_file}: {str(e)}")
        else:
            self.logger.logger.debug(f"No configuration file ('config.json') found in '{flow_dir.name}'.")

        # 2. Auto-load local .env (if present)
        env_file = flow_dir / ".env"
        if env_file.is_file():
            try:
                self._load_env_file(env_file)
                self.logger.logger.info(f"Loaded environment secrets from {env_file.name}")
            except Exception as e:
                self.logger.logger.warning(f"Failed to load .env from {env_file}: {str(e)}")

    def _load_env_file(self, env_path: Path) -> None:
        for k, v in read_env_file(env_path).items():
            if k not in os.environ:
                os.environ[k] = v
            self.logger.redactor.add_env_file_value(k, v)

    def _resolve_subflow_path(self, flow_target: str, context: ExecutionContext) -> Path:
        return resolve_subflow_path(flow_target, context)

    def _handle_flow_call_step(self, step: Step, evaluated_params: Dict[str, Any], context: ExecutionContext,
                               start_time: datetime, retries: int = 0) -> None:
        flow_target = evaluated_params.get("flow")
        if not flow_target:
            raise ValueError(f"Step '{step.id}' (flow.call) requires 'flow' parameter specifying path to target flow JSON")

        resolved_path = self._resolve_subflow_path(flow_target, context)
        canonical_key = str(resolved_path)

        # 1. Enforce max_depth recursion safety
        if len(self.call_stack) >= self.max_depth:
            raise SubflowExecutionError(
                f"Subflow call depth limit of {self.max_depth} exceeded. Current stack: {' -> '.join(self.call_stack)}",
                subflow_name=flow_target,
                failed_step_id=step.id
            )

        # 2. Prevent Circular Subflow Invocation
        if canonical_key in self.call_stack:
            raise SubflowExecutionError(
                f"Circular subflow call detected: {' -> '.join(self.call_stack)} -> {canonical_key}",
                subflow_name=flow_target,
                failed_step_id=step.id
            )

        # 3. Load child FlowDefinition; the .md subflow is compiled in memory on every run
        try:
            subflow_def = load_subflow(resolved_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load subflow definition from '{resolved_path}': {str(e)}") from e
        shared = is_shared_subflow(flow_target, resolved_path, context)

        # 4. Variable Priority Order:
        # 4.1 Subflow defaults
        child_vars = dict(subflow_def.variables) if subflow_def.variables else {}

        # 4.2 Config: a subflow of this bundle works with the bundle's config; a shared subflow
        #     (@shared/ or outside the bundle) keeps its own unless inherit_config is set
        parent_config = context.get_variable("config")
        if isinstance(parent_config, dict) and (not shared or _is_true(evaluated_params.get("inherit_config"))):
            child_vars["config"] = dict(parent_config)

        # 4.3 Inputs from parent flow (override defaults; an inputs "config" is merged over the config)
        inputs = evaluated_params.get("inputs", {})
        if isinstance(inputs, dict):
            for k, v in inputs.items():
                if k == "config" and isinstance(v, dict) and isinstance(child_vars.get("config"), dict):
                    child_vars["config"] = {**child_vars["config"], **v}
                else:
                    child_vars[k] = v

        # 4.4 System variables. Relative paths in a bundle subflow resolve against the bundle root
        #     (output/, assets/, config/), like the main flow; a shared subflow keeps its own folder
        bundle_dir = context.get_variable("__flow_dir__")
        child_vars["__flow_dir__"] = str(resolved_path.parent) if shared or not bundle_dir else str(bundle_dir)
        child_vars["__flow_file_dir__"] = str(resolved_path.parent)
        child_vars["__bundle_config_from_caller__"] = not shared
        child_vars["__parent_flow__"] = context.flow_name
        child_vars["__is_subflow__"] = True
        # The run id, the path to this call, and the enclosing loop items, for ${run} and ${error} in the subflow
        child_vars["run"] = dict(context.get_variable("run") or {})
        child_vars["__location__"] = list(context.get_variable("__location__") or [context.flow_name]) + [subflow_def.name]
        child_vars["__loops__"] = list(context.get_variable("__loops__") or [])
        child_vars["__items__"] = context.get_variable("__items__")

        # 4.5 Safeguard & Browser Session Propagation
        if evaluated_params.get("propagate_sessions", True):
            pw = context.get_variable("__playwright_pw__")
            browser = context.get_variable("__playwright_browser__")
            page = context.get_variable("__playwright_page__")
            if pw:
                child_vars["__playwright_pw__"] = pw
            if browser:
                child_vars["__playwright_browser__"] = browser
                child_vars["__shared_browser__"] = True  # Safeguard signal
            if page:
                child_vars["__playwright_page__"] = page
        elif context.get_variable("__playwright_pw__"):
            # Playwright allows one instance per thread: the subflow borrows it and opens its own browser
            child_vars["__playwright_pw__"] = context.get_variable("__playwright_pw__")

        # 5. Spawn child interpreter with incremented call stack
        new_stack = list(self.call_stack) + [canonical_key]
        child_interpreter = FlowInterpreter(
            logger=self.logger,
            max_depth=self.max_depth,
            call_stack=new_stack,
            auto_close_browser=self.auto_close_browser
        )
        child_interpreter.finishing = self.finishing or (context.get_variable("__section__") or "steps") != "steps"

        child_context = child_interpreter.run_flow(subflow_def, initial_vars=child_vars)
        self._take_browser_back(context, child_context, shared=evaluated_params.get("propagate_sessions", True))
        # The subflow's steps are part of this run's record, in the order they ran (#62)
        context.step_results.extend(child_context.step_results)
        context.set_variable("__failures__", self._failure_count(context) + self._failure_count(child_context))

        if child_context.interrupted:
            raise RunStopped()  # The subflow ran its own Finally; now this flow stops

        if child_context.has_error:
            failed_id = child_context.failure_details.failed_step_id if child_context.failure_details else "unknown"
            err_msg = child_context.failure_details.error_message if child_context.failure_details else "Child subflow failed"
            raise SubflowExecutionError(
                f"Subflow '{subflow_def.name}' failed at step '{failed_id}': {err_msg}",
                subflow_name=subflow_def.name,
                failed_step_id=failed_id,
                child_context=child_context
            )

        # 6. Method 2: Contract-First Return Payload
        child_return = child_context.get_variable("__return_value__")
        if child_return is None:
            child_return = {
                k: v for k, v in child_context.variables.items()
                if not k.startswith("__")
            }

        if step.output_var:
            context.set_variable(step.output_var, child_return)

        # Optional direct outputs mapping if configured
        outputs_map = evaluated_params.get("outputs")
        if isinstance(outputs_map, dict):
            for sub_k, parent_k in outputs_map.items():
                if sub_k in child_context.variables:
                    context.set_variable(parent_k, child_context.variables[sub_k])

        end_time = local_now()
        duration = (end_time - start_time).total_seconds()

        # 7. Hierarchical Logging: subflow steps grouped inside parent step output
        result = StepResult(
            step_id=step.id,
            step_name=step.name,
            action=step.action,
            status="success",
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            retries=retries,
            output={
                "subflow_name": subflow_def.name,
                "subflow_path": str(resolved_path),
                "return_value": child_return,
                "subflow_metrics": child_context.metrics.model_dump(),
            }
        )
        self._record(context, result, step)

    def _handle_flow_return_step(self, step: Step, evaluated_params: Dict[str, Any], context: ExecutionContext, start_time: datetime) -> None:
        value = evaluated_params.get("value")
        context.set_variable("__return_value__", value)
        context.set_variable("__early_exit__", True)

        end_time = local_now()
        duration = (end_time - start_time).total_seconds()

        result = StepResult(
            step_id=step.id,
            step_name=step.name,
            action=step.action,
            status="success",
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            output={"returned": value, "early_exit": True}
        )
        self._record(context, result, step)

    def _evaluate_condition(self, left: Any, operator: str, right: Any) -> bool:
        op = (operator or "equals").lower().strip()

        if op in ["is_empty", "empty"]:
            return left is None or str(left).strip() == ""
        if op in ["is_not_empty", "not_empty"]:
            return left is not None and str(left).strip() != ""

        if is_order_operator(op):
            return compare_order(left, op, right)

        s_left = "" if left is None else str(left).strip()
        s_right = "" if right is None else str(right).strip()

        if op in ["equals", "==", "eq"]:
            return values_equal(left, right)
        if op in ["not_equals", "!=", "neq"]:
            return not values_equal(left, right)
        # `left in right` means left is part of right; a list on the other side is checked item by item
        if op in ["in", "not_in"]:
            if isinstance(right, (list, tuple, set)):
                found = any(s_left.lower() == ("" if item is None else str(item).strip()).lower() for item in right)
            else:
                found = s_left.lower() in s_right.lower()
            return found if op == "in" else not found
        if op in ["contains", "not_contains"]:
            if isinstance(left, (list, tuple, set)):
                found = any(s_right.lower() == ("" if item is None else str(item).strip()).lower() for item in left)
            else:
                found = s_right.lower() in s_left.lower()
            return found if op == "contains" else not found
        if op in ["starts_with", "startswith"]:
            return s_left.lower().startswith(s_right.lower())
        if op in ["ends_with", "endswith"]:
            return s_left.lower().endswith(s_right.lower())

        return s_left == s_right

    def _condition_holds(self, expression: Any, variables: Dict[str, Any]) -> bool:
        """
        Evaluates a condition such as `${a} == b`, `${note} is empty`, or several joined with and / or /
        not (see engine/conditions.py).
        """
        if isinstance(expression, bool):
            return expression
        text = str(expression).strip()
        if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
            text = text[1:-1].strip()
        problem = grouping_problem(text)
        if problem:
            raise ConditionError(problem, text)
        return self._boolean_holds(parse_boolean(text), variables)

    def _boolean_holds(self, tree: Any, variables: Dict[str, Any]) -> bool:
        kind, value = tree
        if kind == "or":
            return any(self._boolean_holds(part, variables) for part in value)
        if kind == "and":
            return all(self._boolean_holds(part, variables) for part in value)
        if kind == "not":
            return not self._comparison_holds(value, variables)
        return self._comparison_holds(value, variables)

    def _comparison_holds(self, expression: str, variables: Dict[str, Any]) -> bool:
        left, operator, right = resolve_condition(expression, variables)
        if operator is None:
            return left if isinstance(left, bool) else str(left).strip().lower() in ["true", "1", "yes"]
        try:
            return self._evaluate_condition(left, operator, right)
        except ConditionError as e:
            raise ConditionError(e.reason, expression) from None

    def _evaluate_condition_expr(self, expr: Any) -> bool:
        """A condition whose variables are already replaced; kept for callers outside the interpreter."""
        return self._condition_holds(expr, {})
