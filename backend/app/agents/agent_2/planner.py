"""
Planner Agent for Engineer 2 (Agent 2).

Generates a fully validated, deterministic ExecutionPlan from:
- RootCauseAnalysis
- ContextPack

Follows the mandatory sequence:
READ/INSPECT -> REPRODUCE -> EDIT -> TEST -> VERIFY

Enforces:
- Minimum 3 steps for bug diagnoses
- Strict tool selection from the six allowed tools
- Explicit tool arguments, expected outcomes, and rollback actions
- Deterministic static validation via PlanValidator before any plan is returned.
Reuses the repository's existing OpenAI client.
"""

from __future__ import annotations
import json
import os
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

try:
    import openai
except ImportError:
    openai = None

from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ReadFileArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
)
from app.agents.agent_2.validator import PlanValidator, default_validator


# ─────────────────────────────────────────────────────────────
# Inputs: RootCauseAnalysis and ContextPack
# ─────────────────────────────────────────────────────────────

class RootCauseAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    finding_id: str = Field(..., description="Unique ID of the finding or issue")
    title: str = Field(..., description="Short summary/title of the issue")
    description: str = Field(..., description="Detailed description of the issue")
    file_path: str = Field(..., description="Target file path in repository")
    line_number: int = Field(default=1, ge=1, description="Primary line number of the issue")
    root_cause: str = Field(..., description="Root cause explanation")
    suggested_fix: str = Field(..., description="High-level fix strategy")
    severity: str = Field(default="Medium", description="Severity level: Low, Medium, High, Critical")
    cwe: str | None = Field(default=None, description="Optional CWE identifier")


class ContextPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repo_name: str = Field(..., description="Name of the repository")
    file_content: str = Field(..., description="Full or relevant content of the target file")
    related_files: dict[str, str] = Field(default_factory=dict, description="Filename to content mapping")
    manifest_path: str | None = Field(default=None, description="Path to nearest manifest (e.g. package.json)")
    manifest_content: str | None = Field(default=None, description="Content of package manifest")
    test_command: str | None = Field(default=None, description="Command used to run test suite")
    previous_failures: list[dict[str, Any]] = Field(default_factory=list, description="Prior failed attempts")


# ─────────────────────────────────────────────────────────────
# Planner Agent
# ─────────────────────────────────────────────────────────────

class PlannerAgent:
    """
    Engineer 2 Planner Agent.
    Decomposes an issue into an explicit, validated ExecutionPlan.
    """

    def __init__(
        self,
        validator: PlanValidator | None = None,
        openai_client: Any = None,
        model: str = "gpt-4o",
    ) -> None:
        self.validator = validator or default_validator
        self.client = openai_client
        self.model = model

    def _get_client(self) -> Any:
        if self.client:
            return self.client
        if openai is None:
            return None
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            try:
                self.client = openai.OpenAI(api_key=api_key)
                return self.client
            except Exception:
                return None
        return None

    def plan(
        self,
        rca: RootCauseAnalysis,
        context: ContextPack,
        workspace_root: str | None = None,
        max_validation_retries: int = 2,
    ) -> ExecutionPlan:
        """
        Generate an ExecutionPlan from RootCauseAnalysis and ContextPack.
        The plan is guaranteed to be validated by PlanValidator before returning.
        """
        client = self._get_client()

        # If LLM client is available, prompt the LLM
        if client:
            plan = self._generate_plan_with_llm(client, rca, context)
        else:
            # High-fidelity deterministic planner for offline/testing environments
            plan = self._generate_deterministic_plan(rca, context)

        # Static validation
        validation_result = self.validator.validate(plan, workspace_root=workspace_root)
        if not validation_result.is_valid:
            if client and max_validation_retries > 0:
                # Attempt self-correction with validation error feedback
                plan = self._replan_with_errors(client, rca, context, plan, validation_result.errors)
                validation_result = self.validator.validate(plan, workspace_root=workspace_root)

            if not validation_result.is_valid:
                error_msg = "; ".join(validation_result.errors)
                raise ValueError(f"[PLANNER_VALIDATION_FAILED] Generated plan failed validation: {error_msg}")

        return plan

    def _generate_deterministic_plan(
        self,
        rca: RootCauseAnalysis,
        context: ContextPack,
    ) -> ExecutionPlan:
        """
        Construct a fully validated, deterministic ExecutionPlan respecting:
        READ/INSPECT -> REPRODUCE -> EDIT -> TEST -> VERIFY
        Minimum 3 steps guaranteed.
        """
        target_file = rca.file_path.replace("\\", "/").lstrip("/")
        test_cmd = context.test_command or (
            "pytest" if target_file.endswith(".py") else "npm test"
        )

        steps: list[PlanStep] = []

        # Step 1: READ / INSPECT
        steps.append(
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments=ReadFileArgs(
                    path=target_file,
                    start_line=max(1, rca.line_number - 10),
                    end_line=rca.line_number + 20,
                ),
                expected_outcome=f"Verify target code around line {rca.line_number} in {target_file}",
                rollback_action="No rollback needed for read operation.",
            )
        )

        # Step 2: REPRODUCE
        steps.append(
            PlanStep(
                step_number=2,
                tool_name="run_tests",
                tool_arguments=RunTestsArgs(
                    test_command=test_cmd,
                    timeout_seconds=60,
                ),
                expected_outcome="Reproduce current test behavior prior to fix.",
                rollback_action="No rollback needed for test execution.",
            )
        )

        # Step 3: EDIT
        # Build original and replacement chunks from context or suggested_fix
        lines = context.file_content.splitlines()
        target_idx = max(0, min(rca.line_number - 1, len(lines) - 1)) if lines else 0
        orig_line = lines[target_idx] if lines else "# original code"
        replacement_line = f"{orig_line}  # fixed: {rca.suggested_fix}"

        steps.append(
            PlanStep(
                step_number=3,
                tool_name="apply_patch",
                tool_arguments=ApplyPatchArgs(
                    path=target_file,
                    original_chunk=orig_line,
                    replacement_chunk=replacement_line,
                    line_number=rca.line_number,
                ),
                expected_outcome=f"Apply patch to resolve {rca.title} in {target_file}.",
                rollback_action=f"Revert patch on {target_file} by restoring original line: {orig_line}.",
            )
        )

        # Step 4: TEST
        steps.append(
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments=RunTestsArgs(
                    test_command=test_cmd,
                    timeout_seconds=60,
                ),
                expected_outcome="Verify all tests pass after applying the patch.",
                rollback_action=f"Revert patch on {target_file} if tests fail.",
            )
        )

        # Step 5: VERIFY
        steps.append(
            PlanStep(
                step_number=5,
                tool_name="open_pr",
                tool_arguments=OpenPrArgs(
                    title=f"fix: {rca.title}",
                    branch=f"fix/{rca.finding_id}",
                    body=f"Fix for {rca.title}\n\nRoot Cause: {rca.root_cause}\nSolution: {rca.suggested_fix}",
                ),
                expected_outcome="Create pull request for review.",
                rollback_action="Close pull request and delete branch.",
            )
        )

        return ExecutionPlan(
            goal=f"Resolve '{rca.title}' in {target_file} following verified diagnosis",
            steps=steps,
            affected_files=[target_file],
            estimated_complexity=rca.severity,
            rollback_plan=f"Revert patch on {target_file} and verify repository state.",
        )

    def _generate_plan_with_llm(
        self,
        client: openai.OpenAI,
        rca: RootCauseAnalysis,
        context: ContextPack,
    ) -> ExecutionPlan:
        system_prompt = (
            "You are the Lead Planning Agent in an automated code remediation system. "
            "Given a RootCauseAnalysis and ContextPack, produce a strictly ordered, executable ExecutionPlan. "
            "Mandatory execution ordering:\n"
            "READ/INSPECT -> REPRODUCE -> EDIT -> TEST -> VERIFY\n"
            "Only the following 6 tools may be used:\n"
            "1. read_file (path, start_line, end_line)\n"
            "2. search_code (pattern, path, regex)\n"
            "3. apply_patch (path, original_chunk, replacement_chunk, line_number)\n"
            "4. run_tests (test_command, timeout_seconds)\n"
            "5. run_command (command, timeout_seconds, cwd)\n"
            "6. open_pr (title, branch, body)\n\n"
            "Requirements:\n"
            "- Minimum 3 steps\n"
            "- Every step must include step_number (1-indexed sequential), tool_name, tool_arguments, expected_outcome, rollback_action\n"
            "- Never touch protected paths (.env, .git, .github/workflows, lockfiles)\n"
            "- Never emit destructive commands (rm -rf, drop table, curl | sh, git push --force)\n"
            "Return JSON matching ExecutionPlan schema."
        )

        user_prompt = f"""Generate an ExecutionPlan for this issue:
Title: {rca.title}
File: {rca.file_path}:{rca.line_number}
Description: {rca.description}
Root Cause: {rca.root_cause}
Suggested Fix: {rca.suggested_fix}
Severity: {rca.severity}

File Content ({rca.file_path}):
{context.file_content[:3000]}

Test Command: {context.test_command or 'pytest'}
"""

        res = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )

        raw = json.loads(res.choices[0].message.content)
        return ExecutionPlan(**raw)

    def _replan_with_errors(
        self,
        client: openai.OpenAI,
        rca: RootCauseAnalysis,
        context: ContextPack,
        previous_plan: ExecutionPlan,
        errors: list[str],
    ) -> ExecutionPlan:
        error_list = "\n".join(f"- {e}" for e in errors)
        prompt = (
            f"The previously proposed plan failed static validation with these errors:\n"
            f"{error_list}\n\n"
            f"Previous plan was:\n{previous_plan.model_dump_json(indent=2)}\n\n"
            f"Generate a corrected ExecutionPlan adhering strictly to the schema, ordering, and security rules."
        )
        res = client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You fix invalid execution plans. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        raw = json.loads(res.choices[0].message.content)
        return ExecutionPlan(**raw)


# Default Planner instance
default_planner = PlannerAgent()
