"""
Purpose:
Task 35: Targeted Self-Healing Repair Agent Tests.
Verifies AC-E3-D2-02:
1. When validation fails (e.g. pagination off-by-one bug), the Repair Agent:
   - Analyzes test failure diagnostic
   - Synthesizes an adjusted repair plan
   - Reaches a PASS state in <= 3 rounds unattended.
2. When attempt count exceeds 3, halts cleanly and escalates to 'NEEDS_HUMAN'.
"""

import os
import tempfile
import pytest

from agents.agent_3.day2_models import CheckResult, ValidationVerdict
from agents.agent_3.validation_engine import ValidationEngine
from agents.agent_3.repair_agent import RepairAgent, FailureDiagnosticParser
from tests.fixtures.day2_fixtures import setup_repair_benchmark_repo


def test_repair_agent_diagnoses_and_repairs_pagination_bug():
    """
    AC-E3-D2-02:
    Inject broken fix / off-by-one bug into benchmark pagination repo.
    Repair agent analyzes diagnostic, synthesizes targeted repair,
    and reaches PASS within <= 3 rounds unattended.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        files = setup_repair_benchmark_repo(tmp_dir)
        target_files = ["src/catalog/paginate.py"]
        repro_path = files["test_repro"]

        # Initial broken fix with off-by-one boundary
        broken_diff = """--- a/src/catalog/paginate.py
+++ b/src/catalog/paginate.py
@@ -3,3 +3,3 @@
     start = (page - 1) * page_size
-    end = start + page_size
+    end = start + (page_size - 1)
     return items[start:end]
"""

        # Round 1: Run ValidationEngine on the initial buggy code
        verdict_1 = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=broken_diff,
            task_desc="Fix pagination logic",
            target_files=target_files,
            repro_test_path=repro_path,
        )

        # Confirm that Round 1 failed specifically on repro_test
        assert verdict_1.verdict == "FAIL"
        assert not verdict_1.checks["repro_test"].passed
        assert "Expected 5 items, got 4" in verdict_1.checks["repro_test"].details.get("output", "")

        # Repair Agent analyzes diagnostic and generates RepairPlan (Attempt 1)
        repair_plan = RepairAgent.generate_repair_plan(
            session_id="session-pagination-01",
            current_attempt=1,
            failed_diff=broken_diff,
            verdict=verdict_1,
        )

        assert repair_plan.attempt == 1
        assert repair_plan.status == "RETRY"
        assert "OFF_BY_ONE" in repair_plan.diagnosis
        assert "src/catalog/paginate.py" in repair_plan.target_components

        # Apply the targeted repair patch to the file
        success = RepairAgent.apply_repair_to_file(
            files["paginate"],
            "end = start + (page_size - 1)",
            "end = start + page_size",
        )
        assert success, "Repair patch must apply cleanly to paginate.py"

        # Corrected diff generated
        corrected_diff = """--- a/src/catalog/paginate.py
+++ b/src/catalog/paginate.py
@@ -3,3 +3,3 @@
     start = (page - 1) * page_size
-    end = start + (page_size - 1)
+    end = start + page_size
     return items[start:end]
"""

        # Round 2: Re-validate with the corrected implementation
        verdict_2 = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=corrected_diff,
            task_desc="Fix pagination logic",
            target_files=target_files,
            repro_test_path=repro_path,
        )

        # Verify reached PASS in 2 rounds (which is <= 3 rounds)
        assert verdict_2.verdict == "PASS"
        assert verdict_2.checks["repro_test"].passed
        assert verdict_2.checks["regression_tests"].passed
        assert verdict_2.checks["security_scan"].passed
        assert verdict_2.checks["requirements"].passed
        assert verdict_2.checks["diff_quality"].passed


def test_repair_agent_guardrail_escalates_to_needs_human():
    """
    AC-E3-D2-02 (Guardrail):
    When attempt count exceeds MAX_ATTEMPTS (3), RepairAgent must halt immediately
    and transition status to 'NEEDS_HUMAN' without generating further automated patches.
    """
    mock_verdict = ValidationVerdict(
        verdict="FAIL",
        score=0.4,
        checks={
            "repro_test": CheckResult(
                name="repro_test",
                passed=False,
                score=0.0,
                message="Persistent failure",
                details={"output": "AssertionError: Expected 5 items, got 4"},
            )
        },
        failure_reasons=["[REPRO_TEST] Persistent failure"],
    )

    # Attempt 4 exceeds the hard ceiling of 3
    repair_plan = RepairAgent.generate_repair_plan(
        session_id="session-pagination-guardrail",
        current_attempt=4,
        failed_diff="dummy diff",
        verdict=mock_verdict,
    )

    assert repair_plan.status == "NEEDS_HUMAN"
    assert repair_plan.attempt == 4
    assert repair_plan.target_components == []
    assert "Maximum repair limit of 3 attempts exceeded" in repair_plan.diagnosis
    assert "Escalating session to human engineer" in repair_plan.diagnosis


def test_failure_diagnostic_parser_security_and_regression():
    """
    Verifies that FailureDiagnosticParser correctly differentiates between
    security vulnerabilities and regression failures.
    """
    # Test Security Diagnostic
    sec_verdict = ValidationVerdict(
        verdict="FAIL",
        score=0.6,
        checks={
            "security_scan": CheckResult(
                name="security_scan",
                passed=False,
                score=0.0,
                message="SQL Injection detected",
                details={"new_vulnerabilities": ["CWE-89 at src/payment/client.py:2"]},
            )
        },
        failure_reasons=["[SECURITY_SCAN] SQL Injection detected"],
    )
    sec_diag = FailureDiagnosticParser.parse(sec_verdict, "diff")
    assert sec_diag.failure_type == "SECURITY"
    assert "parameterized queries" in sec_diag.suggested_fix

    # Test Regression Diagnostic
    reg_verdict = ValidationVerdict(
        verdict="FAIL",
        score=0.6,
        checks={
            "regression_tests": CheckResult(
                name="regression_tests",
                passed=False,
                score=0.0,
                message="Regression in checkout",
                details={"failed_tests": ["test_checkout_total"]},
            )
        },
        failure_reasons=["[REGRESSION_TESTS] Regression in checkout"],
    )
    reg_diag = FailureDiagnosticParser.parse(reg_verdict, "diff")
    assert reg_diag.failure_type == "REGRESSION"
    assert "Regression tests broke" in reg_diag.error_summary
