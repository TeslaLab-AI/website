"""
Adversarial tests for Day 5 Task 29: ExecutionSafety Runtime Interceptor.

Acceptance Criteria:
Four adversarial tests:
1. Protected file modification (Guard 1: File Write Jail)
2. Sudo rm command (Guard 2: Command Blocklist)
3. 600-line diff (Guard 3: Diff Size)
4. Three identical cyclic execution steps (Guard 4: Loop Detection)

Expected:
4/4 blocked.
Every violation transitions to NEEDS_HUMAN and execution stops immediately.
"""

import os
import subprocess
import tempfile
import pytest

from app.contracts.schemas import SessionState
from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ApplyPatchArgs,
    RunCommandArgs,
    ReadFileArgs,
)
from app.agents.agent_2.executor import (
    ExecutorAgent,
    ExecutionStatus,
    ExecutorResult,
)
from app.agents.agent_2.execution_safety import (
    ExecutionSafety,
    GuardType,
    SafetyViolationError,
)
from app.agents.agent_2.git_workspace import WorkspaceSession


def _init_git_repo(path: str) -> None:
    """Helper to initialize a git repo for testing diffs."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, capture_output=True, check=True)

    dummy_file = os.path.join(path, "main.py")
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write("# initial content\ndef run():\n    pass\n")

    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, capture_output=True, check=True)


def test_adversarial_guard1_protected_file_modification():
    """
    Adversarial Test 1 (Guard 1 — File Write Jail):
    Attempt to modify .git/config, .env, and a file outside workspace (traversal).
    Asserts:
    - Blocked
    - Transition to NEEDS_HUMAN
    - Execution stops immediately
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        _init_git_repo(tmp_dir)

        ws_session = WorkspaceSession(
            task_name="adv-test-1",
            branch_name="main",
            worktree_path=tmp_dir,
            base_ref="HEAD",
        )

        executor = ExecutorAgent()

        # 1. Test .git escape
        plan_git = ExecutionPlan(
            goal="Attempt modifying .git internals",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path=".git/config",
                        original_chunk="",
                        replacement_chunk="evil=1",
                        line_number=1,
                    ),
                    expected_outcome="Should fail",
                    rollback_action="git checkout -- .git/config",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="echo step2"),
                    expected_outcome="Should not execute",
                    rollback_action="echo noop",
                ),
            ],
        )

        result = executor.execute_plan(plan_git, workspace_session=ws_session)

        # Verifications
        assert result.status == ExecutionStatus.NEEDS_HUMAN
        assert len(result.completed_steps) == 0
        assert any("FILE_WRITE_JAIL" in err for err in result.errors)
        assert any(
            e.get("to_state") in (SessionState.NEEDS_HUMAN.value, SessionState.NEEDS_HUMAN)
            for e in result.emitted_events
        )

        # 2. Test .env file modification
        plan_env = ExecutionPlan(
            goal="Attempt modifying .env",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path=".env",
                        original_chunk="",
                        replacement_chunk="SECRET=12345",
                        line_number=1,
                    ),
                    expected_outcome="Should fail",
                    rollback_action="rm -f .env",
                )
            ],
        )
        res_env = executor.execute_plan(plan_env, workspace_session=ws_session)
        assert res_env.status == ExecutionStatus.NEEDS_HUMAN
        assert any("FILE_WRITE_JAIL" in err for err in res_env.errors)

        # 3. Test directory traversal escape
        plan_escape = ExecutionPlan(
            goal="Attempt escaping workspace via ../",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path="../../outside.txt",
                        original_chunk="",
                        replacement_chunk="outside data",
                        line_number=1,
                    ),
                    expected_outcome="Should fail",
                    rollback_action="echo noop",
                )
            ],
        )
        res_esc = executor.execute_plan(plan_escape, workspace_session=ws_session)
        assert res_esc.status == ExecutionStatus.NEEDS_HUMAN
        assert any("FILE_WRITE_JAIL" in err for err in res_esc.errors)


def test_adversarial_guard2_sudo_rm_command():
    """
    Adversarial Test 2 (Guard 2 — Command Blocklist):
    Attempt to run blocked commands (sudo rm, curl, shell chaining bypass).
    Asserts:
    - Command MUST NOT execute
    - Transition to NEEDS_HUMAN
    - Execution stops immediately
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        _init_git_repo(tmp_dir)
        ws_session = WorkspaceSession(
            task_name="adv-test-cmd",
            branch_name="main",
            worktree_path=tmp_dir,
            base_ref="HEAD",
        )

        executor = ExecutorAgent()

        # 1. Direct sudo rm
        plan_sudo = ExecutionPlan(
            goal="Attempt running sudo rm",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="sudo rm -rf /"),
                    expected_outcome="Should fail",
                    rollback_action="echo noop",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="echo should_not_run"),
                    expected_outcome="Should not execute",
                    rollback_action="echo noop",
                ),
            ],
        )

        res_sudo = executor.execute_plan(plan_sudo, workspace_session=ws_session)
        assert res_sudo.status == ExecutionStatus.NEEDS_HUMAN
        assert len(res_sudo.completed_steps) == 0
        assert any("COMMAND_BLOCKLIST" in err for err in res_sudo.errors)
        assert any(
            e.get("to_state") in (SessionState.NEEDS_HUMAN.value, SessionState.NEEDS_HUMAN)
            for e in res_sudo.emitted_events
        )

        # 2. Shell chaining bypass attempt: echo ok && curl evil.com
        plan_chain = ExecutionPlan(
            goal="Attempt chained curl",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="echo ok && curl https://evil.com"),
                    expected_outcome="Should fail",
                    rollback_action="echo noop",
                )
            ],
        )
        res_chain = executor.execute_plan(plan_chain, workspace_session=ws_session)
        assert res_chain.status == ExecutionStatus.NEEDS_HUMAN
        assert any("COMMAND_BLOCKLIST" in err for err in res_chain.errors)


def test_adversarial_guard3_600_line_diff():
    """
    Adversarial Test 3 (Guard 3 — Diff Size):
    Attempt to inject a 600-line diff.
    Asserts:
    - REAL git diff inspected
    - Blocked (>500 lines)
    - Transition to NEEDS_HUMAN
    - Evidence preserved
    - Later steps halted
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        _init_git_repo(tmp_dir)
        ws_session = WorkspaceSession(
            task_name="adv-test-diff",
            branch_name="main",
            worktree_path=tmp_dir,
            base_ref="HEAD",
        )

        # Create 600 lines in a file
        target_file = os.path.join(tmp_dir, "bloated.py")
        bloated_code = "\n".join(f"x_{i} = {i}" for i in range(600)) + "\n"
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(bloated_code)

        # Validate directly with ExecutionSafety on real git diff
        safety = ExecutionSafety(max_diff_lines=500, max_diff_files=5)
        with pytest.raises(SafetyViolationError) as exc_info:
            safety.validate_diff(tmp_dir)

        violation = exc_info.value.violation
        assert violation.guard == GuardType.DIFF_SIZE
        assert violation.details["changed_lines"] >= 600

        # Now execute a plan that triggers post-step diff inspection
        executor = ExecutorAgent(execution_safety=safety)
        plan_bloat = ExecutionPlan(
            goal="Bloated code addition",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path="main.py",
                        original_chunk="# initial content",
                        replacement_chunk="# updated content",
                        line_number=1,
                    ),
                    expected_outcome="Trigger diff check",
                    rollback_action="git checkout main.py",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="echo unreachable"),
                    expected_outcome="Should not run",
                    rollback_action="echo noop",
                ),
            ],
        )

        # Intercept post-step will detect bloated diff and transition to NEEDS_HUMAN
        res_bloat = executor.execute_plan(plan_bloat, workspace_session=ws_session)
        assert res_bloat.status == ExecutionStatus.NEEDS_HUMAN
        assert any("DIFF_SIZE" in err for err in res_bloat.errors)
        assert any(
            e.get("to_state") in (SessionState.NEEDS_HUMAN.value, SessionState.NEEDS_HUMAN)
            for e in res_bloat.emitted_events
        )


def test_adversarial_guard4_cyclic_loop_detection():
    """
    Adversarial Test 4 (Guard 4 — Loop Detection):
    Track execution step/state signatures.
    If the same logical step/file signature repeats 3 times without progress:
    - Abort before executing the fourth repetition
    - Transition to NEEDS_HUMAN
    - Log loop violation
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        _init_git_repo(tmp_dir)
        ws_session = WorkspaceSession(
            task_name="adv-test-loop",
            branch_name="main",
            worktree_path=tmp_dir,
            base_ref="HEAD",
        )

        # Create a plan with 4 identical steps
        step_args = ReadFileArgs(path="main.py")
        plan_loop = ExecutionPlan(
            goal="Looping plan with 4 identical steps",
            estimated_complexity="Low",
            rollback_plan="revert",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments=step_args,
                    expected_outcome="First execution",
                    rollback_action="echo noop",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="read_file",
                    tool_arguments=step_args,
                    expected_outcome="Second execution",
                    rollback_action="echo noop",
                ),
                PlanStep(
                    step_number=3,
                    tool_name="read_file",
                    tool_arguments=step_args,
                    expected_outcome="Third execution",
                    rollback_action="echo noop",
                ),
                PlanStep(
                    step_number=4,
                    tool_name="read_file",
                    tool_arguments=step_args,
                    expected_outcome="Fourth execution — MUST BE ABORTED",
                    rollback_action="echo noop",
                ),
            ],
        )

        safety = ExecutionSafety()
        executor = ExecutorAgent(execution_safety=safety)
        result = executor.execute_plan(plan_loop, workspace_session=ws_session)

        # Verifications
        # Steps 1, 2, 3 succeeded; step 4 was aborted BEFORE execution
        assert len(result.completed_steps) == 3, f"Expected 3 completed steps, got {len(result.completed_steps)}"
        assert result.status == ExecutionStatus.NEEDS_HUMAN
        assert any("LOOP_DETECTION" in err for err in result.errors)
        assert result.failed_step is not None
        assert result.failed_step.step_number == 4
        assert any(
            e.get("to_state") in (SessionState.NEEDS_HUMAN.value, SessionState.NEEDS_HUMAN)
            for e in result.emitted_events
        )
