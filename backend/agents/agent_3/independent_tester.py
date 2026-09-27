"""
Purpose:
Task 31: Independent Testing Agent.
Implements the Zero-Trust verification engine that executes reproduction
tests and regression suites independently outside the Executor's context.

Acceptance Criteria:
- AC-E3-D1-01: Catches injected regression test failure independently and produces
  accurate VerificationReport with specific failing test names.
"""

from __future__ import annotations

import os
import re
import sys
import time
import subprocess
from typing import List, Optional, Tuple, Dict, Any

try:
    from .verification_models import VerificationReport
except (ImportError, ValueError):
    from agents.agent_3.verification_models import VerificationReport


def discover_tests_for_files(repo_root: str, changed_files: List[str]) -> List[str]:
    """
    Finds test files covering the changed source files via naming patterns
    and import references.
    """
    discovered = set()
    all_test_files = []

    # Collect all test files in the repo
    for root, _, files in os.walk(repo_root):
        for f in files:
            if (f.startswith("test_") or f.endswith("_test.py")) and f.endswith(".py"):
                rel = os.path.relpath(os.path.join(root, f), repo_root)
                all_test_files.append(rel.replace("\\", "/"))

    for changed in changed_files:
        normalized = changed.replace("\\", "/")
        basename = os.path.splitext(os.path.basename(normalized))[0]

        # 1. Naming pattern matching: client.py -> test_client.py
        for tf in all_test_files:
            test_base = os.path.splitext(os.path.basename(tf))[0]
            if test_base == f"test_{basename}" or test_base == f"{basename}_test":
                discovered.add(tf)

        # 2. Content/Import search: find tests importing this module
        module_name = basename
        for tf in all_test_files:
            full_tf_path = os.path.join(repo_root, tf)
            try:
                with open(full_tf_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if f"import {module_name}" in content or f"from " in content and module_name in content:
                        discovered.add(tf)
            except Exception:
                continue

    return sorted(list(discovered))


def _run_pytest_command(repo_root: str, test_targets: List[str], timeout_sec: int = 30) -> Tuple[int, str]:
    """
    Executes pytest on the specified targets in an isolated subprocess.
    Uses sys.executable to ensure the current environment/venv is utilized.
    """
    cmd = [sys.executable, "-m", "pytest", "-v"] + test_targets
    env = os.environ.copy()
    # Add repo_root to PYTHONPATH so modules resolve cleanly
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else repo_root

    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_sec,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        return -1, "Test execution timed out after {timeout_sec} seconds."
    except Exception as e:
        return -1, f"Failed to execute pytest: {str(e)}"


def parse_pytest_output(output: str) -> Tuple[int, int, int, List[str]]:
    """
    Parses pytest stdout to extract tests_run, passed, failed, and specific failure identifiers.
    """
    passed = 0
    failed = 0
    failed_tests = []

    # Regex to capture individual test results from verbose (-v) output
    # Example: tests/test_checkout.py::test_process_cart FAILED
    for line in output.splitlines():
        if " FAILED" in line:
            parts = line.split()
            if len(parts) >= 2:
                failed_tests.append(parts[0])

    # Match counts independently to support "X passed", "X failed", or "X failed, Y passed"
    passed_match = re.search(r"(\d+)\s+passed", output)
    if passed_match:
        passed = int(passed_match.group(1))

    failed_match = re.search(r"(\d+)\s+failed", output)
    if failed_match:
        failed = int(failed_match.group(1))

    # Fallback if summary format varied slightly but individual failures were found
    if failed == 0 and failed_tests:
        failed = len(failed_tests)

    tests_run = passed + failed
    return tests_run, passed, failed, failed_tests


def run_independent_verification(
    repo_root: str,
    changed_files: List[str],
    repro_test_path: Optional[str] = None,
    known_baseline_failures: Optional[List[str]] = None,
    timeout_sec: int = 60,
) -> VerificationReport:
    """
    Main entrypoint for Task 31.
    Independently runs reproduction tests and regression suites outside Executor context.
    """
    start_time = time.time()
    known_failures = set(known_baseline_failures or [])
    combined_logs = []

    # 1. Step 1: Execute Reproduction Test (if provided)
    repro_status = "NOT_RUN"
    if repro_test_path:
        rel_repro = os.path.relpath(repro_test_path, repo_root).replace("\\", "/") if os.path.isabs(repro_test_path) else repro_test_path
        ret_code, repro_out = _run_pytest_command(repo_root, [rel_repro], timeout_sec=timeout_sec)
        combined_logs.append(f"--- Reproduction Test ({rel_repro}) ---\n{repro_out}")
        repro_status = "PASS" if ret_code == 0 else "FAIL"

    # 2. Step 2: Discover and Run Regression Suite
    target_tests = discover_tests_for_files(repo_root, changed_files)

    # Exclude repro test from general regression list to avoid double counting
    if repro_test_path:
        norm_repro = os.path.normpath(repro_test_path)
        target_tests = [t for t in target_tests if os.path.normpath(os.path.join(repo_root, t)) != norm_repro]

    tests_run = 0
    passed = 0
    failed = 0
    new_failures = []

    if target_tests:
        ret_code, reg_out = _run_pytest_command(repo_root, target_tests, timeout_sec=timeout_sec)
        combined_logs.append(f"--- Regression Suite ---\n{reg_out}")
        tests_run, passed, failed, failed_test_names = parse_pytest_output(reg_out)

        # Catch newly injected regressions (failures that were not in baseline)
        for f in failed_test_names:
            if f not in known_failures:
                new_failures.append(f)
    else:
        combined_logs.append("--- Regression Suite ---\nNo regression tests discovered for changed files.")

    duration_ms = round((time.time() - start_time) * 1000, 2)

    return VerificationReport(
        tests_run=tests_run + (1 if repro_test_path else 0),
        passed=passed + (1 if repro_status == "PASS" else 0),
        failed=failed + (1 if repro_status == "FAIL" else 0),
        new_failures=new_failures,
        repro_test_status=repro_status,
        duration_ms=duration_ms,
        test_runner="pytest",
        logs="\n".join(combined_logs),
    )
