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
        router: Any = None,
        gateway: Any = None,
    ) -> None:
        self.validator = validator or default_validator
        self.client = openai_client
        self.model = model
        self.router = router
        self.gateway = gateway

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

    def _build_prompts(
        self,
        rca: RootCauseAnalysis,
        context: ContextPack,
    ) -> tuple[str, str]:
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

        user_prompt = (
            f"Generate an ExecutionPlan for this issue:\n"
            f"Title: {rca.title}\n"
            f"File: {rca.file_path}:{rca.line_number}\n"
            f"Description: {rca.description}\n"
            f"Root Cause: {rca.root_cause}\n"
            f"Suggested Fix: {rca.suggested_fix}\n"
            f"Severity: {rca.severity}\n\n"
            f"File Content ({rca.file_path}):\n"
            f"{context.file_content[:3000]}\n\n"
            f"Test Command: {context.test_command or 'pytest'}\n"
        )
        return system_prompt, user_prompt

    def plan_with_metadata(
        self,
        rca: RootCauseAnalysis,
        context: ContextPack,
        workspace_root: str | None = None,
        max_validation_retries: int = 2,
        router: Any = None,
        gateway: Any = None,
        complexity_hint: str | None = None,
    ) -> tuple[ExecutionPlan, dict[str, Any]]:
        """
        Execute full planning pipeline:
        RootCauseAnalysis -> ModelRouter -> PlannerAgent -> ExecutionPlan -> PlanValidator
        Returns (ExecutionPlan, metadata_dict).
        """
        import time
        start_time = time.perf_counter()

        effective_router = router or self.router
        effective_gateway = gateway or self.gateway

        # 1. ModelRouter model selection
        route = None
        if effective_router is not None:
            route = effective_router.get_model_for_task(
                task_type="planning",
                complexity_hint=complexity_hint,
            )
        else:
            try:
                from app.agents.agent_2.router import default_router
                route = default_router.get_model_for_task(
                    task_type="planning",
                    complexity_hint=rca.severity,
                )
            except Exception:
                from app.agents.agent_2.router.models import ModelRoute
                route = ModelRoute(
                    task_type="planning",
                    tier="strong",
                    model=self.model,
                    provider="openai",
                    fallback_model="claude-3-5-sonnet",
                    reason="Default strong planning tier",
                )

        selected_model = route.model if route else self.model
        selected_tier = route.tier if route else "strong"
        selected_provider = route.provider if route else "openai"

        # 2. Plan Generation
        plan = None
        llm_response = None

        # Try LLMGateway if available
        if effective_gateway is not None:
            try:
                system_prompt, user_prompt = self._build_prompts(rca, context)
                llm_response = effective_gateway.complete(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=selected_model,
                    temperature=0.1,
                    max_tokens=2048,
                    json_schema=ExecutionPlan,
                    fallback_model=route.fallback_model if route else None,
                )
                if llm_response and llm_response.parsed:
                    plan = ExecutionPlan(**llm_response.parsed)
                elif llm_response and llm_response.content:
                    plan = ExecutionPlan.model_validate_json(llm_response.content)
            except Exception:
                plan = None

        # If gateway didn't produce plan, try client or deterministic
        if plan is None:
            client = self._get_client()
            if client:
                plan = self._generate_plan_with_llm(client, rca, context)
            else:
                plan = self._generate_deterministic_plan(rca, context)

        # 3. Static Plan Validation on initial attempt
        initial_val_result = self.validator.validate(plan, workspace_root=workspace_root)
        first_attempt_pass = initial_val_result.is_valid

        validation_result = initial_val_result
        if not validation_result.is_valid:
            client = self._get_client()
            if client and max_validation_retries > 0:
                plan = self._replan_with_errors(client, rca, context, plan, validation_result.errors)
                validation_result = self.validator.validate(plan, workspace_root=workspace_root)

            if not validation_result.is_valid:
                error_msg = "; ".join(validation_result.errors)
                raise ValueError(f"[PLANNER_VALIDATION_FAILED] Generated plan failed validation: {error_msg}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Calculate token counts and cost
        prompt_tokens = llm_response.usage.prompt_tokens if llm_response and llm_response.usage else 0
        completion_tokens = llm_response.usage.completion_tokens if llm_response and llm_response.usage else 0
        cached_tokens = llm_response.usage.cached_tokens if llm_response and llm_response.usage else 0

        cost_usd = 0.0
        if effective_gateway and effective_gateway.cost_tracker:
            recent_records = effective_gateway.cost_tracker.get_all_records()
            if recent_records:
                cost_usd = recent_records[-1].cost_usd

        if cost_usd == 0.0 and (prompt_tokens > 0 or completion_tokens > 0):
            try:
                from app.agents.agent_2.cost.calculator import default_calculator
                breakdown = default_calculator.calculate_cost(
                    model=selected_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                )
                cost_usd = breakdown.total_cost_usd
            except Exception:
                pass

        metadata = {
            "route": route,
            "selected_tier": selected_tier,
            "selected_model": selected_model,
            "selected_provider": selected_provider,
            "first_attempt_pass": first_attempt_pass,
            "validation_result": validation_result,
            "validation_errors": validation_result.errors,
            "planning_latency_ms": elapsed_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": cost_usd,
            "llm_response": llm_response,
        }

        return plan, metadata

    def plan(
        self,
        rca: RootCauseAnalysis,
        context: ContextPack,
        workspace_root: str | None = None,
        max_validation_retries: int = 2,
        router: Any = None,
        gateway: Any = None,
        complexity_hint: str | None = None,
    ) -> ExecutionPlan:
        """
        Generate an ExecutionPlan from RootCauseAnalysis and ContextPack.
        The plan is guaranteed to be validated by PlanValidator before returning.
        """
        plan, _ = self.plan_with_metadata(
            rca=rca,
            context=context,
            workspace_root=workspace_root,
            max_validation_retries=max_validation_retries,
            router=router,
            gateway=gateway,
            complexity_hint=complexity_hint,
        )
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
        if rca.suggested_fix and not rca.suggested_fix.strip().startswith("#"):
            indent = orig_line[:len(orig_line) - len(orig_line.lstrip())]
            replacement_line = f"{indent}{rca.suggested_fix.strip()}"
        else:
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
            f"Return JSON matching ExecutionPlan schema:\n{json.dumps(ExecutionPlan.model_json_schema(), indent=2)}"
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
                {"role": "system", "content": f"You fix invalid execution plans. Output JSON only matching this schema:\n{json.dumps(ExecutionPlan.model_json_schema(), indent=2)}"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        raw = json.loads(res.choices[0].message.content)
        return ExecutionPlan(**raw)


# Default Planner instance
default_planner = PlannerAgent()
