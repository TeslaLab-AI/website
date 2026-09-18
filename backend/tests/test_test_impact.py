"""
Purpose:
Acceptance and unit tests for Task 32: Test Impact Analysis (TIA).

Verifies:
- AC-E3-D1-02: Test Impact Analysis Speedup: Targeted-suite run completes in under 25%
  of full suite time with 0 missed failures across 3 test scenarios.
- AC-E3-D1-04: Zero-Test Fallback Protection: Ambiguous graph test falls back to directory
  test suite; never executes 0 tests.
"""

import os
import time
import tempfile
import pytest

from tests.fixtures.day1_fixtures import create_mock_repo
from app.agents.test_impact import build_import_graph, select_impacted_tests


def test_import_graph_construction():
    """Verify AST parses import relationships correctly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)
        depends_on, imported_by = build_import_graph(tmp_dir)

        # checkout.py imports client.py
        assert any("client.py" in dep for dep in depends_on.get("src/payment/checkout.py", set()))
        # billing.py imports checkout.py
        assert any("checkout.py" in dep for dep in depends_on.get("src/payment/billing.py", set()))
        # client.py is imported by checkout.py
        assert any("checkout.py" in imp for imp in imported_by.get("src/payment/client.py", set()))


def test_scenario_a_modify_client():
    """Scenario 1: Modifying client.py affects client, checkout, and billing, but NOT helpers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)
        manifest = select_impacted_tests(tmp_dir, ["src/payment/client.py"])

        assert not manifest.is_fallback
        assert any("test_client.py" in t for t in manifest.selected_tests)
        assert any("test_checkout.py" in t for t in manifest.selected_tests)
        assert any("test_billing.py" in t for t in manifest.selected_tests)
        assert not any("test_helpers.py" in t for t in manifest.selected_tests), "helpers must not be affected"


def test_scenario_b_modify_checkout():
    """Scenario 2: Modifying checkout.py affects checkout and billing, but NOT client or helpers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)
        manifest = select_impacted_tests(tmp_dir, ["src/payment/checkout.py"])

        assert not manifest.is_fallback
        assert any("test_checkout.py" in t for t in manifest.selected_tests)
        assert any("test_billing.py" in t for t in manifest.selected_tests)
        assert not any("test_client.py" in t for t in manifest.selected_tests)
        assert not any("test_helpers.py" in t for t in manifest.selected_tests)


def test_scenario_c_modify_helpers():
    """Scenario 3: Modifying helpers.py affects ONLY test_helpers.py."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)
        manifest = select_impacted_tests(tmp_dir, ["src/utils/helpers.py"])

        assert not manifest.is_fallback
        assert any("test_helpers.py" in t for t in manifest.selected_tests)
        assert not any("test_client.py" in t for t in manifest.selected_tests)
        assert not any("test_checkout.py" in t for t in manifest.selected_tests)
        assert not any("test_billing.py" in t for t in manifest.selected_tests)


def test_ac_e3_d1_04_zero_test_fallback_protection():
    """
    AC-E3-D1-04 Acceptance Test:
    When dependency analysis is ambiguous (e.g. unknown new file, dynamic imports),
    safety guard must fallback to directory test suite and NEVER return 0 tests.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)

        # Ambiguous untracked file with no static imports in graph
        ambiguous_file = "src/payment/unknown_plugin.py"
        with open(os.path.join(tmp_dir, ambiguous_file), "w", encoding="utf-8") as f:
            f.write("# Dynamic plugin without static import links\n")

        manifest = select_impacted_tests(tmp_dir, [ambiguous_file])

        # Assert Fallback Protection
        assert manifest.is_fallback is True, "Fallback must activate for ambiguous file"
        assert len(manifest.selected_tests) > 0, "Safety constraint violated: must NEVER return 0 tests"
        assert "Fallback applied" in manifest.rationale


def test_ac_e3_d1_02_benchmark_speedup():
    """
    AC-E3-D1-02 Acceptance Test:
    Targeted-suite run completes in under 25% of the time of a full suite run.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        create_mock_repo(tmp_dir)

        # Add 24 additional test suites to simulate a realistic repository test suite
        # Each suite includes a synthetic delay (100ms)
        full_suite = []
        for i in range(24):
            test_file = os.path.join(tmp_dir, "tests", f"test_extra_{i}.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(f"""import time

def test_extra_{i}():
    time.sleep(0.10)
    assert True
""")
            full_suite.append(f"tests/test_extra_{i}.py")

        # Scenario: single isolated module changed (helpers.py)
        manifest = select_impacted_tests(tmp_dir, ["src/utils/helpers.py"])
        targeted_tests = manifest.selected_tests

        # Measure Targeted Suite Run Time
        t0 = time.perf_counter()
        import subprocess, sys
        cmd_targeted = [sys.executable, "-m", "pytest"] + targeted_tests
        proc_targeted = subprocess.run(cmd_targeted, cwd=tmp_dir, stdout=subprocess.PIPE, text=True)
        targeted_duration = time.perf_counter() - t0

        # Measure Full Suite Run Time
        all_tests = [os.path.join("tests", f) for f in os.listdir(os.path.join(tmp_dir, "tests")) if f.startswith("test_")]
        t1 = time.perf_counter()
        cmd_full = [sys.executable, "-m", "pytest"] + all_tests
        proc_full = subprocess.run(cmd_full, cwd=tmp_dir, stdout=subprocess.PIPE, text=True)
        full_duration = time.perf_counter() - t1

        ratio = targeted_duration / full_duration if full_duration > 0 else 1.0

        print(f"\nTIA Benchmark: Targeted={targeted_duration:.3f}s, Full={full_duration:.3f}s, Ratio={ratio*100:.1f}%")

        # Target Metric: < 25% duration
        assert ratio < 0.25, f"Targeted suite duration ({targeted_duration:.3f}s) must be < 25% of full suite ({full_duration:.3f}s), got {ratio*100:.1f}%"
        assert proc_targeted.returncode == 0
        assert proc_full.returncode == 0
