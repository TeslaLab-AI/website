"""
Deterministic Static Plan Validator for Engineer 2 (Agent 2).

Validates an ExecutionPlan BEFORE any execution takes place:
1. Referenced file existence.
2. Tool name validity.
3. Tool argument schema validity.
4. Valid step numbering and sequence.
5. Required execution ordering:
   READ / INSPECT -> REPRODUCE -> EDIT -> TEST -> VERIFY
6. Protected path checks (.env, .git/, .github/workflows/, lockfiles).
7. Destructive command checks (rm -rf, drop table, curl | sh, git push --force).

Static, deterministic, and guaranteed < 50ms runtime.
"""

from __future__ import annotations
import os
import re
from typing import Any
from pydantic import BaseModel, Field

from app.agents.agent_2.plan_schema import (
    ALLOWED_TOOLS,
    ExecutionPlan,
    PlanStep,
    TOOL_ARGUMENT_MODELS,
)
from app.agents.agent_2.tool_resolver import ToolResolver, default_resolver


class ValidationResult(BaseModel):
    is_valid: bool = Field(..., description="Whether the execution plan passed all checks")
    errors: list[str] = Field(default_factory=list, description="Descriptive error messages with tags")
    warnings: list[str] = Field(default_factory=list, description="Informational warnings")


# Protected paths pattern
PROTECTED_PATH_PATTERNS = [
    re.compile(r"(^|[/\\])\.env(\.[a-zA-Z0-9_-]+)?$", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.git([/\\]|$)", re.IGNORECASE),
    re.compile(r"(^|[/\\])\.github[/\\]workflows([/\\]|$)", re.IGNORECASE),
    re.compile(
        r"(^|[/\\])(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Pipfile\.lock|Cargo\.lock|composer\.lock)$",
        re.IGNORECASE,
    ),
]

# Destructive command patterns
DESTRUCTIVE_COMMAND_PATTERNS = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r|--recursive\s+--force|--force\s+--recursive)\b", re.IGNORECASE), "rm -rf"),
    (re.compile(r"\brmdir\s+/[sS]\b", re.IGNORECASE), "rmdir /s"),
    (re.compile(r"\bRemove-Item\b.*-Recurse.*-Force", re.IGNORECASE), "Remove-Item -Recurse -Force"),
    (re.compile(r"\bdrop\s+table\b", re.IGNORECASE), "drop table"),
    (re.compile(r"\bdrop\s+database\b", re.IGNORECASE), "drop database"),
    (re.compile(r"\btruncate\s+table\b", re.IGNORECASE), "truncate table"),
    (re.compile(r"(curl|wget)\b[^|;&\n]*\|\s*(ba|z)?sh\b", re.IGNORECASE), "curl | sh"),
    (re.compile(r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|--force-if-includes\b|-f\b|\+[a-zA-Z0-9_/-]+)", re.IGNORECASE), "git push --force"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE), "fork bomb"),
    (re.compile(r"\bmkfs(\.[a-zA-Z0-9]+)?\b", re.IGNORECASE), "mkfs"),
    (re.compile(r"\bdd\s+if=[^ ]+\s+of=/dev/", re.IGNORECASE), "dd of=/dev/"),
]

# Phase ordering mapping
# 0: READ/INSPECT
# 1: REPRODUCE
# 2: EDIT
# 3: TEST
# 4: VERIFY
PHASE_READ_INSPECT = 0
PHASE_REPRODUCE = 1
PHASE_EDIT = 2
PHASE_TEST = 3
PHASE_VERIFY = 4

PHASE_NAMES = {
    PHASE_READ_INSPECT: "READ/INSPECT",
    PHASE_REPRODUCE: "REPRODUCE",
    PHASE_EDIT: "EDIT",
    PHASE_TEST: "TEST",
    PHASE_VERIFY: "VERIFY",
}


class PlanValidator:
    """
    Deterministic static validator for ExecutionPlan instances.
    Enforces structural, security, ordering, and existence rules.
    """

    def __init__(self, resolver: ToolResolver | None = None) -> None:
        self.resolver = resolver or default_resolver

    def is_protected_path(self, path: str) -> bool:
        """Check if a file or directory path touches protected configuration/lockfiles."""
        norm = path.replace("\\", "/").strip()
        for pattern in PROTECTED_PATH_PATTERNS:
            if pattern.search(norm):
                return True
        return False

    def check_destructive_command(self, command: str) -> str | None:
        """Return the matched destructive description if found, else None."""
        for pattern, desc in DESTRUCTIVE_COMMAND_PATTERNS:
            if pattern.search(command):
                return desc
        return None

    def validate(
        self,
        plan: ExecutionPlan | dict[str, Any],
        workspace_root: str | None = None,
    ) -> ValidationResult:
        """
        Statically validate an execution plan.
        Returns a ValidationResult with is_valid, descriptive errors, and warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Parse into ExecutionPlan model if given dict
        if isinstance(plan, dict):
            try:
                plan = ExecutionPlan(**plan)
            except Exception as e:
                return ValidationResult(
                    is_valid=False,
                    errors=[f"[SCHEMA_VALIDATION_ERROR] ExecutionPlan payload invalid: {e}"],
                    warnings=[],
                )

        if not plan.steps:
            errors.append("[EMPTY_PLAN] ExecutionPlan contains no steps.")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 2. Step sequence and numbering checks
        has_edit = False
        has_read = False
        has_test_or_verify_after_edit = False
        highest_phase = -1

        for idx, step in enumerate(plan.steps):
            expected_step_num = idx + 1
            if step.step_number != expected_step_num:
                errors.append(
                    f"[INVALID_STEP_NUMBERING] Expected step number {expected_step_num}, but got {step.step_number}."
                )

            # 3. Tool name validity
            if step.tool_name not in ALLOWED_TOOLS:
                errors.append(
                    f"[INVALID_TOOL_NAME] Step {step.step_number}: Unknown tool '{step.tool_name}'. "
                    f"Allowed tools: {', '.join(sorted(ALLOWED_TOOLS))}."
                )
                continue

            # 4. Tool arguments schema validation
            try:
                args_obj = self.resolver.validate_tool_call(step.tool_name, step.tool_arguments)
            except Exception as e:
                errors.append(
                    f"[INVALID_TOOL_ARGUMENTS] Step {step.step_number} ({step.tool_name}): {e}"
                )
                continue

            args_dict = args_obj.model_dump()

            # 5. Protected path checks
            for field_name in ("path", "cwd"):
                target_path = args_dict.get(field_name)
                if target_path and self.is_protected_path(str(target_path)):
                    errors.append(
                        f"[PROTECTED_PATH_VIOLATION] Step {step.step_number} targets protected path: '{target_path}'."
                    )

            # Check commands for protected path manipulation or destructive commands
            cmd = args_dict.get("command") or args_dict.get("test_command")
            if cmd:
                cmd_str = str(cmd)
                # Check destructive commands
                destructive_match = self.check_destructive_command(cmd_str)
                if destructive_match:
                    errors.append(
                        f"[DESTRUCTIVE_COMMAND_VIOLATION] Step {step.step_number} contains forbidden command: '{destructive_match}'."
                    )

                # Check if command targets protected paths
                for token in cmd_str.split():
                    clean_token = token.strip("'\";&|<>")
                    if self.is_protected_path(clean_token):
                        errors.append(
                            f"[PROTECTED_PATH_VIOLATION] Step {step.step_number} command references protected path: '{clean_token}'."
                        )

            # 6. File existence checks (if workspace_root is provided)
            if workspace_root and os.path.isdir(workspace_root):
                file_target = args_dict.get("path")
                if file_target:
                    norm_path = os.path.normpath(os.path.join(workspace_root, str(file_target)))
                    if step.tool_name in ("read_file", "apply_patch"):
                        # For read_file, file must exist
                        # For apply_patch, if it's patching existing code (original_chunk != ""), it must exist
                        if step.tool_name == "read_file" and not os.path.isfile(norm_path):
                            errors.append(
                                f"[FILE_NOT_FOUND] Step {step.step_number} references non-existent file: '{file_target}'."
                            )
                        elif step.tool_name == "apply_patch":
                            orig = args_dict.get("original_chunk", "")
                            if orig != "" and not os.path.isfile(norm_path):
                                errors.append(
                                    f"[FILE_NOT_FOUND] Step {step.step_number} patch targets non-existent file: '{file_target}'."
                                )

            # 7. Execution Ordering Validation
            # Classify step phase:
            # - read_file, search_code -> READ/INSPECT (0)
            # - run_tests, run_command before edit -> REPRODUCE (1)
            # - apply_patch -> EDIT (2)
            # - run_tests after edit -> TEST (3)
            # - run_command after edit -> VERIFY (4)
            # - open_pr -> VERIFY (4)
            if step.tool_name in ("read_file", "search_code"):
                current_phase = PHASE_READ_INSPECT
                has_read = True
            elif step.tool_name == "apply_patch":
                current_phase = PHASE_EDIT
                has_edit = True
            elif step.tool_name == "run_tests":
                if not has_edit:
                    current_phase = PHASE_REPRODUCE
                else:
                    current_phase = PHASE_TEST
                    has_test_or_verify_after_edit = True
            elif step.tool_name == "run_command":
                if not has_edit:
                    current_phase = PHASE_REPRODUCE
                else:
                    current_phase = PHASE_VERIFY
                    has_test_or_verify_after_edit = True
            elif step.tool_name == "open_pr":
                current_phase = PHASE_VERIFY
                has_test_or_verify_after_edit = True
            else:
                current_phase = -1

            # Check ordering constraints:
            # A step cannot belong to a phase lower than the highest phase already reached
            # (i.e. cannot go backwards from EDIT to READ/INSPECT, or from VERIFY to EDIT)
            if current_phase < highest_phase:
                errors.append(
                    f"[INVALID_EXECUTION_ORDER] Step {step.step_number} ({step.tool_name} - {PHASE_NAMES.get(current_phase)}) "
                    f"cannot execute after {PHASE_NAMES.get(highest_phase)} phase."
                )

            if current_phase > highest_phase:
                highest_phase = current_phase

        # 8. Holistic ordering / completeness checks:
        # If an edit is proposed, it must have been preceded by READ/INSPECT
        if has_edit and not has_read:
            errors.append(
                "[INVALID_EXECUTION_ORDER] Plan proposes EDIT (apply_patch) without prior READ/INSPECT step."
            )

        # If an edit is proposed, it must be followed by TEST or VERIFY
        if has_edit and not has_test_or_verify_after_edit:
            errors.append(
                "[INVALID_EXECUTION_ORDER] Plan proposes EDIT (apply_patch) without subsequent TEST or VERIFY step."
            )

        # Check affected_files consistency
        for step in plan.steps:
            args = step.tool_arguments if isinstance(step.tool_arguments, dict) else step.tool_arguments.model_dump()
            p = args.get("path")
            if p and p not in plan.affected_files and step.tool_name in ("apply_patch", "read_file"):
                warnings.append(
                    f"Path '{p}' in step {step.step_number} is not listed in plan.affected_files."
                )

        is_valid = len(errors) == 0
        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


# Global default validator singleton
default_validator = PlanValidator()
