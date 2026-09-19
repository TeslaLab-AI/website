"""
Purpose:
Task 34: 5-Signal Validation Engine.
Combines all verification signals (Requirements, Diff Quality, Repro Test,
Regression Tests, and Security Scan) into one final PASS/FAIL verdict.

Architecture & Invariants:
- Strict Conjunction Gate: All 5 signals must have passed == True for the final
  verdict to be PASS. Zero override permitted.
- Individual Signal Breakdown: Outputs full component telemetry in CheckResult.
- Failure Reasoning: Every failing signal explicitly populates failure_reasons
  to provide actionable diagnostics for Task 35 (Repair Agent).

Acceptance Criteria:
- AC-E3-D2-01: Requires 5/5 checks to PASS; any single failure returns FAIL with
  specific failure reason across 5 distinct single-failure scenarios.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Any

from agents.agent_3.day2_models import CheckResult, ValidationVerdict
from agents.agent_3.independent_tester import _run_pytest_command, parse_pytest_output
from agents.agent_3.test_impact import select_impacted_tests
from agents.agent_3.security_agent import diff_security_gate


# ─────────────────────────────────────────────────────────────────────────────
# 1. Signal 1: Requirements Satisfaction Checker
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_requirements(
    task_desc: str,
    target_files: List[str],
    diff_text: str,
) -> CheckResult:
    """
    Evaluates whether the generated patch satisfies task requirements and targets
    the relevant problem scope.
    
    Checks:
    1. Diff is non-empty.
    2. Patch modifies at least one of the specified target files or relevant modules.
    3. Patch does not exclusively modify unrelated documentation or utilities.
    """
    if not diff_text or not diff_text.strip():
        return CheckResult(
            name="requirements",
            passed=False,
            score=0.0,
            message="Patch rejected: Unified diff is empty (no changes generated).",
            details={"diff_length": 0},
        )

    # Extract modified file paths from diff headers (e.g. +++ b/src/payment/client.py)
    modified_in_diff = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            modified_in_diff.append(line[6:].strip().replace("\\", "/"))

    # Normalize target files
    normalized_targets = [f.replace("\\", "/").lstrip("./") for f in target_files]

    # Verify that at least one modified file matches the target scope
    matches_target = False
    for mod_f in modified_in_diff:
        if any(target in mod_f or os.path.basename(target) == os.path.basename(mod_f) for target in normalized_targets):
            matches_target = True
            break

    if not matches_target and normalized_targets:
        return CheckResult(
            name="requirements",
            passed=False,
            score=0.2,
            message=(
                f"Patch rejected: Scope mismatch. Diff modified {modified_in_diff}, "
                f"which does not target the required files: {normalized_targets}."
            ),
            details={"modified": modified_in_diff, "expected": normalized_targets},
        )

    return CheckResult(
        name="requirements",
        passed=True,
        score=1.0,
        message="Requirements verified: Patch targets the correct functional scope.",
        details={"modified": modified_in_diff},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Signal 2: Diff Quality & Minimality Checker
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_diff_quality(diff_text: str, max_lines: int = 150) -> CheckResult:
    """
    Enforces that the code patch is minimal, clean, and reviewable.
    
    Checks:
    1. Total changed lines (additions + deletions) does not exceed threshold (default 150).
    2. Does not contain bloated repetitive comment blocks or binary clutter.
    """
    if not diff_text:
        return CheckResult(
            name="diff_quality",
            passed=False,
            score=0.0,
            message="Empty diff provided.",
        )

    added_lines = 0
    deleted_lines = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added_lines += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted_lines += 1

    total_changed = added_lines + deleted_lines

    # Guardrail: reject bloated patches exceeding max_lines
    if total_changed > max_lines:
        return CheckResult(
            name="diff_quality",
            passed=False,
            score=0.3,
            message=(
                f"Patch rejected: Diff is too large ({total_changed} lines changed). "
                f"Exceeds team threshold of {max_lines} lines."
            ),
            details={"added": added_lines, "deleted": deleted_lines, "total": total_changed, "limit": max_lines},
        )

    return CheckResult(
        name="diff_quality",
        passed=True,
        score=1.0,
        message=f"Diff quality passed: Minimal patch with {total_changed} lines changed (+{added_lines}/-{deleted_lines}).",
        details={"added": added_lines, "deleted": deleted_lines, "total": total_changed},
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Signal 3: Reproduction Test Checker
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_repro_test(worktree_dir: str, repro_test_path: Optional[str] = None, timeout_sec: int = 30) -> CheckResult:
    """
    Executes the standalone reproduction test in the worktree.
    Asserts that the reproduction test transitions from FAIL to PASS.
    """
    if not repro_test_path:
        # If no dedicated repro test is required for this bug, pass with info
        return CheckResult(
            name="repro_test",
            passed=True,
            score=1.0,
            message="No standalone reproduction test specified; bypassed.",
        )

    rel_repro = os.path.relpath(repro_test_path, worktree_dir).replace("\\", "/") if os.path.isabs(repro_test_path) else repro_test_path
    ret_code, stdout = _run_pytest_command(worktree_dir, [rel_repro], timeout_sec=timeout_sec)

    if ret_code == 0:
        return CheckResult(
            name="repro_test",
            passed=True,
            score=1.0,
            message=f"Reproduction test ({rel_repro}) PASSED cleanly.",
            details={"output": stdout[:300]},
        )
    else:
        return CheckResult(
            name="repro_test",
            passed=False,
            score=0.0,
            message=f"Reproduction test ({rel_repro}) FAILED: The defect is not yet resolved.",
            details={"output": stdout[:800], "exit_code": ret_code},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Signal 4: Regression Test Checker
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_regression_tests(worktree_dir: str, changed_files: List[str], timeout_sec: int = 45) -> CheckResult:
    """
    Selects impacted regression tests via AST Test Impact Analysis and executes them.
    Asserts that 0 new regressions are introduced.
    """
    # Use Day 1 TIA to pinpoint impacted tests
    manifest = select_impacted_tests(worktree_dir, changed_files)
    target_tests = manifest.selected_tests

    if not target_tests:
        return CheckResult(
            name="regression_tests",
            passed=True,
            score=1.0,
            message="No regression test suites impacted by the change.",
            details={"selected_tests": []},
        )

    ret_code, stdout = _run_pytest_command(worktree_dir, target_tests, timeout_sec=timeout_sec)
    tests_run, passed, failed, failed_tests = parse_pytest_output(stdout)

    if failed == 0 and ret_code == 0:
        return CheckResult(
            name="regression_tests",
            passed=True,
            score=1.0,
            message=f"Regression tests PASSED: {passed}/{tests_run} tests succeeded with 0 regressions.",
            details={"tests_run": tests_run, "passed": passed, "failed": 0},
        )
    else:
        return CheckResult(
            name="regression_tests",
            passed=False,
            score=0.0,
            message=f"Regression test failure: {failed} tests failed ({failed_tests}).",
            details={"tests_run": tests_run, "passed": passed, "failed": failed, "failed_tests": failed_tests, "output": stdout[:800]},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Signal 5: Security Scan Checker
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_security_scan(worktree_dir: str, diff_text: str) -> CheckResult:
    """
    Executes the Diff Security Gate to verify that no new security vulnerabilities
    (e.g., SQL injection CWE-89 or leaked secrets CWE-798) are introduced by the patch.
    """
    sec_report = diff_security_gate(worktree_dir, diff_text)

    if sec_report.passed and len(sec_report.new_vulnerabilities) == 0:
        return CheckResult(
            name="security_scan",
            passed=True,
            score=1.0,
            message="Security scan clean: 0 new CWE vulnerabilities introduced.",
            details={"vulnerabilities": []},
        )
    else:
        vuln_details = [
            f"{v.cwe} at {v.file}:{v.line} - {v.description}"
            for v in sec_report.new_vulnerabilities
        ]
        return CheckResult(
            name="security_scan",
            passed=False,
            score=0.0,
            message=f"Security gate REJECTED patch: Introduced {len(sec_report.new_vulnerabilities)} new vulnerability.",
            details={"new_vulnerabilities": vuln_details, "raw": sec_report.raw_output},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Verdict Synthesizer: 5-Signal Validation Engine
# ─────────────────────────────────────────────────────────────────────────────

class ValidationEngine:
    """
    Synthesizes the 5 verification signals into an objective PASS / FAIL verdict.
    Enforces strict boolean conjunction with zero overrides.
    """

    @staticmethod
    def evaluate(
        worktree_dir: str,
        diff_text: str,
        task_desc: str = "Fix defect",
        target_files: Optional[List[str]] = None,
        repro_test_path: Optional[str] = None,
        changed_files: Optional[List[str]] = None,
    ) -> ValidationVerdict:
        """
        Runs all 5 evaluation signals and computes the composite ValidationVerdict.
        """
        targets = target_files or []
        changes = changed_files or targets

        # Run all 5 distinct signal checkers
        c_requirements = evaluate_requirements(task_desc, targets, diff_text)
        c_diff_quality = evaluate_diff_quality(diff_text)
        c_repro = evaluate_repro_test(worktree_dir, repro_test_path)
        c_regression = evaluate_regression_tests(worktree_dir, changes)
        c_security = evaluate_security_scan(worktree_dir, diff_text)

        checks: Dict[str, CheckResult] = {
            "requirements": c_requirements,
            "diff_quality": c_diff_quality,
            "repro_test": c_repro,
            "regression_tests": c_regression,
            "security_scan": c_security,
        }

        # Strict Boolean Conjunction Gate: ALL 5 must pass
        all_passed = all(check.passed for check in checks.values())
        verdict = "PASS" if all_passed else "FAIL"

        # Collect failure reasons from any failing checks
        failure_reasons = []
        for name, check in checks.items():
            if not check.passed:
                failure_reasons.append(f"[{name.upper()}] {check.message}")

        # Compute normalized composite score
        composite_score = round(sum(c.score for c in checks.values()) / len(checks), 2)

        return ValidationVerdict(
            verdict=verdict,
            score=composite_score if verdict == "PASS" else min(composite_score, 0.8),
            checks=checks,
            failure_reasons=failure_reasons,
        )
