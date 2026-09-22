"""
Acceptance Tests for Executor Agent v1 (Engineer 2 — Task 26).

Covers:
- SUCCESS: 3-step ExecutionPlan execution, all succeed, STEP_COMPLETED and CODE_MODIFIED events.
- RECOVERY: Controlled failure on step 2, retry occurs (retry count <= 2), recovery succeeds, execution finishes.
- HARD FAILURE: Persistent failure on a step, retry count capped at exactly 2, rollback triggered,
  execution stops, status transitions to NEEDS_REPAIR, STEP_FAILED event emitted, later steps never run.
- Docker-dependent tests cleanly mocked/separated.
"""

from pathlib import Path
import pytest
import shutil
import subprocess
import tempfile
from typing import Any, Dict

from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ReadFileArgs,
    ApplyPatchArgs,
    RunCommandArgs,
    RunTestsArgs,
)
from app.agents.agent_2.tool_registry import (
    ToolRegistry,
    ToolResult,
    ToolPermission,
    create_default_tool_registry,
)
from app.agents.agent_2.git_workspace import (
    GitWorkspaceManager,
)
from app.agents.agent_2.executor import (
    ExecutorAgent,
    ExecutorResult,
    ExecutionStatus,
    MAX_RETRIES_PER_STEP,
)
from app.contracts.schemas import AgentEventType


@pytest.fixture
def test_repo_and_workspace():
    """Create a temporary repo and workspace manager for executor tests."""
    temp_dir = tempfile.mkdtemp(prefix="test_executor_repo_")
    repo_path = Path(temp_dir).resolve()

    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Executor Tester"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@teslalab.ai"], cwd=str(repo_path), check=True, capture_output=True)

    # Seed file
    demo_file = repo_path / "calc.py"
    demo_file.write_text("def add(a, b):\n    return a - b  # deliberate bug\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=str(repo_path), check=True, capture_output=True)

    mgr = GitWorkspaceManager(repo_path=repo_path)
    yield repo_path, mgr

    # Cleanup
    for attempt in range(3):
        try:
            shutil.rmtree(repo_path, ignore_errors=False)
            break
        except Exception:
            import time
            time.sleep(0.2)
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)


class TestExecutorAgentAcceptance:
    """Acceptance test suite for ExecutorAgent v1."""

    def test_01_successful_three_step_execution(self, test_repo_and_workspace):
        """
        SUCCESS Acceptance Test:
        - 3-step ExecutionPlan (read_file -> apply_patch -> run_command)
        - All 3 succeed sequentially
        - Verify STEP_COMPLETED events for each step
        - Verify CODE_MODIFIED event for apply_patch
        - Verify overall status is SUCCESS
        """
        _, mgr = test_repo_and_workspace
        registry = create_default_tool_registry()

        plan = ExecutionPlan(
            goal="Fix deliberate subtraction bug in calc.py",
            affected_files=["calc.py"],
            estimated_complexity="Low",
            rollback_plan="Revert workspace",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments=ReadFileArgs(path="calc.py"),
                    expected_outcome="Read original calc.py content",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path="calc.py",
                        original_chunk="    return a - b  # deliberate bug",
                        replacement_chunk="    return a + b",
                        line_number=2,
                    ),
                    expected_outcome="Patch calc.py to use addition",
                    rollback_action="Revert patch",
                ),
                PlanStep(
                    step_number=3,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(
                        command="python -c \"print('validation passed')\"",
                        timeout_seconds=10,
                    ),
                    expected_outcome="Validate addition logic",
                    rollback_action="None",
                ),
            ],
        )

        emitted_events = []
        executor = ExecutorAgent(
            tool_registry=registry,
            workspace_manager=mgr,
            event_callback=lambda evt: emitted_events.append(evt),
        )

        res = executor.execute_plan(
            plan=plan,
            session_id="session-success-001",
            task_name="task-fix-add",
        )

        assert res.status == ExecutionStatus.SUCCESS
        assert len(res.completed_steps) == 3
        assert res.failed_step is None
        assert res.total_retries == 0

        # Check events
        event_types = [e.event_type for e in emitted_events]
        assert "STEP_COMPLETED" in event_types
        assert event_types.count("STEP_COMPLETED") == 3
        assert AgentEventType.CODE_MODIFIED.value in event_types

        # Verify step numbers
        completed_step_nums = [
            e.payload.get("step_number") for e in emitted_events if e.event_type == "STEP_COMPLETED"
        ]
        assert completed_step_nums == [1, 2, 3]

    def test_02_recovery_after_transient_failure(self, test_repo_and_workspace):
        """
        RECOVERY Acceptance Test:
        - Step 2 fails once due to an error, then succeeds on retry 1
        - Verify retry occurred
        - Verify recovery succeeds and step 3 executes
        - Verify overall status is SUCCESS
        """
        _, mgr = test_repo_and_workspace
        registry = create_default_tool_registry()

        # Wrap run_command to fail on first attempt, then succeed on retry
        attempts_tracker = {"step2_calls": 0}
        original_run_cmd = registry.get_tool("run_command").handler

        def flaky_run_cmd(args, **kw):
            if "flaky" in args.command:
                attempts_tracker["step2_calls"] += 1
                if attempts_tracker["step2_calls"] == 1:
                    raise RuntimeError("Transient connection reset in test runner")
            return original_run_cmd(args, **kw)

        # Re-register with flaky handler
        registry.register(
            name="run_command",
            description="Execute command with simulated transient glitch",
            parameters_schema=RunCommandArgs,
            permission=ToolPermission.DESTRUCTIVE,
            handler=flaky_run_cmd,
        )

        plan = ExecutionPlan(
            goal="Execute multi-step workflow with transient recovery",
            affected_files=["calc.py"],
            estimated_complexity="Low",
            rollback_plan="Revert workspace",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments=ReadFileArgs(path="calc.py"),
                    expected_outcome="Read calc.py",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(
                        command="python -c \"# flaky test\nprint('recovered')\"",
                        timeout_seconds=10,
                    ),
                    expected_outcome="Run transient test",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=3,
                    tool_name="read_file",
                    tool_arguments=ReadFileArgs(path="calc.py"),
                    expected_outcome="Verify calc.py final state",
                    rollback_action="None",
                ),
            ],
        )

        executor = ExecutorAgent(tool_registry=registry, workspace_manager=mgr)
        res = executor.execute_plan(plan=plan, task_name="task-recovery-test")

        assert res.status == ExecutionStatus.SUCCESS
        assert attempts_tracker["step2_calls"] == 2  # 1 initial fail + 1 retry success
        assert res.step_retries.get(2) == 1
        assert res.total_retries == 1
        assert len(res.completed_steps) == 3

    def test_03_hard_failure_rollback_and_needs_repair(self, test_repo_and_workspace):
        """
        HARD FAILURE Acceptance Test:
        - Inject persistent failure on step 2
        - Verify retry count never exceeds 2
        - Verify workspace rollback is triggered
        - Verify status transitions to NEEDS_REPAIR
        - Verify STEP_FAILED event is emitted
        - Verify step 3 is NEVER executed
        """
        _, mgr = test_repo_and_workspace
        registry = create_default_tool_registry()

        # Handler that persistently fails
        def persistently_failing_handler(args, **kw):
            raise RuntimeError("Fatal unrecoverable syntax / sandbox execution error")

        registry.register(
            name="apply_patch",
            description="Failing patch handler",
            parameters_schema=ApplyPatchArgs,
            permission=ToolPermission.WRITE,
            handler=persistently_failing_handler,
        )

        plan = ExecutionPlan(
            goal="Test hard failure and rollback enforcement",
            affected_files=["calc.py"],
            estimated_complexity="Medium",
            rollback_plan="Rollback dirty workspace",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments=ReadFileArgs(path="calc.py"),
                    expected_outcome="Read file",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path="calc.py",
                        original_chunk="bad",
                        replacement_chunk="good",
                        line_number=1,
                    ),
                    expected_outcome="Apply patch that will persistently fail",
                    rollback_action="Rollback",
                ),
                PlanStep(
                    step_number=3,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(
                        command="python -c \"print('should never run!')\"",
                        timeout_seconds=10,
                    ),
                    expected_outcome="This step MUST NOT be executed",
                    rollback_action="None",
                ),
            ],
        )

        emitted_events = []
        executor = ExecutorAgent(
            tool_registry=registry,
            workspace_manager=mgr,
            event_callback=lambda evt: emitted_events.append(evt),
        )

        res = executor.execute_plan(
            plan=plan,
            task_name="task-hard-fail",
            session_id="session-hard-fail",
        )

        # 1. Status must be NEEDS_REPAIR
        assert res.status == ExecutionStatus.NEEDS_REPAIR

        # 2. Only step 1 should be in completed_steps
        assert len(res.completed_steps) == 1
        assert res.completed_steps[0].step_number == 1

        # 3. Failed step must be step 2
        assert res.failed_step is not None
        assert res.failed_step.step_number == 2

        # 4. Retry count must NEVER exceed 2
        assert res.step_retries.get(2) == MAX_RETRIES_PER_STEP
        assert res.step_retries.get(2) == 2

        # 5. STEP_FAILED event must be emitted
        event_types = [e.event_type for e in emitted_events]
        assert "STEP_FAILED" in event_types

        step_failed_evt = next(e for e in emitted_events if e.event_type == "STEP_FAILED")
        assert step_failed_evt.payload.get("step_number") == 2
        assert step_failed_evt.payload.get("rollback_triggered") is True

        # 6. Workspace rollback verified clean
        diff_res = mgr.get_diff_result("task-hard-fail")
        assert diff_res.has_changes is False

    def test_04_retry_count_strictly_capped_at_two(self, test_repo_and_workspace):
        """
        Verify that under NO circumstances can a step exceed 2 retries (3 total attempts).
        """
        _, mgr = test_repo_and_workspace
        registry = create_default_tool_registry()

        call_counts = {"attempts": 0}

        def counting_fail_handler(args, **kw):
            call_counts["attempts"] += 1
            raise RuntimeError(f"Failure on call {call_counts['attempts']}")

        registry.register(
            name="run_tests",
            description="Failing test runner",
            parameters_schema=RunTestsArgs,
            permission=ToolPermission.WRITE,
            handler=counting_fail_handler,
        )

        plan = ExecutionPlan(
            goal="Strict retry cap enforcement test",
            affected_files=["calc.py"],
            estimated_complexity="Low",
            rollback_plan="Rollback",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="run_tests",
                    tool_arguments=RunTestsArgs(test_command="pytest"),
                    expected_outcome="Fail and verify retry limit",
                    rollback_action="None",
                )
            ],
        )

        executor = ExecutorAgent(tool_registry=registry, workspace_manager=mgr)
        res = executor.execute_plan(plan=plan, task_name="task-retry-cap")

        assert res.status == ExecutionStatus.NEEDS_REPAIR
        # Exactly 1 initial + 2 retries = 3 calls total
        assert call_counts["attempts"] == 3
        assert res.step_retries[1] == 2
        assert res.total_retries == 2

    def test_05_custom_retry_hook_with_feedback(self, test_repo_and_workspace):
        """
        Verify that retry can incorporate error feedback / argument adaptation.
        """
        _, mgr = test_repo_and_workspace
        registry = create_default_tool_registry()

        plan = ExecutionPlan(
            goal="Test retry argument feedback adaptation",
            affected_files=["calc.py"],
            estimated_complexity="Low",
            rollback_plan="Rollback",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="python -c \"import sys; sys.exit(1)\""),
                    expected_outcome="Self-heal command arguments on retry",
                    rollback_action="None",
                )
            ],
        )

        def retry_hook(step, attempt, last_result):
            # Adapt command to succeed on retry
            if attempt == 1:
                return {"command": "python -c \"import sys; sys.exit(0)\"", "timeout_seconds": 10}
            return None

        executor = ExecutorAgent(tool_registry=registry, workspace_manager=mgr)
        res = executor.execute_plan(
            plan=plan,
            task_name="task-hook-feedback",
            custom_retry_hook=retry_hook,
        )

        assert res.status == ExecutionStatus.SUCCESS
        assert res.step_retries[1] == 1
        assert len(res.completed_steps) == 1

    @pytest.mark.skipif(True, reason="Docker daemon is not available on host. Live container execution deferred.")
    def test_06_docker_live_sandbox_execution(self, test_repo_and_workspace):
        """
        Placeholder test explicitly marking live Docker execution as skipped
        when Docker daemon is absent, adhering to cross-task non-fabrication rules.
        """
        pass
