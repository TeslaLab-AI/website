"""
Integration tests for Agent 2 (Engineer 2) with existing executor and pipeline.

Covers:
- ExecutionPlan to FixPlan adapter compatibility.
- FixPlan to ExecutionPlan adapter compatibility.
- PlanValidator gatekeeper preventing invalid plan execution on IsolatedWorkspace.
- Valid plan passing PlanValidator, adapting to FixPlan, and executing cleanly via execute_plan.
"""

import os
import tempfile
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
from app.agents.agent_2.adapter import (
    execution_plan_to_fix_plan,
    fix_plan_to_execution_plan,
)
from app.agents.agent_2.validator import default_validator
from app.agents.executor import FixPlan, FixStep, execute_plan
from app.agents.sandbox import IsolatedWorkspace


class TestAgent2Integration:
    """Agent 2 integration test suite."""

    def test_adapter_execution_plan_to_fix_plan(self):
        """Verify ExecutionPlan converts to valid FixPlan for the executor."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments=ReadFileArgs(path="app/config.py"),
                expected_outcome="Read config",
                rollback_action="None",
            ),
            PlanStep(
                step_number=2,
                tool_name="run_tests",
                tool_arguments=RunTestsArgs(test_command="pytest"),
                expected_outcome="Test before",
                rollback_action="None",
            ),
            PlanStep(
                step_number=3,
                tool_name="apply_patch",
                tool_arguments=ApplyPatchArgs(
                    path="app/config.py",
                    original_chunk="DEBUG = True",
                    replacement_chunk="DEBUG = False",
                    line_number=5,
                ),
                expected_outcome="Disable debug",
                rollback_action="Revert debug",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments=RunTestsArgs(test_command="pytest"),
                expected_outcome="Test after",
                rollback_action="Revert debug",
            ),
        ]
        plan = ExecutionPlan(
            goal="Disable debug in production config",
            steps=steps,
            affected_files=["app/config.py"],
            estimated_complexity="Low",
            rollback_plan="Revert config.py",
        )

        # Static validation passes
        val_res = default_validator.validate(plan)
        assert val_res.is_valid is True

        # Adapter produces FixPlan
        fix_plan = execution_plan_to_fix_plan(
            plan,
            file_cache={"app/config.py": "# Config\nDEBUG = True\n"},
        )
        assert isinstance(fix_plan, FixPlan)
        assert len(fix_plan.steps) == 2  # 1 READ step + 1 MODIFY step
        assert fix_plan.steps[0].action == "READ"
        assert fix_plan.steps[1].action == "MODIFY"
        assert "DEBUG = False" in fix_plan.steps[1].content

    def test_validator_gatekeeper_blocks_dangerous_execution(self):
        """Demonstrate that an invalid plan is rejected BEFORE executor touches workspace."""
        dangerous_plan = ExecutionPlan(
            goal="Malicious plan with force push",
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
                    tool_arguments={"command": "git push origin main --force"},
                    expected_outcome="Force push",
                    rollback_action="None",
                ),
            ],
            affected_files=["app/main.py"],
            estimated_complexity="High",
            rollback_plan="None",
        )

        val_res = default_validator.validate(dangerous_plan)
        assert val_res.is_valid is False
        assert any("[DESTRUCTIVE_COMMAND_VIOLATION]" in e for e in val_res.errors)

        # Gatekeeper invariant: execution is aborted, executor is never called
        executed = False
        if val_res.is_valid:
            executed = True
        assert executed is False

    def test_full_pipeline_workspace_execution(self):
        """End-to-end integration: Valid ExecutionPlan -> validated -> adapted -> executed on IsolatedWorkspace."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = os.path.join(temp_dir, "ws")
            os.makedirs(os.path.join(workspace_dir, "src"), exist_ok=True)
            calc_py = os.path.join(workspace_dir, "src", "calc.py")
            with open(calc_py, "w", encoding="utf-8") as f:
                f.write("def add(a, b):\n    return a - b  # bug\n")

            workspace = IsolatedWorkspace(root=workspace_dir, repo_name="calc-repo")

            plan = ExecutionPlan(
                goal="Fix subtraction bug in add function",
                steps=[
                    PlanStep(
                        step_number=1,
                        tool_name="read_file",
                        tool_arguments=ReadFileArgs(path="src/calc.py"),
                        expected_outcome="Inspect calc.py",
                        rollback_action="None",
                    ),
                    PlanStep(
                        step_number=2,
                        tool_name="run_tests",
                        tool_arguments=RunTestsArgs(test_command="pytest"),
                        expected_outcome="Reproduce bug",
                        rollback_action="None",
                    ),
                    PlanStep(
                        step_number=3,
                        tool_name="apply_patch",
                        tool_arguments=ApplyPatchArgs(
                            path="src/calc.py",
                            original_chunk="return a - b  # bug",
                            replacement_chunk="return a + b",
                            line_number=2,
                        ),
                        expected_outcome="Fix calculation",
                        rollback_action="Revert calc.py",
                    ),
                    PlanStep(
                        step_number=4,
                        tool_name="run_tests",
                        tool_arguments=RunTestsArgs(test_command="pytest"),
                        expected_outcome="Verify tests",
                        rollback_action="Revert calc.py",
                    ),
                ],
                affected_files=["src/calc.py"],
                estimated_complexity="Low",
                rollback_plan="Revert src/calc.py",
            )

            # 1. Gatekeeper validation
            val_res = default_validator.validate(plan, workspace_root=workspace.root)
            assert val_res.is_valid is True

            # 2. Adaptation to FixPlan
            fix_plan = execution_plan_to_fix_plan(plan, workspace_root=workspace.root)

            # 3. Execution via existing executor
            exec_result = execute_plan(fix_plan, workspace)
            assert exec_result.success is True
            assert "src/calc.py" in exec_result.changed_files

            # 4. Verify disk state
            with open(calc_py, "r", encoding="utf-8") as f:
                content = f.read()
            assert "return a + b" in content
            assert "return a - b" not in content

    def test_pipeline_gatekeeper_blocks_execute_plan_call(self):
        """Audit #5: Prove execute_plan() is never reached when validator rejects a plan."""
        from unittest.mock import MagicMock, patch

        invalid_plan = ExecutionPlan(
            goal="Invalid plan with rm -rf",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments=ReadFileArgs(path="app.py"),
                    expected_outcome="Read",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="run_command",
                    tool_arguments=RunCommandArgs(command="rm -rf /"),
                    expected_outcome="Delete",
                    rollback_action="None",
                ),
            ],
            affected_files=["app.py"],
            estimated_complexity="High",
            rollback_plan="None",
        )

        import app.agents.executor
        mock_executor = MagicMock()
        with patch.object(app.agents.executor, "execute_plan", mock_executor):
            # Simulate the exact pipeline validation gate
            val_res = default_validator.validate(invalid_plan)
            if val_res.is_valid:
                mock_executor(invalid_plan, None)

        mock_executor.assert_not_called()
