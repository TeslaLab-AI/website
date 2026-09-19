"""
Tests for Task 18: Deterministic Plan Validator.

Covers:
- Static validation BEFORE execution
- 5 valid plans accepted
- 5 deliberately malformed/dangerous plans rejected
- Required execution ordering: READ/INSPECT -> REPRODUCE -> EDIT -> TEST -> VERIFY
- Destructive command checks (rm -rf, drop table, curl | sh, git push --force)
- Protected path checks (.env, .git/, .github/workflows/, lockfiles)
- Referenced file existence checks
- Performance benchmark demonstrating < 50ms runtime
"""

import os
import tempfile
import time
import pytest

from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ReadFileArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
)
from app.agents.agent_2.validator import PlanValidator, ValidationResult, default_validator


# Helper to build a valid step sequence
def make_valid_steps(target_file: str = "app/main.py") -> list[PlanStep]:
    return [
        PlanStep(
            step_number=1,
            tool_name="read_file",
            tool_arguments=ReadFileArgs(path=target_file, start_line=1, end_line=30),
            expected_outcome="Read target file for context",
            rollback_action="No rollback needed",
        ),
        PlanStep(
            step_number=2,
            tool_name="run_tests",
            tool_arguments=RunTestsArgs(test_command="pytest tests/"),
            expected_outcome="Reproduce current failure",
            rollback_action="No rollback needed",
        ),
        PlanStep(
            step_number=3,
            tool_name="apply_patch",
            tool_arguments=ApplyPatchArgs(
                path=target_file,
                original_chunk="def hello():\n    return False",
                replacement_chunk="def hello():\n    return True",
                line_number=5,
            ),
            expected_outcome="Apply patch to hello()",
            rollback_action="Revert patch",
        ),
        PlanStep(
            step_number=4,
            tool_name="run_tests",
            tool_arguments=RunTestsArgs(test_command="pytest tests/"),
            expected_outcome="Verify tests pass post-patch",
            rollback_action="Revert patch if fail",
        ),
        PlanStep(
            step_number=5,
            tool_name="open_pr",
            tool_arguments=OpenPrArgs(
                title="fix: return True in hello",
                branch="fix/hello-return",
                body="Fixed return value.",
            ),
            expected_outcome="Create pull request",
            rollback_action="Close pull request",
        ),
    ]


class TestPlanValidator:
    """Task 18 PlanValidator test suite."""

    # ─────────────────────────────────────────────────────────
    # 5 VALID PLANS
    # ─────────────────────────────────────────────────────────

    def test_valid_plan_1_full_lifecycle(self):
        """Plan 1: Standard 5-step lifecycle (READ -> REPRODUCE -> EDIT -> TEST -> VERIFY)."""
        plan = ExecutionPlan(
            goal="Full lifecycle bug fix",
            steps=make_valid_steps("app/main.py"),
            affected_files=["app/main.py"],
            estimated_complexity="Low",
            rollback_plan="Revert main.py patch",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is True
        assert len(res.errors) == 0

    def test_valid_plan_2_search_code_inspection(self):
        """Plan 2: Inspection via search_code then edit and test."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="search_code",
                tool_arguments={"pattern": "SECRET_KEY", "path": "app/"},
                expected_outcome="Locate hardcoded secret",
                rollback_action="No rollback",
            ),
            PlanStep(
                step_number=2,
                tool_name="apply_patch",
                tool_arguments={
                    "path": "app/config.py",
                    "original_chunk": "SECRET_KEY = '123'",
                    "replacement_chunk": "SECRET_KEY = os.getenv('SECRET_KEY')",
                    "line_number": 10,
                },
                expected_outcome="Use environment variable for secret",
                rollback_action="Revert config.py patch",
            ),
            PlanStep(
                step_number=3,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest tests/test_config.py"},
                expected_outcome="Verify config loading test passes",
                rollback_action="Revert config.py patch",
            ),
        ]
        plan = ExecutionPlan(
            goal="Extract hardcoded secret into environment variable",
            steps=steps,
            affected_files=["app/config.py"],
            estimated_complexity="Medium",
            rollback_plan="Revert config.py patch",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is True
        assert len(res.errors) == 0

    def test_valid_plan_3_multi_file_read_and_patch(self):
        """Plan 3: Multiple inspect steps and verification via run_command."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": "package.json"},
                expected_outcome="Check dependency versions",
                rollback_action="No rollback",
            ),
            PlanStep(
                step_number=2,
                tool_name="read_file",
                tool_arguments={"path": "src/utils.js"},
                expected_outcome="Check helper implementation",
                rollback_action="No rollback",
            ),
            PlanStep(
                step_number=3,
                tool_name="apply_patch",
                tool_arguments={
                    "path": "src/utils.js",
                    "original_chunk": "module.exports = {};",
                    "replacement_chunk": "module.exports = { helper: () => true };",
                    "line_number": 1,
                },
                expected_outcome="Export helper function",
                rollback_action="Revert utils.js",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_command",
                tool_arguments={"command": "node --check src/utils.js"},
                expected_outcome="Verify syntax",
                rollback_action="Revert utils.js",
            ),
            PlanStep(
                step_number=5,
                tool_name="open_pr",
                tool_arguments={"title": "fix: export helper", "branch": "fix/helper", "body": "Export helper."},
                expected_outcome="Open PR for reviewed helper export",
                rollback_action="Close PR",
            ),
        ]
        plan = ExecutionPlan(
            goal="Fix helper export in utils.js",
            steps=steps,
            affected_files=["package.json", "src/utils.js"],
            estimated_complexity="Low",
            rollback_plan="Revert src/utils.js",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is True
        assert len(res.errors) == 0

    def test_valid_plan_4_reproduce_via_run_command(self):
        """Plan 4: Reproduce step using run_command before patch."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": "server.py"},
                expected_outcome="Inspect server configuration",
                rollback_action="No rollback",
            ),
            PlanStep(
                step_number=2,
                tool_name="run_command",
                tool_arguments={"command": "python server.py --check-health"},
                expected_outcome="Observe unhealthy state",
                rollback_action="No rollback",
            ),
            PlanStep(
                step_number=3,
                tool_name="apply_patch",
                tool_arguments={
                    "path": "server.py",
                    "original_chunk": "healthy = False",
                    "replacement_chunk": "healthy = True",
                    "line_number": 20,
                },
                expected_outcome="Set server health check to true",
                rollback_action="Revert server.py",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest"},
                expected_outcome="Confirm tests pass",
                rollback_action="Revert server.py",
            ),
        ]
        plan = ExecutionPlan(
            goal="Fix server health check",
            steps=steps,
            affected_files=["server.py"],
            estimated_complexity="Low",
            rollback_plan="Revert server.py",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is True
        assert len(res.errors) == 0

    def test_valid_plan_5_verified_against_real_workspace(self):
        """Plan 5: Valid plan with real workspace directory and existing files."""
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, "app"), exist_ok=True)
            main_py = os.path.join(ws, "app", "main.py")
            with open(main_py, "w", encoding="utf-8") as f:
                f.write("def hello():\n    return False\n")

            plan = ExecutionPlan(
                goal="Fix hello function with workspace existence validation",
                steps=make_valid_steps("app/main.py"),
                affected_files=["app/main.py"],
                estimated_complexity="Low",
                rollback_plan="Revert app/main.py",
            )
            res = default_validator.validate(plan, workspace_root=ws)
            assert res.is_valid is True
            assert len(res.errors) == 0

    # ─────────────────────────────────────────────────────────
    # 5 DELIBERATELY MALFORMED / DANGEROUS PLANS
    # ─────────────────────────────────────────────────────────

    def test_invalid_plan_1_destructive_command(self):
        """Rejection: Destructive command (rm -rf, drop table, git push --force, curl | sh)."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": "app/main.py"},
                expected_outcome="Read",
                rollback_action="None",
            ),
            PlanStep(
                step_number=2,
                tool_name="run_command",
                tool_arguments={"command": "rm -rf /var/log/*"},
                expected_outcome="Clean logs",
                rollback_action="None",
            ),
            PlanStep(
                step_number=3,
                tool_name="apply_patch",
                tool_arguments={
                    "path": "app/main.py",
                    "original_chunk": "a",
                    "replacement_chunk": "b",
                    "line_number": 1,
                },
                expected_outcome="Patch",
                rollback_action="Revert",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest"},
                expected_outcome="Test",
                rollback_action="Revert",
            ),
        ]
        plan = ExecutionPlan(
            goal="Dangerous plan with rm -rf",
            steps=steps,
            affected_files=["app/main.py"],
            estimated_complexity="High",
            rollback_plan="Revert",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is False
        assert any("[DESTRUCTIVE_COMMAND_VIOLATION]" in e for e in res.errors)
        assert any("rm -rf" in e for e in res.errors)

    def test_invalid_plan_2_protected_path(self):
        """Rejection: Attempt to access or modify .env, .git, or package-lock.json."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": ".env"},
                expected_outcome="Steal secrets",
                rollback_action="None",
            ),
            PlanStep(
                step_number=2,
                tool_name="apply_patch",
                tool_arguments={
                    "path": ".env",
                    "original_chunk": "API_KEY=123",
                    "replacement_chunk": "API_KEY=456",
                    "line_number": 1,
                },
                expected_outcome="Modify env",
                rollback_action="None",
            ),
            PlanStep(
                step_number=3,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest"},
                expected_outcome="Test",
                rollback_action="None",
            ),
        ]
        plan = ExecutionPlan(
            goal="Forbidden plan touching .env",
            steps=steps,
            affected_files=[".env"],
            estimated_complexity="Critical",
            rollback_plan="Revert",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is False
        assert any("[PROTECTED_PATH_VIOLATION]" in e for e in res.errors)
        assert any(".env" in e for e in res.errors)

    def test_invalid_plan_3_backwards_ordering(self):
        """Rejection: EDIT followed by READ (violates READ -> EDIT ordering)."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": "app/a.py"},
                expected_outcome="Read a.py",
                rollback_action="None",
            ),
            PlanStep(
                step_number=2,
                tool_name="apply_patch",
                tool_arguments={
                    "path": "app/a.py",
                    "original_chunk": "x = 1",
                    "replacement_chunk": "x = 2",
                    "line_number": 10,
                },
                expected_outcome="Patch a.py",
                rollback_action="Revert",
            ),
            PlanStep(
                step_number=3,
                tool_name="read_file",  # BACKWARDS: READ after EDIT
                tool_arguments={"path": "app/b.py"},
                expected_outcome="Read b.py too late",
                rollback_action="None",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest"},
                expected_outcome="Test",
                rollback_action="Revert",
            ),
        ]
        plan = ExecutionPlan(
            goal="Invalid ordering plan",
            steps=steps,
            affected_files=["app/a.py", "app/b.py"],
            estimated_complexity="Medium",
            rollback_plan="Revert",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is False
        assert any("[INVALID_EXECUTION_ORDER]" in e for e in res.errors)

    def test_invalid_plan_4_invalid_step_numbering(self):
        """Rejection: Step numbering has a gap or starts at wrong index."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": "app/main.py"},
                expected_outcome="Read",
                rollback_action="None",
            ),
            PlanStep(
                step_number=3,  # GAP: skipped 2!
                tool_name="apply_patch",
                tool_arguments={
                    "path": "app/main.py",
                    "original_chunk": "a",
                    "replacement_chunk": "b",
                    "line_number": 1,
                },
                expected_outcome="Patch",
                rollback_action="Revert",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest"},
                expected_outcome="Test",
                rollback_action="Revert",
            ),
        ]
        plan = ExecutionPlan(
            goal="Non-sequential step numbers",
            steps=steps,
            affected_files=["app/main.py"],
            estimated_complexity="Low",
            rollback_plan="Revert",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is False
        assert any("[INVALID_STEP_NUMBERING]" in e for e in res.errors)

    def test_invalid_plan_5_referenced_file_not_found(self):
        """Rejection: File referenced in read_file or apply_patch does not exist on disk."""
        with tempfile.TemporaryDirectory() as ws:
            plan = ExecutionPlan(
                goal="Referencing ghost file",
                steps=[
                    PlanStep(
                        step_number=1,
                        tool_name="read_file",
                        tool_arguments={"path": "app/ghost_file.py"},
                        expected_outcome="Read ghost",
                        rollback_action="None",
                    ),
                    PlanStep(
                        step_number=2,
                        tool_name="apply_patch",
                        tool_arguments={
                            "path": "app/ghost_file.py",
                            "original_chunk": "x = 1",
                            "replacement_chunk": "x = 2",
                            "line_number": 1,
                        },
                        expected_outcome="Patch ghost",
                        rollback_action="None",
                    ),
                    PlanStep(
                        step_number=3,
                        tool_name="run_tests",
                        tool_arguments={"test_command": "pytest"},
                        expected_outcome="Test",
                        rollback_action="None",
                    ),
                ],
                affected_files=["app/ghost_file.py"],
                estimated_complexity="Low",
                rollback_plan="None",
            )
            res = default_validator.validate(plan, workspace_root=ws)
            assert res.is_valid is False
            assert any("[FILE_NOT_FOUND]" in e for e in res.errors)
            assert any("ghost_file.py" in e for e in res.errors)

    # ─────────────────────────────────────────────────────────
    # PERFORMANCE BENCHMARK (< 50ms)
    # ─────────────────────────────────────────────────────────

    def test_validator_benchmark_under_50ms(self):
        """Benchmark: Ensure validator runs in < 50ms per plan (target < 50ms, typically < 1ms)."""
        plan = ExecutionPlan(
            goal="Benchmark plan",
            steps=make_valid_steps("app/main.py"),
            affected_files=["app/main.py"],
            estimated_complexity="Low",
            rollback_plan="Revert",
        )

        # Warmup
        for _ in range(10):
            default_validator.validate(plan)

        # Benchmark 500 iterations
        iterations = 500
        start = time.perf_counter()
        for _ in range(iterations):
            res = default_validator.validate(plan)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / iterations) * 1000
        print(f"\n[BENCHMARK] PlanValidator average runtime: {avg_ms:.3f} ms across {iterations} runs")

        assert avg_ms < 50.0, f"Validator average runtime {avg_ms:.2f}ms exceeded 50ms SLA"
        # Even stricter assertion: static checks should easily run in under 5ms
        assert avg_ms < 10.0, f"Validator took {avg_ms:.2f}ms, expected under 10ms"

    def test_destructive_command_force_push_variants(self):
        """Audit #7: Verify rejection of various force push variants."""
        variants = [
            "git push origin main --force",
            "git push origin main -f",
            "git push origin main --force-with-lease",
            "git push origin +main",
            "git push origin +refs/heads/main",
        ]
        for cmd in variants:
            plan = ExecutionPlan(
                goal="Test force push rejection",
                steps=[
                    PlanStep(
                        step_number=1,
                        tool_name="read_file",
                        tool_arguments={"path": "app/main.py"},
                        expected_outcome="Read",
                        rollback_action="None",
                    ),
                    PlanStep(
                        step_number=2,
                        tool_name="run_command",
                        tool_arguments={"command": cmd},
                        expected_outcome="Push",
                        rollback_action="None",
                    ),
                ],
                affected_files=["app/main.py"],
                estimated_complexity="High",
                rollback_plan="None",
            )
            res = default_validator.validate(plan)
            assert res.is_valid is False, f"Failed to reject command: {cmd}"
            assert any("[DESTRUCTIVE_COMMAND_VIOLATION]" in e for e in res.errors)

    def test_ordering_prevent_verify_before_test(self):
        """Audit #4: Verify open_pr (VERIFY) before run_tests (TEST) is rejected."""
        plan = ExecutionPlan(
            goal="Premature PR before test verification",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments={"path": "app/main.py"},
                    expected_outcome="Read",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="apply_patch",
                    tool_arguments={
                        "path": "app/main.py",
                        "original_chunk": "x = 1",
                        "replacement_chunk": "x = 2",
                        "line_number": 1,
                    },
                    expected_outcome="Patch",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=3,
                    tool_name="open_pr",  # VERIFY before TEST
                    tool_arguments={"title": "Premature PR", "branch": "fix/premature", "body": "desc"},
                    expected_outcome="Open PR too early",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=4,
                    tool_name="run_tests",  # TEST after VERIFY (backward transition)
                    tool_arguments={"test_command": "pytest"},
                    expected_outcome="Test too late",
                    rollback_action="None",
                ),
            ],
            affected_files=["app/main.py"],
            estimated_complexity="Medium",
            rollback_plan="None",
        )
        res = default_validator.validate(plan)
        assert res.is_valid is False
        assert any("[INVALID_EXECUTION_ORDER]" in e for e in res.errors)
        assert any("cannot execute after VERIFY" in e for e in res.errors)
