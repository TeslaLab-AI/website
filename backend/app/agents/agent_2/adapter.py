"""
Adapter between Agent 2 ExecutionPlan and the existing FixPlan / FixStep architecture.

Allows seamless execution of ExecutionPlan via the existing execute_plan() executor
without modifying the core executor logic.
"""

from __future__ import annotations
import os
from typing import Any

from app.agents.executor import FixPlan, FixStep
from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ReadFileArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    OpenPrArgs,
)


def execution_plan_to_fix_plan(
    plan: ExecutionPlan,
    workspace_root: str | None = None,
    file_cache: dict[str, str] | None = None,
) -> FixPlan:
    """
    Convert an Engineer 2 ExecutionPlan to a backward-compatible FixPlan
    so it can be executed by app.agents.executor.execute_plan.
    """
    fix_steps: list[FixStep] = []
    cache = dict(file_cache or {})

    for step in plan.steps:
        args = (
            step.tool_arguments.model_dump()
            if hasattr(step.tool_arguments, "model_dump")
            else dict(step.tool_arguments)
        )

        if step.tool_name == "read_file":
            path = args.get("path", "")
            fix_steps.append(
                FixStep(
                    action="READ",
                    file_path=path,
                    content=None,
                    delete_confirmed=False,
                )
            )

        elif step.tool_name == "apply_patch":
            path = args.get("path", "")
            orig = args.get("original_chunk", "")
            repl = args.get("replacement_chunk", "")

            # If workspace_root is provided, read the current file and apply patch
            new_content = None
            if workspace_root:
                abs_path = os.path.normpath(os.path.join(workspace_root, path))
                if os.path.isfile(abs_path):
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                        current_content = f.read()
                    if orig in current_content:
                        new_content = current_content.replace(orig, repl, 1)
                    else:
                        new_content = current_content + "\n" + repl
                    cache[path] = new_content
            elif path in cache:
                current_content = cache[path]
                if orig in current_content:
                    new_content = current_content.replace(orig, repl, 1)
                else:
                    new_content = current_content + "\n" + repl
                cache[path] = new_content
            else:
                # If no file read possible, treat replacement as content
                new_content = repl

            fix_steps.append(
                FixStep(
                    action="MODIFY",
                    file_path=path,
                    content=new_content,
                    delete_confirmed=False,
                )
            )

    if not fix_steps:
        # Fallback step if plan has no direct file edits (e.g. only tests/pr)
        for f in plan.affected_files:
            fix_steps.append(FixStep(action="READ", file_path=f, content=None))

    return FixPlan(
        steps=fix_steps,
        explanation=plan.goal,
        risk_level=plan.estimated_complexity,
    )


def fix_plan_to_execution_plan(
    fix_plan: FixPlan,
    goal: str = "Execute fix steps",
    test_command: str = "pytest",
) -> ExecutionPlan:
    """
    Convert an existing FixPlan into a validated ExecutionPlan.
    """
    steps: list[PlanStep] = []
    affected: list[str] = []
    step_num = 1

    # Add initial inspection if modify steps exist
    for fs in fix_plan.steps:
        if fs.file_path not in affected:
            affected.append(fs.file_path)

    if affected:
        steps.append(
            PlanStep(
                step_number=step_num,
                tool_name="read_file",
                tool_arguments=ReadFileArgs(path=affected[0]),
                expected_outcome=f"Read target file {affected[0]}",
                rollback_action="No rollback needed for read.",
            )
        )
        step_num += 1

    # Add reproduction test
    steps.append(
        PlanStep(
            step_number=step_num,
            tool_name="run_tests",
            tool_arguments=RunTestsArgs(test_command=test_command),
            expected_outcome="Check test status before fix.",
            rollback_action="No rollback needed for test run.",
        )
    )
    step_num += 1

    # Add patch steps
    for fs in fix_plan.steps:
        if fs.action in ("MODIFY", "CREATE") and fs.content:
            steps.append(
                PlanStep(
                    step_number=step_num,
                    tool_name="apply_patch",
                    tool_arguments=ApplyPatchArgs(
                        path=fs.file_path,
                        original_chunk="",
                        replacement_chunk=fs.content,
                        line_number=1,
                    ),
                    expected_outcome=f"Update file {fs.file_path}",
                    rollback_action=f"Revert edits to {fs.file_path}",
                )
            )
            step_num += 1

    # Add post-fix test
    steps.append(
        PlanStep(
            step_number=step_num,
            tool_name="run_tests",
            tool_arguments=RunTestsArgs(test_command=test_command),
            expected_outcome="Verify test suite passes after fix.",
            rollback_action="Revert changes if tests fail.",
        )
    )
    step_num += 1

    # Add open PR step
    steps.append(
        PlanStep(
            step_number=step_num,
            tool_name="open_pr",
            tool_arguments=OpenPrArgs(
                title=fix_plan.explanation[:50] or "Fix bug",
                branch="fix/agentic-patch",
                body=fix_plan.explanation,
            ),
            expected_outcome="Submit fix as PR.",
            rollback_action="Close PR.",
        )
    )

    return ExecutionPlan(
        goal=fix_plan.explanation or goal,
        steps=steps,
        affected_files=affected,
        estimated_complexity=fix_plan.risk_level or "Medium",
        rollback_plan="Revert changes across affected files.",
    )
