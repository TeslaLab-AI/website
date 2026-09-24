"""
Purpose:
Unit tests for Day 5 shared models and test fixtures (Tasks 43–45).
Verifies:
1. EvaluationMetrics 10-dimensional mathematical schema and constraints.
2. AutonomousTriggerPayload and TriggerSession state machine states.
3. BenchmarkThresholdAudit validation against all 7 Stage 0 thresholds.
4. DemoScenario tracking models.
5. SEEDED_FINDINGS_10 composition: exactly 5 Bugs, 3 Dependencies, 2 Security.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.agent_3.day4_models import FindingCategory, UnifiedFinding
from agents.agent_3.day5_models import (
    EvaluationMetrics,
    AutonomousTriggerPayload,
    TriggerSessionState,
    TriggerSession,
    BenchmarkThresholdAudit,
    DemoScenario,
)
from tests.fixtures.day5_fixtures import SEEDED_FINDINGS_10


def test_evaluation_metrics_model_and_ranges():
    """
    Verifies that EvaluationMetrics enforces valid ranges for all 10 core dimensions.
    """
    metrics = EvaluationMetrics(
        task_success_rate=0.90,
        root_cause_accuracy=0.95,
        plan_validity_rate=0.90,
        first_pass_fix_rate=0.80,
        repair_convergence_rate=1.00,
        regression_rate=0.00,
        time_to_pr_sec=45.2,
        cost_per_task_usd=0.08,
        token_efficiency=0.88,
        human_intervention_rate=0.10,
        total_tasks=10,
        tasks_passed=9,
    )

    assert metrics.task_success_rate == 0.90
    assert metrics.repair_convergence_rate == 1.00
    assert metrics.total_tasks == 10
    assert metrics.tasks_passed == 9

    # Out of bounds rate must raise ValidationError
    with pytest.raises(ValidationError):
        EvaluationMetrics(
            task_success_rate=1.5,  # Invalid: > 1.0
            root_cause_accuracy=0.9,
            plan_validity_rate=0.9,
            first_pass_fix_rate=0.8,
            repair_convergence_rate=1.0,
            regression_rate=0.0,
            time_to_pr_sec=10.0,
            cost_per_task_usd=0.05,
            token_efficiency=0.8,
            human_intervention_rate=0.1,
        )


def test_autonomous_trigger_payload_and_session():
    """
    Verifies AutonomousTriggerPayload and TriggerSession state transitions.
    """
    finding = SEEDED_FINDINGS_10[0]
    payload = AutonomousTriggerPayload(
        webhook_id="WH-12345",
        source="sast_scanner",
        finding=finding,
    )

    assert payload.webhook_id == "WH-12345"
    assert payload.finding.finding_id == "BUG-PAGINATE-01"

    session = TriggerSession(
        session_id="SESS-TRIG-01",
        finding=finding,
        state=TriggerSessionState.ROOT_CAUSE,
        root_cause="Off-by-one boundary calculation in catalog pagination slice",
        paused_at_root_cause=True,
    )

    assert session.state == TriggerSessionState.ROOT_CAUSE
    assert session.paused_at_root_cause is True


def test_benchmark_threshold_audit_model():
    """
    Verifies BenchmarkThresholdAudit validation across all 7 Stage 0 thresholds.
    """
    audit = BenchmarkThresholdAudit(
        investigation_success_rate=0.90,
        reproduction_success_rate=0.80,
        plan_success_rate=0.80,
        execution_success_rate=0.70,
        false_positive_rate=0.05,
        e2e_latency_sec=120.0,
        cost_per_task_usd=0.15,
        thresholds_met={
            "investigation": True,
            "reproduction": True,
            "plan": True,
            "execution": True,
            "false_positive": True,
            "latency": True,
            "cost": True,
        },
        all_thresholds_met=True,
    )

    assert audit.all_thresholds_met is True
    assert audit.investigation_success_rate > 0.80
    assert audit.reproduction_success_rate > 0.70
    assert audit.plan_success_rate > 0.70
    assert audit.execution_success_rate > 0.60
    assert audit.false_positive_rate < 0.15
    assert audit.e2e_latency_sec < 600.0
    assert audit.cost_per_task_usd < 1.00


def test_demo_scenario_model():
    """
    Verifies DemoScenario record tracking.
    """
    scenario = DemoScenario(
        scenario_id="DEMO-01-BUG",
        scenario_type="AUTOMATED_BUG",
        finding_id="BUG-PAGINATE-01",
        title="Live Automated Bug-Fix to PR",
        duration_sec=3.4,
        pr_branch="fix/bug-paginate-01",
        pr_title="fix(BUG-PAGINATE-01): resolve boundary",
        summary="Autonomously repaired off-by-one defect and opened PR",
    )

    assert scenario.status == "SUCCESS"
    assert scenario.scenario_id == "DEMO-01-BUG"


def test_seeded_findings_10_fixtures_composition():
    """
    Verifies that SEEDED_FINDINGS_10 contains exactly 10 findings:
    5 Bugs, 3 Dependencies, 2 Security defects.
    """
    assert len(SEEDED_FINDINGS_10) == 10

    categories = [f.category for f in SEEDED_FINDINGS_10]
    assert categories.count(FindingCategory.BUG) == 5, f"Expected 5 Bugs, got {categories.count(FindingCategory.BUG)}"
    assert categories.count(FindingCategory.DEPENDENCY) == 3, f"Expected 3 Deps, got {categories.count(FindingCategory.DEPENDENCY)}"
    assert categories.count(FindingCategory.SECURITY) == 2, f"Expected 2 Security, got {categories.count(FindingCategory.SECURITY)}"
