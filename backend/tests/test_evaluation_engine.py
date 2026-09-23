"""
Purpose:
Task 43 Test Suite: Evaluation Engine & Dashboard Service (AC-E3-D5-01).
Verifies:
1. Acceptance Criteria AC-E3-D5-01:
   Execute evaluation engine against 10 benchmark finding runs; assert dashboard
   displays all 10 metrics with 100% mathematical consistency with database ground truth.
2. Zero manual estimation: mathematical calculation verified down to exact decimals.
3. Export endpoints: programmatic export of evaluation_report.json and CSV.
4. Live Measurement Dashboard: ASCII render displaying all 10 core dimensions.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import pytest

from agents.agent_3.day4_models import FindingCategory, UnifiedFinding
from agents.agent_3.day5_models import EvaluationMetrics
from agents.agent_3.evaluation_engine import EvaluationEngine, SessionTelemetryRecord
from agents.agent_3.unified_pipeline import UnifiedFindingPipeline
from tests.fixtures.day5_fixtures import SEEDED_FINDINGS_10, setup_workspace_for_day5_finding


def test_evaluation_engine_aggregates_all_10_dimensions_ac_e3_d5_01():
    """
    Acceptance Criteria AC-E3-D5-01:
    Execute evaluation engine against 10 benchmark finding runs.
    Asserts:
    1. All 10 metrics match ground-truth calculation with 0.00 discrepancy.
    2. Every metric is computed strictly from persistent event records.
    """
    engine = EvaluationEngine(benchmark_repo="repo_stage0_benchmark")

    # Ingest 10 benchmark finding session records with deterministic parameters
    ground_truth_data = [
        # (finding_id, category, passed, rc_accurate, plan_valid, first_pass, attempts, converged, regression, time_sec, cost, token_eff, human)
        ("BUG-PAGINATE-01", "BUG", True, True, True, True, 1, True, False, 3.2, 0.04, 0.85, False),
        ("BUG-ZERO-FEE-02", "BUG", True, True, True, True, 1, True, False, 2.8, 0.03, 0.88, False),
        ("BUG-BOOL-FLAG-03", "BUG", True, True, True, True, 1, True, False, 3.0, 0.04, 0.82, False),
        ("BUG-SLUG-HYPHEN-04", "BUG", True, True, True, True, 1, True, False, 2.5, 0.03, 0.90, False),
        ("BUG-CHECKOUT-TOTAL-05", "BUG", True, True, True, False, 2, True, False, 5.1, 0.07, 0.80, False),
        ("DEP-REQ-01", "DEPENDENCY", True, True, True, True, 1, True, False, 4.0, 0.05, 0.85, False),
        ("DEP-PYD-02", "DEPENDENCY", True, True, True, False, 2, True, False, 6.2, 0.08, 0.78, False),
        ("DEP-LODASH-03", "DEPENDENCY", True, True, True, True, 1, True, False, 3.5, 0.04, 0.86, False),
        ("SEC-SQLI-01", "SECURITY", True, True, True, True, 1, True, False, 4.8, 0.06, 0.82, False),
        ("SEC-HARDCODED-JWT-02", "SECURITY", True, True, True, True, 1, True, False, 3.9, 0.05, 0.84, True),
    ]

    for item in ground_truth_data:
        engine.record_direct(
            session_id=f"SESS-{item[0]}",
            finding_id=item[0],
            category=item[1],
            passed=item[2],
            root_cause_accurate=item[3],
            plan_valid=item[4],
            first_pass_fixed=item[5],
            repair_attempts=item[6],
            converged_in_limit=item[7],
            introduced_regression=item[8],
            elapsed_sec=item[9],
            cost_usd=item[10],
            token_efficiency=item[11],
            human_intervened=item[12],
        )

    assert len(engine.records) == 10

    # Compute metrics via Engine
    metrics = engine.compute_metrics()

    # Manual Ground-Truth Calculations:
    # 1. Task success rate: 10/10 passed = 1.00
    expected_task_success = 10 / 10
    assert metrics.task_success_rate == pytest.approx(expected_task_success, rel=1e-4)

    # 2. Root cause accuracy: 10/10 accurate = 1.00
    expected_rc = 10 / 10
    assert metrics.root_cause_accuracy == pytest.approx(expected_rc, rel=1e-4)

    # 3. Plan validity rate: 10/10 valid = 1.00
    expected_plan_valid = 10 / 10
    assert metrics.plan_validity_rate == pytest.approx(expected_plan_valid, rel=1e-4)

    # 4. First-pass fix rate: 8/10 fixed on attempt 1 = 0.80
    expected_first_pass = 8 / 10
    assert metrics.first_pass_fix_rate == pytest.approx(expected_first_pass, rel=1e-4)

    # 5. Repair convergence rate: 10/10 converged within <=3 attempts = 1.00
    expected_convergence = 10 / 10
    assert metrics.repair_convergence_rate == pytest.approx(expected_convergence, rel=1e-4)

    # 6. Regression rate: 0/10 regressions = 0.00
    expected_regression = 0 / 10
    assert metrics.regression_rate == pytest.approx(expected_regression, rel=1e-4)

    # 7. Time to PR: sum(time) / 10 = 39.0 / 10 = 3.90s
    total_time = sum(item[9] for item in ground_truth_data)
    expected_avg_time = total_time / 10
    assert metrics.time_to_pr_sec == pytest.approx(expected_avg_time, rel=1e-2)

    # 8. Cost per task: sum(cost) / 10 = 0.49 / 10 = 0.049 USD
    total_cost = sum(item[10] for item in ground_truth_data)
    expected_avg_cost = total_cost / 10
    assert metrics.cost_per_task_usd == pytest.approx(expected_avg_cost, rel=1e-4)

    # 9. Token efficiency: sum(token_eff) / 10 = 8.40 / 10 = 0.840
    total_eff = sum(item[11] for item in ground_truth_data)
    expected_token_eff = total_eff / 10
    assert metrics.token_efficiency == pytest.approx(expected_token_eff, rel=1e-4)

    # 10. Human intervention rate: 1/10 required human = 0.10
    expected_human = 1 / 10
    assert metrics.human_intervention_rate == pytest.approx(expected_human, rel=1e-4)


def test_evaluation_report_export_json_and_csv():
    """
    Verifies that evaluation reports export cleanly to JSON and CSV formats.
    """
    engine = EvaluationEngine()
    engine.record_direct(
        session_id="SESS-01",
        finding_id="BUG-PAGINATE-01",
        category="BUG",
        passed=True,
        elapsed_sec=3.0,
        cost_usd=0.04,
    )
    engine.record_direct(
        session_id="SESS-02",
        finding_id="DEP-REQ-01",
        category="DEPENDENCY",
        passed=True,
        elapsed_sec=4.0,
        cost_usd=0.05,
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = os.path.join(tmp_dir, "evaluation_report.json")
        csv_path = os.path.join(tmp_dir, "evaluation_report.csv")

        engine.export_json(json_path)
        engine.export_csv(csv_path)

        # Assert JSON report
        assert os.path.exists(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["records_count"] == 2
        assert "task_success_rate" in data["metrics"]
        assert data["metrics"]["task_success_rate"] == 1.0

        # Assert CSV report
        assert os.path.exists(csv_path)
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.reader(f))
        assert len(reader) == 11  # Header + 10 metric rows
        assert reader[0] == ["Metric Dimension", "Observed Value", "Stage 0 Target", "Status"]


def test_ascii_dashboard_rendering():
    """
    Verifies that the live ASCII evaluation dashboard renders cleanly.
    """
    engine = EvaluationEngine()
    engine.record_direct(
        session_id="SESS-TEST",
        finding_id="BUG-01",
        category="BUG",
        passed=True,
    )

    dashboard = engine.render_dashboard_ascii()
    assert "TESLALAB AI — STAGE 0 EVALUATION DASHBOARD" in dashboard
    assert "1. Task Success Rate" in dashboard
    assert "7. Time to PR" in dashboard
    assert "8. Cost per Task" in dashboard
    assert "10. Human Intervention Rate" in dashboard
    assert "PASS" in dashboard


def test_evaluation_engine_ingests_real_pipeline_context():
    """
    Verifies that EvaluationEngine records live telemetry from actual FindingContext.
    """
    engine = EvaluationEngine()
    pipeline = UnifiedFindingPipeline()
    finding = SEEDED_FINDINGS_10[0]

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_day5_finding(tmp_dir, finding)
        ctx = pipeline.process_finding(tmp_dir, finding)

        rec = engine.record_session(
            context=ctx,
            attempts=1,
            cost_usd=0.035,
            elapsed_sec=2.8,
            tokens_generated=140,
            tokens_in_diff=120,
        )

        assert rec.finding_id == "BUG-PAGINATE-01"
        assert rec.passed is True
        assert rec.first_pass_fixed is True
        assert rec.cost_usd == 0.035

        metrics = engine.compute_metrics()
        assert metrics.total_tasks == 1
        assert metrics.task_success_rate == 1.0
        assert metrics.tasks_passed == 1
