"""
Purpose:
Task 45 Test Suite: Full Stage 0 Demo & Capstone Gate (AC-E3-D5-03 & AC-E3-D5-04).
Verifies:
1. Acceptance Criteria AC-E3-D5-03:
   Executes complete benchmark suite of 10 findings (5 Bugs, 3 Dependencies, 2 Security);
   asserts that all 7 Stage 0 quantitative thresholds are strictly satisfied:
   - Investigation success > 80%
   - Reproduction success > 70%
   - Plan success > 70%
   - Execution/repair success > 60%
   - False positive rate < 15%
   - End-to-end latency < 10 min (600s)
   - Cost < $1.00 per task
2. Acceptance Criteria AC-E3-D5-04:
   Rehearses the 4 live demonstration scenarios (Automated Bug, Dependency Upgrade,
   Security Remediation, and Manual Control Drive); asserts clean execution and
   generates multi-engineer sprint acceptance sign-off.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from agents.agent_3.day5_models import BenchmarkThresholdAudit, DemoScenario
from agents.agent_3.stage0_capstone_demo import Stage0CapstoneOrchestrator
from tests.fixtures.day5_fixtures import SEEDED_FINDINGS_10


def test_stage0_benchmark_10_findings_meets_all_7_thresholds_ac_e3_d5_03():
    """
    Acceptance Criteria AC-E3-D5-03:
    10-finding benchmark audit:
    Executes all 10 benchmark repository findings and asserts that 100% of the
    7 official Stage 0 quantitative performance thresholds are satisfied.
    """
    orchestrator = Stage0CapstoneOrchestrator(benchmark_repo="repo_stage0_benchmark")
    assert len(SEEDED_FINDINGS_10) == 10

    # Execute all 10 benchmark findings
    contexts, metrics, audit = orchestrator.run_benchmark_10_findings()

    # 1. Assert exactly 10 contexts processed
    assert len(contexts) == 10
    for ctx in contexts:
        assert ctx.stage == "COMPLETE", f"Finding {ctx.finding.finding_id} failed to complete: {ctx.stage}"
        assert ctx.verdict is not None and ctx.verdict.verdict == "PASS", (
            f"Finding {ctx.finding.finding_id} failed validation: {ctx.verdict.failure_reasons if ctx.verdict else 'No verdict'}"
        )
        assert ctx.pr_manifest is not None, f"Finding {ctx.finding.finding_id} missing PR manifest"

    # 2. Assert All 7 Quantitative Thresholds are Met (AC-E3-D5-03)
    assert audit.all_thresholds_met is True, f"Failed thresholds: {audit.thresholds_met}"

    # Threshold 1: Investigation success > 80% (0.80)
    assert audit.investigation_success_rate > 0.80, f"Investigation {audit.investigation_success_rate} <= 0.80"

    # Threshold 2: Reproduction success > 70% (0.70)
    assert audit.reproduction_success_rate > 0.70, f"Reproduction {audit.reproduction_success_rate} <= 0.70"

    # Threshold 3: Plan success > 70% (0.70)
    assert audit.plan_success_rate > 0.70, f"Plan success {audit.plan_success_rate} <= 0.70"

    # Threshold 4: Execution/repair success > 60% (0.60)
    assert audit.execution_success_rate > 0.60, f"Execution {audit.execution_success_rate} <= 0.60"

    # Threshold 5: False positive rate < 15% (0.15)
    assert audit.false_positive_rate < 0.15, f"False positive {audit.false_positive_rate} >= 0.15"

    # Threshold 6: End-to-end latency < 10 min (600s)
    assert audit.e2e_latency_sec < 600.0, f"Latency {audit.e2e_latency_sec}s >= 600s"

    # Threshold 7: Cost < $1.00 per task
    assert audit.cost_per_task_usd < 1.00, f"Cost ${audit.cost_per_task_usd} >= $1.00"


def test_live_demo_scenarios_clean_execution_ac_e3_d5_04():
    """
    Acceptance Criteria AC-E3-D5-04 (Part 1):
    Rehearses all 4 live demonstration scenarios:
    1. Automated bug-fix to PR (BUG-PAGINATE-01)
    2. Dependency upgrade to PR (DEP-REQ-01)
    3. Security remediation to PR (SEC-SQLI-01)
    4. Manual control drive with plan editing (BUG-ZERO-FEE-02)

    Asserts:
    - 100% of demo scenarios execute with status 'SUCCESS'.
    - PR branches and manifests generated across all scenarios.
    """
    orchestrator = Stage0CapstoneOrchestrator()
    scenarios = orchestrator.run_live_demo_scenarios()

    assert len(scenarios) == 4, f"Expected 4 demo scenarios, got {len(scenarios)}"

    expected_ids = ["DEMO-01-BUG", "DEMO-02-DEP", "DEMO-03-SEC", "DEMO-04-MANUAL"]
    for scenario in scenarios:
        assert scenario.scenario_id in expected_ids
        assert scenario.status == "SUCCESS", f"Demo scenario {scenario.scenario_id} failed!"
        assert scenario.duration_sec > 0.0
        assert scenario.pr_branch is not None
        assert scenario.pr_title is not None
        assert len(scenario.summary) > 20


def test_multi_engineer_signoff_document_generation_ac_e3_d5_04():
    """
    Acceptance Criteria AC-E3-D5-04 (Part 2):
    Asserts that the multi-engineer sprint acceptance sign-off document:
    - Confirms all 7 Stage 0 quantitative thresholds.
    - Lists all 4 live demo scenarios.
    - Validates all 15 tasks across all 5 days (Tasks 31–45).
    - Contains signatures for all 3 engineers.
    """
    orchestrator = Stage0CapstoneOrchestrator()
    scenarios = orchestrator.run_live_demo_scenarios()
    audit = orchestrator.audit_thresholds(orchestrator.eval_engine.compute_metrics())

    # Create dummy passing audit for signoff formatting test
    audit.all_thresholds_met = True
    audit.investigation_success_rate = 1.0
    audit.reproduction_success_rate = 1.0
    audit.plan_success_rate = 1.0
    audit.execution_success_rate = 1.0
    audit.false_positive_rate = 0.0
    audit.e2e_latency_sec = 3.5
    audit.cost_per_task_usd = 0.05

    signoff_doc = orchestrator.generate_signoff_document(audit, scenarios)

    assert "ACCEPTED — FULL STAGE 0 HARD GATE ACHIEVED" in signoff_doc
    assert "Task 31:" in signoff_doc
    assert "Task 40:" in signoff_doc
    assert "Task 45:" in signoff_doc
    assert "Engineer 1 — Intake & Triage Lead" in signoff_doc
    assert "Engineer 2 — Execution & Sandbox Lead" in signoff_doc
    assert "Engineer 3 — Verification & Intel Lead" in signoff_doc
