"""
Executor Agent v1 for Engineer 2 (Agent 2) — Task 26.

Implements a sequential ReAct-style execution loop:
- Executes validated ExecutionPlan steps sequentially
- Dispatches tool invocations through ToolRegistry and Sandbox
- ReAct loop: read step -> dispatch tool -> receive ToolResult -> evaluate -> continue/retry
- Strict retry ceiling: Maximum 2 retries per failed step (NEVER exceeds 2)
- Hard failure recovery:
    - If a step still fails after allowed retries:
        1. Triggers GitWorkspaceManager.rollback_to_clean()
        2. Halts execution (does NOT execute later steps)
        3. Transitions status to NEEDS_REPAIR
        4. Emits STEP_FAILED
- Reuses existing event infrastructure: emits STEP_COMPLETED, STEP_FAILED, CODE_MODIFIED
- Returns structured ExecutorResult (status, completed_steps, failed_step, retries, errors, events, diff)
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    StepOutcome,
)
from app.agents.agent_2.tool_registry import (
    ToolRegistry,
    ToolResult,
    default_registry,
)
from app.agents.agent_2.sandbox import (
    Sandbox,
    default_sandbox,
)
from app.agents.agent_2.git_workspace import (
    GitWorkspaceManager,
    WorkspaceSession,
    default_workspace_manager,
)
from app.agents.agent_2.execution_safety import (
    ExecutionSafety,
    SafetyViolationError,
    SafetyViolation,
    GuardType,
)
from app.contracts.schemas import (
    AgentEvent,
    AgentEventType,
    SessionState,
)

logger = logging.getLogger("executor_agent_v1")

MAX_RETRIES_PER_STEP: int = 2


class ExecutionStatus(str, Enum):
    """Overall status of plan execution."""
    SUCCESS = "SUCCESS"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    FAILED = "FAILED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class ExecutorResult(BaseModel):
    """Structured output from ExecutorAgent."""
    model_config = ConfigDict(extra="ignore")

    status: ExecutionStatus = Field(..., description="Overall execution outcome")
    completed_steps: List[StepOutcome] = Field(default_factory=list, description="Steps completed successfully")
    failed_step: Optional[PlanStep] = Field(default=None, description="Step where hard failure occurred, if any")
    total_retries: int = Field(default=0, ge=0, description="Total number of retries executed across all steps")
    step_retries: Dict[int, int] = Field(default_factory=dict, description="Retry count mapped per step number")
    errors: List[str] = Field(default_factory=list, description="List of recorded error messages")
    emitted_events: List[Dict[str, Any]] = Field(default_factory=list, description="Chronological log of emitted events")
    diff: Optional[str] = Field(default=None, description="Unified git diff from workspace if available")
    workspace_branch: Optional[str] = Field(default=None, description="Task branch name")
    workspace_path: Optional[str] = Field(default=None, description="Absolute worktree path")


class ExecutorAgent:
    """
    Executor Agent v1.
    Coordinates sequential plan execution through ToolRegistry, Sandbox, and GitWorkspaceManager.
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        workspace_manager: Optional[GitWorkspaceManager] = None,
        sandbox: Optional[Sandbox] = None,
        execution_safety: Optional[ExecutionSafety] = None,
        event_callback: Optional[Callable[[AgentEvent], Any]] = None,
    ) -> None:
        self.tool_registry = tool_registry or default_registry
        self.workspace_manager = workspace_manager or default_workspace_manager
        self.sandbox = sandbox or default_sandbox
        self.execution_safety = execution_safety or ExecutionSafety()
        self.event_callback = event_callback

    def _emit_event(
        self,
        session_id: str,
        event_type: str,
        payload: Dict[str, Any],
        from_state: SessionState = SessionState.EXECUTING,
        to_state: SessionState = SessionState.EXECUTING,
        events_log: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentEvent:
        """Create, record, and dispatch a structured AgentEvent."""
        event = AgentEvent(
            id=str(uuid.uuid4()),
            session_id=session_id,
            from_state=from_state,
            to_state=to_state,
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
        )
        if events_log is not None:
            events_log.append(event.model_dump())

        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception as e:
                logger.warning("Event callback error on %s: %s", event_type, e)

        return event

    def _prepare_tool_args_for_workspace(
        self,
        step: PlanStep,
        workspace_path: Optional[str],
    ) -> Dict[str, Any]:
        """
        Adjust file arguments to resolve within the isolated workspace path if provided.
        """
        raw_args = step.tool_arguments
        args_dict = raw_args.model_dump() if hasattr(raw_args, "model_dump") else dict(raw_args)

        if not workspace_path:
            return args_dict

        # If a relative file path is targeted, adjust to absolute path inside workspace
        if "path" in args_dict and isinstance(args_dict["path"], str):
            p = args_dict["path"]
            if not os.path.isabs(p):
                args_dict["path"] = str((Path(workspace_path) / p).resolve())

        if "cwd" in args_dict and args_dict["cwd"] in (None, ".", ""):
            args_dict["cwd"] = workspace_path

        return args_dict

    def execute_plan(
        self,
        plan: ExecutionPlan,
        session_id: Optional[str] = None,
        task_name: Optional[str] = None,
        workspace_session: Optional[WorkspaceSession] = None,
        custom_retry_hook: Optional[Callable[[PlanStep, int, ToolResult], Optional[Dict[str, Any]]]] = None,
        execution_safety: Optional[ExecutionSafety] = None,
    ) -> ExecutorResult:
        """
        Execute a validated ExecutionPlan sequentially.

        Flow:
        Read next step -> safety check -> dispatch tool -> safety check -> evaluate result -> continue OR retry
        """
        active_session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        active_task_name = task_name or f"task-exec-{uuid.uuid4().hex[:8]}"
        safety = execution_safety or self.execution_safety or ExecutionSafety()

        # 1. Initialize or acquire workspace if requested
        ws: Optional[WorkspaceSession] = workspace_session
        if ws is None and self.workspace_manager:
            try:
                ws = self.workspace_manager.checkout(active_task_name)
            except Exception as e:
                logger.warning("Could not create workspace for task %s: %s", active_task_name, e)

        ws_path = ws.worktree_path if ws else None
        completed_steps: List[StepOutcome] = []
        emitted_events: List[Dict[str, Any]] = []
        errors: List[str] = []
        step_retries: Dict[int, int] = {}
        total_retries = 0
        overall_status = ExecutionStatus.SUCCESS
        failed_step: Optional[PlanStep] = None

        # 2. Sequential Step Execution
        for step in plan.steps:
            step_num = step.step_number
            tool_name = step.tool_name
            step_retries[step_num] = 0
            step_success = False
            last_tool_result: Optional[ToolResult] = None
            current_args = self._prepare_tool_args_for_workspace(step, ws_path)

            # Runtime Safety Guard Interceptor (Pre-Step)
            try:
                safety.intercept_pre_step(
                    workspace_root=ws_path,
                    tool_name=tool_name,
                    step_number=step_num,
                    args=current_args,
                )
            except SafetyViolationError as sve:
                logger.error("ExecutionSafety PRE-STEP violation on step %d: %s", step_num, sve)
                overall_status = ExecutionStatus.NEEDS_HUMAN
                failed_step = step
                errors.append(str(sve))
                self._emit_event(
                    session_id=active_session_id,
                    event_type="SAFETY_VIOLATION",
                    payload=sve.violation.to_dict(),
                    from_state=SessionState.EXECUTING,
                    to_state=SessionState.NEEDS_HUMAN,
                    events_log=emitted_events,
                )
                break

            attempt = 0
            while attempt <= MAX_RETRIES_PER_STEP:
                logger.info(
                    "Executing Step %d: %s (attempt %d/%d)",
                    step_num, tool_name, attempt, MAX_RETRIES_PER_STEP,
                )

                # Dispatch tool invocation
                tool_result = self.tool_registry.dispatch(
                    name=tool_name,
                    args=current_args,
                )
                last_tool_result = tool_result

                # Evaluate ToolResult
                step_succeeded = tool_result.success
                if step_succeeded and isinstance(tool_result.data, dict):
                    exit_code = tool_result.data.get("exit_code")
                    if exit_code is not None and exit_code != 0:
                        step_succeeded = False
                        err_text = tool_result.data.get("stderr") or f"Command exited with non-zero exit code {exit_code}"
                        tool_result = ToolResult(
                            success=False,
                            data=tool_result.data,
                            error=err_text.strip(),
                            execution_time_ms=tool_result.execution_time_ms,
                        )
                    elif tool_result.data.get("status") in ("failed", "error"):
                        step_succeeded = False
                        err_text = tool_result.data.get("error") or tool_result.data.get("stderr") or f"Command status: {tool_result.data.get('status')}"
                        tool_result = ToolResult(
                            success=False,
                            data=tool_result.data,
                            error=err_text.strip(),
                            execution_time_ms=tool_result.execution_time_ms,
                        )

                # Runtime Safety Guard Interceptor (Post-Step)
                try:
                    safety.intercept_post_step(
                        workspace_root=ws_path,
                        tool_name=tool_name,
                        args=current_args,
                        step_succeeded=step_succeeded,
                    )
                except SafetyViolationError as sve:
                    logger.error("ExecutionSafety POST-STEP violation on step %d: %s", step_num, sve)
                    overall_status = ExecutionStatus.NEEDS_HUMAN
                    failed_step = step
                    errors.append(str(sve))
                    self._emit_event(
                        session_id=active_session_id,
                        event_type="SAFETY_VIOLATION",
                        payload=sve.violation.to_dict(),
                        from_state=SessionState.EXECUTING,
                        to_state=SessionState.NEEDS_HUMAN,
                        events_log=emitted_events,
                    )
                    break

                if step_succeeded:
                    step_success = True

                    # Step outcome recording
                    outcome = StepOutcome(
                        step_number=step_num,
                        tool_name=tool_name,
                        success=True,
                        output=str(tool_result.data) if tool_result.data is not None else None,
                        error=None,
                        artifacts={
                            "attempt": attempt,
                            "execution_time_ms": tool_result.execution_time_ms,
                        },
                    )
                    completed_steps.append(outcome)

                    # Emit CODE_MODIFIED if tool modified code
                    if tool_name in ("apply_patch", "code_modifier"):
                        self._emit_event(
                            session_id=active_session_id,
                            event_type=AgentEventType.CODE_MODIFIED.value,
                            payload={
                                "step_number": step_num,
                                "tool_name": tool_name,
                                "target": current_args.get("path"),
                                "status": "modified",
                            },
                            events_log=emitted_events,
                        )

                    # Emit STEP_COMPLETED
                    self._emit_event(
                        session_id=active_session_id,
                        event_type="STEP_COMPLETED",
                        payload={
                            "step_number": step_num,
                            "tool_name": tool_name,
                            "expected_outcome": step.expected_outcome,
                            "attempts_taken": attempt + 1,
                            "execution_time_ms": tool_result.execution_time_ms,
                        },
                        events_log=emitted_events,
                    )
                    break

                else:
                    # Tool returned failure
                    if attempt < MAX_RETRIES_PER_STEP:
                        attempt += 1
                        total_retries += 1
                        step_retries[step_num] = attempt
                        logger.warning(
                            "Step %d (%s) failed on attempt %d: %s. Retrying (%d/%d)...",
                            step_num, tool_name, attempt, tool_result.error, attempt, MAX_RETRIES_PER_STEP,
                        )

                        # Retry hook allowing argument modification based on error feedback
                        if custom_retry_hook:
                            modified_args = custom_retry_hook(step, attempt, tool_result)
                            if modified_args:
                                current_args = modified_args
                    else:
                        # Max retries reached (2 retries exhausted)
                        break

            # 3. Handle Step Outcome
            if overall_status == ExecutionStatus.NEEDS_HUMAN:
                # Safety violation occurred: execution halts immediately, preserving evidence
                break

            if not step_success:
                # HARD FAILURE on this step
                failed_step = step
                err_msg = (
                    f"Step {step_num} ('{tool_name}') failed after {attempt} retries. "
                    f"Last error: {last_tool_result.error if last_tool_result else 'Unknown failure'}"
                )
                errors.append(err_msg)
                overall_status = ExecutionStatus.NEEDS_REPAIR

                # Trigger GitWorkspaceManager rollback to clean
                if ws and self.workspace_manager:
                    try:
                        rolled_back = self.workspace_manager.rollback_to_clean(ws.task_name)
                        logger.info("Triggered rollback_to_clean for task '%s'. Success: %s", ws.task_name, rolled_back)
                    except Exception as rb_err:
                        logger.error("Failed to rollback workspace '%s': %s", ws.task_name, rb_err)

                # Emit STEP_FAILED
                self._emit_event(
                    session_id=active_session_id,
                    event_type="STEP_FAILED",
                    payload={
                        "step_number": step_num,
                        "tool_name": tool_name,
                        "error": err_msg,
                        "retries_exhausted": attempt,
                        "rollback_triggered": True,
                    },
                    to_state=SessionState.REPAIRING,
                    events_log=emitted_events,
                )

                # Stop execution immediately; do NOT execute later steps
                break

        # 4. Final Diff Capture
        final_diff = None
        if ws and self.workspace_manager and overall_status == ExecutionStatus.SUCCESS:
            try:
                final_diff = self.workspace_manager.get_diff(ws.task_name)
            except Exception:
                final_diff = None

        return ExecutorResult(
            status=overall_status,
            completed_steps=completed_steps,
            failed_step=failed_step,
            total_retries=total_retries,
            step_retries=step_retries,
            errors=errors,
            emitted_events=emitted_events,
            diff=final_diff,
            workspace_branch=ws.branch_name if ws else None,
            workspace_path=ws.worktree_path if ws else None,
        )


default_executor = ExecutorAgent()
