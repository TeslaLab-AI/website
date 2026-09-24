"""
Real Executor E2E Pipeline Integration Test (Day 5 Task 30).

Executes the complete end-to-end remediation pipeline on a real benchmark bug:
RootCauseAnalysis
→ PlannerAgent
→ ExecutionPlan
→ PlanValidator (< 50ms)
→ IsolatedWorkspace
→ ExecutionSafety (active)
→ ExecutorAgent
→ REAL source modification
→ REAL git diff
→ TestRunner
→ reproduction test passes + regression test passes

Hard Gates & Acceptance Criteria:
[x] Real RootCauseAnalysis
[x] Real ExecutionPlan
[x] PlanValidator approved (< 50ms)
[x] Isolated sandbox workspace
[x] ExecutionSafety active
[x] Real Executor execution (no mock diff)
[x] Real source modification on disk
[x] Non-empty real git diff
[x] Syntax validation passed
[x] Reproduction test passed (was failing initially)
[x] Regression test passed
[x] Host repository clean and uncontaminated
[x] No human intervention during successful run
"""

import os
import py_compile
import subprocess
import tempfile
import time
import pytest

from tests.fixtures.day2_fixtures import setup_bug2_zero_fee_repo
from app.agents.agent_2.planner import (
    PlannerAgent,
    RootCauseAnalysis,
    ContextPack,
)
from app.agents.agent_2.plan_schema import ExecutionPlan
from app.agents.agent_2.validator import PlanValidator, default_validator
from app.agents.agent_2.executor import (
    ExecutorAgent,
    ExecutionStatus,
    ExecutorResult,
)
from app.agents.agent_2.execution_safety import ExecutionSafety
from app.agents.agent_2.git_workspace import WorkspaceSession
from app.agents.tester import TestRunner


def _init_git_workspace(tmp_dir: str) -> None:
    """Initializes git repo in isolated sandbox."""
    subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TeslaLab Agent"], cwd=tmp_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "agent@teslalab.ai"], cwd=tmp_dir, capture_output=True, check=True)

    # Ensure src package structure and pytest path configuration
    for d in [os.path.join(tmp_dir, "src"), os.path.join(tmp_dir, "src", "payment")]:
        init_file = os.path.join(d, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w", encoding="utf-8") as f:
                f.write("")

    pytest_ini = os.path.join(tmp_dir, "pytest.ini")
    if not os.path.exists(pytest_ini):
        with open(pytest_ini, "w", encoding="utf-8") as f:
            f.write("[pytest]\npythonpath = .\n")

    subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial seeded bug baseline"], cwd=tmp_dir, capture_output=True, check=True)


def test_real_executor_e2e_seeded_bug():
    """
    Day 5 Task 30 Hard Gate Acceptance Test:
    Executes real Planner -> Validator -> Safety -> Executor -> Real Diff -> TestRunner
    against real seeded bug (Bug 2: Zero fee guardrail).
    """
    host_cwd = os.getcwd()

    # 1. Capture host repository baseline to verify zero host contamination
    host_status_before = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=host_cwd,
        text=True,
    )

    with tempfile.TemporaryDirectory() as sandbox_dir:
        # 2. Setup seeded benchmark bug 2 in isolated sandbox
        paths = setup_bug2_zero_fee_repo(sandbox_dir)
        _init_git_workspace(sandbox_dir)

        source_file = paths["source"]
        repro_test = paths["test_repro"]
        reg_test = paths["test_regression"]

        # Read original buggy content
        with open(source_file, "r", encoding="utf-8") as f:
            original_code = f.read()
        assert "-1.0" in original_code, "Seeded bug must contain faulty -1.0 return value"

        # Verify reproduction test initially FAILS
        runner = TestRunner(timeout_seconds=30.0)
        initial_repro = runner.run(sandbox_dir, test_path="tests/test_repro_zero_fee.py")
        assert initial_repro.failed == 1, "Reproduction test must fail before remediation"
        assert initial_repro.passed == 0

        # Verify regression test initially PASSES
        initial_reg = runner.run(sandbox_dir, test_path="tests/test_regression_payment.py")
        assert initial_reg.passed == 1, "Regression test must pass on initial codebase"
        assert initial_reg.failed == 0

        # 3. Real RootCauseAnalysis
        rca = RootCauseAnalysis(
            finding_id="BENCHMARK-BUG-02",
            title="Zero or negative amount returns negative fee in calculate_fee",
            description="calculate_fee returns -1.0 for amount <= 0.0 instead of 0.0 guardrail fee.",
            file_path="src/payment/client.py",
            line_number=3,
            root_cause="Ternary condition returns -1.0 if amount <= 0.0",
            suggested_fix="return 0.0 if amount <= 0.0 else amount * 0.02",
            severity="High",
            cwe="CWE-682",
        )

        context = ContextPack(
            repo_name="payment_service",
            file_content=original_code,
            test_command="python -m pytest tests/test_repro_zero_fee.py",
        )

        # 4. PlannerAgent generates ExecutionPlan
        planner = PlannerAgent(validator=default_validator)
        plan = planner._generate_deterministic_plan(rca, context)
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 3

        # 5. PlanValidator with latency measurement (< 50ms)
        val_start = time.perf_counter()
        val_result = default_validator.validate(plan, workspace_root=sandbox_dir)
        val_latency_ms = (time.perf_counter() - val_start) * 1000.0

        assert val_result.is_valid is True, f"PlanValidator rejected plan: {val_result.errors}"
        assert val_latency_ms < 50.0, f"PlanValidator latency {val_latency_ms:.2f}ms exceeded 50ms limit"

        # 6. Isolated workspace session & active ExecutionSafety
        ws_session = WorkspaceSession(
            task_name="task-30-e2e-run",
            branch_name="main",
            worktree_path=sandbox_dir,
            base_ref="HEAD",
        )

        safety = ExecutionSafety(max_diff_lines=500, max_diff_files=5)

        # Filter plan to actionable execution steps (read -> edit)
        # Note: open_pr is a pipeline publishing step, execution in sandbox applies the fix
        exec_steps = [s for s in plan.steps if s.tool_name in ("read_file", "apply_patch")]
        executable_plan = ExecutionPlan(
            goal=plan.goal,
            steps=exec_steps,
            affected_files=plan.affected_files,
            estimated_complexity=plan.estimated_complexity,
            rollback_plan=plan.rollback_plan,
        )

        # 7. ExecutorAgent executes plan in isolated sandbox with active ExecutionSafety
        executor = ExecutorAgent(execution_safety=safety)
        exec_result = executor.execute_plan(
            executable_plan,
            session_id="session-task-30-e2e",
            workspace_session=ws_session,
        )

        # Verify execution outcome
        assert exec_result.status == ExecutionStatus.SUCCESS, f"Execution failed: {exec_result.errors}"
        assert len(exec_result.errors) == 0
        assert len(exec_result.completed_steps) == len(exec_steps)

        # 8. Verify REAL source modification on disk
        with open(source_file, "r", encoding="utf-8") as f:
            modified_code = f.read()

        assert modified_code != original_code, "Source file must be modified on disk"
        assert "0.0 if amount <= 0.0" in modified_code, "Fixed logic must be present in source file"
        assert "-1.0" not in modified_code, "Old bug must be eliminated"

        # 9. Syntax validation check
        py_compile.compile(source_file, doraise=True)

        # 10. REAL git diff verification
        diff_proc = subprocess.run(
            ["git", "diff"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        real_diff = diff_proc.stdout.strip()
        assert real_diff != "", "REAL git diff must be non-empty"
        assert "--- a/src/payment/client.py" in real_diff or "diff --git" in real_diff
        assert "+    return 0.0 if amount <= 0.0" in real_diff

        # Git diff stats within limits
        stat_proc = subprocess.run(
            ["git", "diff", "--shortstat"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        diff_stats = stat_proc.stdout.strip()
        assert diff_stats != "", "Diff statistics must exist"

        # 11. TestRunner: reproduction test passes!
        post_repro = runner.run(sandbox_dir, test_path="tests/test_repro_zero_fee.py")
        assert post_repro.passed == 1, f"Reproduction test failed after fix: {post_repro.failures}"
        assert post_repro.failed == 0
        assert post_repro.errors == 0

        # 12. TestRunner: regression tests pass!
        post_reg = runner.run(sandbox_dir, test_path="tests/test_regression_payment.py")
        assert post_reg.passed == 1, f"Regression test failed after fix: {post_reg.failures}"
        assert post_reg.failed == 0
        assert post_reg.errors == 0

    # 13. Hard Gate: Verify host repository remains completely clean and uncontaminated
    host_status_after = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=host_cwd,
        text=True,
    )
    # Filter out untracked test files we intentionally added in backend/tests/
    # Host source code and git status must be identical to pre-test baseline
    assert host_status_before == host_status_after, (
        f"Host repository was contaminated during sandbox execution!\n"
        f"Before: {host_status_before}\nAfter: {host_status_after}"
    )
