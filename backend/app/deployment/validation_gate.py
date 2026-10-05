"""Validation gate: deploy only if lint, type-check, build and tests all passed.

The sandbox (Build Engine) runs the four checks and reports the results here.
The gate fails CLOSED: a check that is missing, skipped, errored or failed
blocks the deployment, so a broken build never reaches the provider.

Typical use with a sandbox command runner:

    results = [
        check_from_command("lint", exit_code=0, output=lint_output),
        check_from_command("type_check", exit_code=0, output=tsc_output),
        check_from_command("build", exit_code=0, output=build_output),
        check_from_command("tests", exit_code=1, output=test_output),
    ]
    decision = evaluate_gate(results)   # decision.allowed == False
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from .log_masking import mask_secrets

REQUIRED_CHECKS = ("lint", "type_check", "build", "tests")
MAX_OUTPUT_CHARS = 4000  # keep the END of the output, where errors usually are


class CheckStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"  # the check could not complete (timeout, crash)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    output: str = ""
    duration_seconds: Optional[float] = None


def _normalize(name: str) -> str:
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def check_from_command(
    name: str,
    exit_code: Optional[int],
    output: str = "",
    duration_seconds: Optional[float] = None,
    timed_out: bool = False,
) -> CheckResult:
    """Build a CheckResult from a command's exit code. Output is masked and trimmed."""
    if timed_out or exit_code is None:
        status = CheckStatus.ERROR
    elif exit_code == 0:
        status = CheckStatus.PASSED
    else:
        status = CheckStatus.FAILED
    safe_output = mask_secrets(output or "")[-MAX_OUTPUT_CHARS:]
    return CheckResult(_normalize(name), status, safe_output, duration_seconds)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reasons: tuple[str, ...]

    @property
    def summary(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "all checks passed"


def evaluate_gate(
    results: Iterable[CheckResult],
    required: Iterable[str] = REQUIRED_CHECKS,
) -> GateDecision:
    by_name: dict[str, list[CheckStatus]] = {}
    for result in results:
        by_name.setdefault(_normalize(result.name), []).append(result.status)

    reasons: list[str] = []
    for name in required:
        statuses = by_name.get(_normalize(name))
        if not statuses:
            reasons.append(f"{name} did not run")
        elif all(s == CheckStatus.PASSED for s in statuses):
            continue
        elif CheckStatus.FAILED in statuses:
            reasons.append(f"{name} failed")
        elif CheckStatus.ERROR in statuses:
            reasons.append(f"{name} could not complete")
        else:
            reasons.append(f"{name} was skipped")
    return GateDecision(allowed=not reasons, reasons=tuple(reasons))