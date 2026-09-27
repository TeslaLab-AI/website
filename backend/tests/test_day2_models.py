"""
Purpose:
Unit tests verifying Day 2 shared contracts and schemas (Task 34–36).
Ensures serialization, validation, and zero-override defaults adhere to specifications.
"""

from agents.agent_3.day2_models import (
    CheckResult,
    ValidationVerdict,
    RepairPlan,
    LoopState,
    LoopIterationEvent,
)


def test_check_result_model():
    """Verify individual signal result schema and score bounds."""
    res = CheckResult(
        name="repro_test",
        passed=True,
        score=1.0,
        message="Reproduction test passed cleanly.",
        details={"duration_ms": 42.5},
    )
    assert res.passed is True
    assert res.score == 1.0
    assert res.name == "repro_test"


def test_validation_verdict_pass_payload():
    """Verify composite verdict model when all checks pass."""
    checks = {
        "requirements": CheckResult(name="requirements", passed=True, message="Scope satisfied"),
        "diff_quality": CheckResult(name="diff_quality", passed=True, message="Minimal diff (12 lines)"),
        "repro_test": CheckResult(name="repro_test", passed=True, message="Repro test PASSED"),
        "regression_tests": CheckResult(name="regression_tests", passed=True, message="0 new regressions"),
        "security_scan": CheckResult(name="security_scan", passed=True, message="0 new CWE vulnerabilities"),
    }
    verdict = ValidationVerdict(
        verdict="PASS",
        score=1.0,
        checks=checks,
        failure_reasons=[],
    )
    data = verdict.model_dump()
    assert data["verdict"] == "PASS"
    assert data["score"] == 1.0
    assert len(data["checks"]) == 5
    assert len(data["failure_reasons"]) == 0


def test_validation_verdict_fail_payload():
    """Verify composite verdict model when a single check fails."""
    checks = {
        "requirements": CheckResult(name="requirements", passed=True, message="Scope satisfied"),
        "diff_quality": CheckResult(name="diff_quality", passed=True, message="Minimal diff"),
        "repro_test": CheckResult(name="repro_test", passed=True, message="Repro test PASSED"),
        "regression_tests": CheckResult(name="regression_tests", passed=False, message="1 test failed"),
        "security_scan": CheckResult(name="security_scan", passed=True, message="Clean scan"),
    }
    verdict = ValidationVerdict(
        verdict="FAIL",
        score=0.8,
        checks=checks,
        failure_reasons=["Regression test suite broke: test_checkout.py::test_process_cart"],
    )
    assert verdict.verdict == "FAIL"
    assert len(verdict.failure_reasons) == 1


def test_repair_plan_model():
    """Verify targeted repair plan attributes and attempt tracking."""
    plan = RepairPlan(
        attempt=2,
        target_components=["src/catalog/paginate.py"],
        diagnosis="Off-by-one slice calculation: end index omitted last element.",
        adjusted_patch="end = start + page_size",
        status="RETRY",
    )
    assert plan.attempt == 2
    assert plan.status == "RETRY"
    assert len(plan.target_components) == 1


def test_loop_state_circuit_breakers():
    """Verify loop state defaults enforce circuit breaker thresholds."""
    state = LoopState(session_id="session-test-123")
    assert state.max_cost == 0.50, "Cost breaker ceiling must be $0.50"
    assert state.max_time_sec == 300.0, "Timeout breaker ceiling must be 300s (5 minutes)"
    assert state.max_attempts == 3, "Max repair attempts must be 3"
    assert state.circuit_breaker_tripped is False
    assert state.diff_hashes == []
