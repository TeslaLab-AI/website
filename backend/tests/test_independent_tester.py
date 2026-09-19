"""
Purpose:
Acceptance and unit tests for Task 31: Independent Testing Agent.

Verifies:
- AC-E3-D1-01: Independent Test Verification: Catches an injected regression
  test failure independently; asserts failure reported with specific test names
  and produces an accurate VerificationReport.
"""

import os
import tempfile
import pytest

from tests.fixtures.day1_fixtures import create_mock_repo
from agents.agent_3.independent_tester import (
    discover_tests_for_files,
    run_independent_verification,
)


def test_test_discovery():
    """Verify discovery finds directly named and imported test suites."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)
        changed = ["src/payment/client.py", "src/payment/checkout.py"]
        discovered = discover_tests_for_files(tmp_dir, changed)

        assert any("test_client.py" in t for t in discovered)
        assert any("test_checkout.py" in t for t in discovered)


def test_independent_tester_valid_fix():
    """Verify that a valid change runs cleanly with zero regressions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)
        changed = ["src/payment/client.py"]

        # Create a reproduction test that passes
        repro_path = os.path.join(tmp_dir, "tests", "test_repro.py")
        with open(repro_path, "w", encoding="utf-8") as f:
            f.write("from src.payment.client import calculate_fee\n\ndef test_repro():\n    assert calculate_fee(50.0) == 1.0\n")

        report = run_independent_verification(
            repo_root=tmp_dir,
            changed_files=changed,
            repro_test_path=repro_path,
        )

        assert report.repro_test_status == "PASS"
        assert report.failed == 0
        assert len(report.new_failures) == 0
        assert report.passed >= 2


def test_independent_tester_catches_injected_regression():
    """
    AC-E3-D1-01 Acceptance Test:
    Execute Testing Agent on fix with an injected regression.
    Asserts failure is reported with specific test names in new_failures.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        paths = create_mock_repo(tmp_dir)

        # Inject a regression into checkout.py that breaks test_process_cart
        with open(paths["checkout"], "w", encoding="utf-8") as f:
            f.write("""from src.payment.client import calculate_fee

def process_cart(total: float) -> float:
    # INJECTED REGRESSION: Breaks cart calculation logic
    return 0.0
""")

        changed = ["src/payment/checkout.py"]

        report = run_independent_verification(
            repo_root=tmp_dir,
            changed_files=changed,
            repro_test_path=None,
        )

        # AC-E3-D1-01 Assertions:
        assert report.failed > 0, "Independent tester must detect the regression failure"
        assert len(report.new_failures) > 0, "new_failures list must not be empty"
        assert any("test_checkout.py" in f and "test_process_cart" in f for f in report.new_failures), (
            f"Expected 'test_checkout.py::test_process_cart' in new_failures, got: {report.new_failures}"
        )
