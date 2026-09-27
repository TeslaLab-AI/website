"""
Purpose:
Executor — applies a FixPlan's steps to the isolated workspace.
Supports READ, MODIFY, CREATE, DELETE* operations on files.

DELETE is marked with * because it is destructive and requires
explicit confirmation in the plan (delete_confirmed: true).
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Literal

from app.agents.sandbox import IsolatedWorkspace


@dataclass
class FixStep:
    action: Literal["READ", "MODIFY", "CREATE", "DELETE"]
    file_path: str          # Repo-relative path
    content: str | None     # New content (for MODIFY / CREATE)
    delete_confirmed: bool = False  # Must be True for DELETE to execute


@dataclass
class FixPlan:
    steps: list[FixStep]
    explanation: str        # Human-readable description of what the plan does
    risk_level: str         # Low | Medium | High


@dataclass
class ExecutionResult:
    success: bool
    changed_files: list[str]
    errors: list[str]


def execute_plan(plan: FixPlan, workspace: IsolatedWorkspace) -> ExecutionResult:
    """
    Apply each step in the FixPlan to the isolated workspace.
    Returns a summary of what changed.
    """
    changed_files: list[str] = []
    errors: list[str] = []

    for step in plan.steps:
        abs_path = workspace.resolve(step.file_path)

        if step.action == "READ":
            # READ steps are informational — no disk change needed
            continue

        elif step.action in ("MODIFY", "CREATE"):
            if step.content is None:
                errors.append(f"{step.action} step for {step.file_path} has no content.")
                continue
            try:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(step.content)
                changed_files.append(step.file_path)
                print(f"[Executor] {step.action}: {step.file_path}")
            except Exception as e:
                errors.append(f"Failed to {step.action} {step.file_path}: {e}")

        elif step.action == "DELETE":
            if not step.delete_confirmed:
                errors.append(f"DELETE of {step.file_path} skipped — delete_confirmed is False.")
                continue
            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                    changed_files.append(step.file_path)
                    print(f"[Executor] DELETE: {step.file_path}")
            except Exception as e:
                errors.append(f"Failed to DELETE {step.file_path}: {e}")

    return ExecutionResult(
        success=len(errors) == 0,
        changed_files=changed_files,
        errors=errors,
    )
