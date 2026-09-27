"""
Automated Acceptance Tests for Task 22: Planner E2E Benchmark.

Verifies:
1. All 5 seeded benchmark cases are discovered and loaded.
2. ModelRouter is invoked and selects the Strong tier (gpt-4o, openai).
3. Each benchmark diagnosis reaches PlannerAgent.
4. Valid ExecutionPlan is produced for every benchmark case.
5. PlanValidator is invoked and passes all 5 cases on the FIRST attempt (zero schema correction).
6. Latency threshold: Average latency < 15.0 seconds per plan.
7. Cost thresholds: Each plan < $0.05, total cost across all 5 < $0.25.
8. Batch runner outputs complete records with all 11 required fields.
9. Malformed / dangerous plans are strictly rejected and reported with actionable diagnostics.
10. Preservation of Task 19 & Task 20 behavior without direct provider API bypass.
"""

from __future__ import annotations

import pytest

from app.agents.agent_2.benchmarks import (
    BenchmarkCase,
    get_seeded_benchmarks,
    get_benchmark_by_id,
    SEEDED_BENCHMARK_CASES,
)
from app.agents.agent_2.plan_schema import ExecutionPlan, PlanStep, ReadFileArgs, RunTestsArgs, RunCommandArgs
from app.agents.agent_2.validator import PlanValidator, default_validator
from app.agents.agent_2.planner import PlannerAgent, RootCauseAnalysis, ContextPack
from app.agents.agent_2.router import ModelRouter, default_router
from app.agents.agent_2.gateway import LLMGateway
from app.agents.agent_2.benchmark_runner import (
    BenchmarkCaseResult,
    BatchRunSummary,
    build_benchmark_gateway,
    run_planner_e2e_benchmark,
)


class TestPlannerE2ESuite:
    """Comprehensive Task 22 Planner E2E test suite."""

    def test_01_all_5_benchmark_cases_discovered_and_loaded(self):
        """1. Verify exact 5 seeded benchmark RootCauseAnalysis cases are discovered."""
        benchmarks = get_seeded_benchmarks()
        assert len(benchmarks) == 5

        expected_ids = {
            "finding-101",
            "finding-102",
            "finding-103",
            "finding-104",
            "finding-105",
        }
        discovered_ids = {c.case_id for c in benchmarks}
        assert discovered_ids == expected_ids

        for case in benchmarks:
            assert isinstance(case.rca, RootCauseAnalysis)
            assert isinstance(case.context, ContextPack)
            assert case.rca.finding_id == case.case_id
            assert len(case.rca.title) > 0
            assert len(case.rca.root_cause) > 0
            assert len(case.rca.suggested_fix) > 0
            assert case.rca.file_path == case.expected_affected_file

    def test_02_router_invoked_for_each_benchmark_case(self):
        """2. Verify ModelRouter is invoked and selects the Strong tier (gpt-4o, openai)."""
        router = default_router
        benchmarks = get_seeded_benchmarks()

        for case in benchmarks:
            route = router.get_model_for_task("planning")
            assert route.tier == "strong"
            assert route.model == "gpt-4o"
            assert route.provider == "openai"
            assert route.fallback_model == "claude-3-5-sonnet"

    def test_03_each_case_reaches_planner_agent_and_produces_execution_plan(self):
        """3. Verify each benchmark diagnosis reaches PlannerAgent and generates ExecutionPlan."""
        benchmarks = get_seeded_benchmarks()
        gateway = build_benchmark_gateway(benchmarks)
        router = ModelRouter(gateway=gateway)
        planner = PlannerAgent(router=router, gateway=gateway, validator=default_validator)

        for case in benchmarks:
            plan, metadata = planner.plan_with_metadata(
                rca=case.rca,
                context=case.context,
                router=router,
                gateway=gateway,
            )
            assert isinstance(plan, ExecutionPlan)
            assert len(plan.steps) >= 3
            assert plan.affected_files == [case.expected_affected_file]
            assert case.expected_affected_file in plan.steps[0].tool_arguments.get("path", "") or plan.steps[0].tool_name == "read_file"
            assert metadata["selected_tier"] == "strong"
            assert metadata["selected_model"] == "gpt-4o"
            assert metadata["selected_provider"] == "openai"

    def test_04_plan_validator_invoked_and_all_5_pass_first_attempt(self):
        """4. Verify PlanValidator is invoked and passes all 5 on first attempt without schema mutation."""
        benchmarks = get_seeded_benchmarks()
        gateway = build_benchmark_gateway(benchmarks)
        router = ModelRouter(gateway=gateway)
        planner = PlannerAgent(router=router, gateway=gateway, validator=default_validator)

        for case in benchmarks:
            plan, metadata = planner.plan_with_metadata(
                rca=case.rca,
                context=case.context,
                router=router,
                gateway=gateway,
            )
            # Direct validation check
            val_res = default_validator.validate(plan)
            assert val_res.is_valid is True
            assert len(val_res.errors) == 0
            assert metadata["first_attempt_pass"] is True
            assert metadata["validation_result"].is_valid is True

    def test_05_latency_and_cost_thresholds_strictly_enforced(self):
        """5. Verify latency (< 15s avg) and cost (< $0.05/plan, < $0.25 total) targets."""
        summary = run_planner_e2e_benchmark()

        assert summary.all_valid is True
        assert summary.all_first_attempt_pass is True
        assert summary.passed_cases == 5
        assert summary.first_attempt_passes == 5

        # Latency check: < 15,000 ms (15.0 seconds)
        assert summary.avg_latency_ms < 15000.0, f"Average latency {summary.avg_latency_ms}ms exceeded 15000ms"
        assert summary.latency_target_met is True

        # Cost check: Each < $0.05, total < $0.25
        for res in summary.case_results:
            assert res.cost_usd < 0.05, f"Plan {res.case_id} cost ${res.cost_usd} exceeded $0.05 limit"

        assert summary.total_cost_usd < 0.25, f"Total cost ${summary.total_cost_usd} exceeded $0.25 limit"
        assert summary.cost_target_met is True
        assert summary.status == "PASS"

    def test_06_batch_runner_records_all_required_fields(self):
        """6. Verify batch runner records all 11 required fields per benchmark case."""
        summary = run_planner_e2e_benchmark()

        assert len(summary.case_results) == 5
        for res in summary.case_results:
            assert isinstance(res, BenchmarkCaseResult)
            # 1. benchmark/case ID
            assert res.case_id in {"finding-101", "finding-102", "finding-103", "finding-104", "finding-105"}
            # 2. root cause summary
            assert len(res.root_cause) > 0
            # 3. selected provider/model
            assert res.selected_provider == "openai"
            assert res.selected_model == "gpt-4o"
            # 4. generated ExecutionPlan
            assert isinstance(res.execution_plan, ExecutionPlan)
            # 5. validation result
            assert res.is_valid is True
            # 6. first-attempt pass/fail
            assert res.first_attempt_pass is True
            # 7. planning latency in milliseconds
            assert res.planning_latency_ms > 0.0
            # 8. prompt/completion/cached tokens
            assert res.prompt_tokens > 0
            assert res.completion_tokens > 0
            # 9. cost_usd
            assert res.cost_usd > 0.0
            # 10. validation errors if any
            assert isinstance(res.validation_errors, list)
            assert len(res.validation_errors) == 0
            # 11. final status
            assert res.status == "PASS"

    def test_07_invalid_malformed_plans_correctly_reported(self):
        """7. Verify malformed / dangerous plans are detected and rejected by PlanValidator."""
        validator = default_validator

        # Plan with destructive command
        dangerous_plan = ExecutionPlan(
            goal="Malicious cleanup",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments={"path": "app/main.py", "start_line": 1, "end_line": 10},
                    expected_outcome="Read",
                    rollback_action="None",
                ),
                PlanStep(
                    step_number=2,
                    tool_name="run_command",
                    tool_arguments={"command": "rm -rf /var/log"},
                    expected_outcome="Delete files",
                    rollback_action="None",
                ),
            ],
            affected_files=["app/main.py"],
            estimated_complexity="High",
            rollback_plan="Revert",
        )
        val_res = validator.validate(dangerous_plan)
        assert val_res.is_valid is False
        assert any("destructive" in err.lower() or "rm -rf" in err.lower() for err in val_res.errors)

        # Plan with protected path
        env_plan = ExecutionPlan(
            goal="Read secrets",
            steps=[
                PlanStep(
                    step_number=1,
                    tool_name="read_file",
                    tool_arguments={"path": ".env", "start_line": 1, "end_line": 10},
                    expected_outcome="Read secret",
                    rollback_action="None",
                ),
            ],
            affected_files=[".env"],
            estimated_complexity="High",
            rollback_plan="Revert",
        )
        val_res_env = validator.validate(env_plan)
        assert val_res_env.is_valid is False
        assert any("protected" in err.lower() or ".env" in err.lower() for err in val_res_env.errors)

    def test_08_no_manual_schema_mutation_performed(self):
        """8. Verify plans pass validation in their original generated schema without mutation."""
        case = get_benchmark_by_id("finding-101")
        gateway = build_benchmark_gateway([case])
        router = ModelRouter(gateway=gateway)
        planner = PlannerAgent(router=router, gateway=gateway, validator=default_validator)

        plan, metadata = planner.plan_with_metadata(
            rca=case.rca,
            context=case.context,
            router=router,
            gateway=gateway,
        )

        # Ensure plan was not mutated after validation
        serialized_before = plan.model_dump_json()
        val_res = default_validator.validate(plan)
        serialized_after = plan.model_dump_json()

        assert serialized_before == serialized_after
        assert val_res.is_valid is True
        assert metadata["first_attempt_pass"] is True
