import pytest

from deployment.validation_gate import (
    MAX_OUTPUT_CHARS,
    CheckResult,
    CheckStatus,
    check_from_command,
    evaluate_gate,
)

P, F, S, E = CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.SKIPPED, CheckStatus.ERROR


def results(lint=P, type_check=P, build=P, tests=P):
    return [
        CheckResult("lint", lint),
        CheckResult("type_check", type_check),
        CheckResult("build", build),
        CheckResult("tests", tests),
    ]


def test_all_passed_allows_deploy():
    decision = evaluate_gate(results())
    assert decision.allowed is True
    assert decision.reasons == ()
    assert decision.summary == "all checks passed"


@pytest.mark.parametrize("name", ["lint", "type_check", "build", "tests"])
def test_any_single_failure_blocks(name):
    decision = evaluate_gate(results(**{name: F}))
    assert decision.allowed is False
    assert decision.reasons == (f"{name} failed",)


def test_missing_check_blocks_fail_closed():
    decision = evaluate_gate([CheckResult("lint", P), CheckResult("build", P)])
    assert decision.allowed is False
    assert "type_check did not run" in decision.reasons
    assert "tests did not run" in decision.reasons


def test_no_results_at_all_blocks():
    assert evaluate_gate([]).allowed is False


def test_skipped_and_errored_checks_block():
    assert evaluate_gate(results(tests=S)).reasons == ("tests was skipped",)
    assert evaluate_gate(results(build=E)).reasons == ("build could not complete",)


def test_multiple_problems_are_all_reported_in_order():
    decision = evaluate_gate(results(lint=F, tests=F))
    assert decision.reasons == ("lint failed", "tests failed")
    assert decision.summary == "lint failed; tests failed"


def test_duplicate_results_all_must_pass():
    decision = evaluate_gate(results() + [CheckResult("tests", F)])
    assert decision.allowed is False


def test_names_are_normalized():
    decision = evaluate_gate([
        CheckResult("Lint", P), CheckResult("type-check", P),
        CheckResult("BUILD", P), CheckResult("tests", P),
    ])
    assert decision.allowed is True


def test_extra_checks_are_ignored():
    assert evaluate_gate(results() + [CheckResult("e2e", F)]).allowed is True


def test_custom_required_checks():
    decision = evaluate_gate([CheckResult("build", P)], required=("build",))
    assert decision.allowed is True


# -- check_from_command ----------------------------------------------------
def test_exit_code_zero_passes_nonzero_fails():
    assert check_from_command("lint", 0).status == P
    assert check_from_command("lint", 2).status == F


def test_timeout_or_missing_exit_code_is_an_error_not_a_pass():
    assert check_from_command("build", None).status == E
    assert check_from_command("build", 0, timed_out=True).status == E


def test_output_is_masked_and_trimmed_to_the_end():
    token = "ghp_" + "a1B2c3D4e5" * 4
    result = check_from_command("tests", 1, "x" * 10_000 + f" failed with token {token}")
    assert token not in result.output
    assert len(result.output) <= MAX_OUTPUT_CHARS
    assert "failed with token" in result.output  # the end is kept


def test_check_name_is_normalized_by_helper():
    assert check_from_command("Type-Check", 0).name == "type_check"