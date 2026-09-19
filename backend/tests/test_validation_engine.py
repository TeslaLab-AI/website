"""
Purpose:
Acceptance and unit tests for Task 34: 5-Signal Validation Engine.

Verifies:
- AC-E3-D2-01: 5-Signal Validation Rigor: Requires 5/5 checks to PASS;
  any single failure returns FAIL with specific reason across 1 clean fix
  and 5 distinct single-failure scenarios.
"""

import os
import tempfile
import pytest

from tests.fixtures.day1_fixtures import create_mock_repo
from tests.fixtures.day2_fixtures import (
    CLEAN_PASSING_DIFF,
    DIFF_FAILING_REQUIREMENTS,
    DIFF_FAILING_DIFF_QUALITY,
    DIFF_FAILING_REPRO_TEST,
    DIFF_FAILING_REGRESSION,
    DIFF_FAILING_SECURITY,
)
from agents.agent_3.validation_engine import ValidationEngine


def test_validation_engine_clean_fix_passes():
    """
    AC-E3-D2-01 (Part 1):
    Execute Validation Engine on 1 clean fix.
    Asserts PASS with all 5 component checks confirmed.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        # Repro test that passes when clean fix is applied
        repro_path = os.path.join(tmp_dir, "tests", "test_repro.py")
        with open(repro_path, "w", encoding="utf-8") as f:
            f.write("from src.payment.client import calculate_fee\n\ndef test_repro():\n    assert calculate_fee(100.0) == 2.0\n")

        verdict = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=CLEAN_PASSING_DIFF,
            task_desc="Fix fee calculation in client.py",
            target_files=["src/payment/client.py"],
            repro_test_path=repro_path,
            changed_files=["src/payment/client.py"],
        )

        # Assertions for clean fix
        assert verdict.verdict == "PASS", "Clean fix must pass validation"
        assert verdict.score == 1.0
        assert len(verdict.failure_reasons) == 0
        assert len(verdict.checks) == 5
        assert all(c.passed for c in verdict.checks.values()), "All 5 checks must pass"


def test_validation_engine_fails_requirements():
    """AC-E3-D2-01 (Part 2 - Scenario 1): Fails on Requirements Mismatch."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        verdict = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=DIFF_FAILING_REQUIREMENTS,
            task_desc="Fix fee calculation in client.py",
            target_files=["src/payment/client.py"],
            repro_test_path=None,
            changed_files=["src/utils/logger.py"],
        )

        assert verdict.verdict == "FAIL", "Must fail on requirements scope mismatch"
        assert verdict.checks["requirements"].passed is False
        assert any("REQUIREMENTS" in r for r in verdict.failure_reasons)


def test_validation_engine_fails_diff_quality():
    """AC-E3-D2-01 (Part 2 - Scenario 2): Fails on Bloated Diff Quality."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        verdict = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=DIFF_FAILING_DIFF_QUALITY,
            task_desc="Fix fee calculation in client.py",
            target_files=["src/payment/client.py"],
            repro_test_path=None,
            changed_files=["src/payment/client.py"],
        )

        assert verdict.verdict == "FAIL", "Must fail on diff bloat limit"
        assert verdict.checks["diff_quality"].passed is False
        assert any("DIFF_QUALITY" in r for r in verdict.failure_reasons)


def test_validation_engine_fails_repro_test():
    """AC-E3-D2-01 (Part 2 - Scenario 3): Fails when Reproduction Test fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        # Repro test requiring specific value that the buggy diff fails
        repro_path = os.path.join(tmp_dir, "tests", "test_repro.py")
        with open(repro_path, "w", encoding="utf-8") as f:
            f.write("from src.payment.client import calculate_fee\n\ndef test_repro():\n    # Expect positive fee, but buggy code returns negative\n    assert calculate_fee(50.0) > 0.0\n")

        # Apply the failing code to client.py
        with open(paths["client"], "w", encoding="utf-8") as f:
            f.write("def calculate_fee(amount: float) -> float:\n    return -1.0\n")

        verdict = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=DIFF_FAILING_REPRO_TEST,
            task_desc="Fix fee calculation in client.py",
            target_files=["src/payment/client.py"],
            repro_test_path=repro_path,
            changed_files=["src/payment/client.py"],
        )

        assert verdict.verdict == "FAIL", "Must fail when reproduction test fails"
        assert verdict.checks["repro_test"].passed is False
        assert any("REPRO_TEST" in r for r in verdict.failure_reasons)


def test_validation_engine_fails_regression_tests():
    """AC-E3-D2-01 (Part 2 - Scenario 4): Fails when existing Regression Tests break."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        # Break checkout.py to cause a regression failure in test_checkout.py
        with open(paths["checkout"], "w", encoding="utf-8") as f:
            f.write("def process_cart(total: float) -> float:\n    return 0.0\n")

        verdict = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=DIFF_FAILING_REGRESSION,
            task_desc="Fix checkout cart processing",
            target_files=["src/payment/checkout.py"],
            repro_test_path=None,
            changed_files=["src/payment/checkout.py"],
        )

        assert verdict.verdict == "FAIL", "Must fail when regression tests fail"
        assert verdict.checks["regression_tests"].passed is False
        assert any("REGRESSION_TESTS" in r for r in verdict.failure_reasons)


def test_validation_engine_fails_security_scan():
    """AC-E3-D2-01 (Part 2 - Scenario 5): Fails when Security Flaw is introduced."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        verdict = ValidationEngine.evaluate(
            worktree_dir=tmp_dir,
            diff_text=DIFF_FAILING_SECURITY,
            task_desc="Fix client query",
            target_files=["src/payment/client.py"],
            repro_test_path=None,
            changed_files=["src/payment/client.py"],
        )

        assert verdict.verdict == "FAIL", "Must fail when diff introduces security flaw"
        assert verdict.checks["security_scan"].passed is False
        assert any("SECURITY_SCAN" in r for r in verdict.failure_reasons)
