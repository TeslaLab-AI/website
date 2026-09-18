"""
Purpose:
Unit tests verifying Phase 1 data contracts and models.
Ensures serialization, validation, and defaults comply with Day 1 specification.
"""

from app.agents.verification_models import (
    VerificationReport,
    TestImpactManifest,
    VulnFinding,
    SecurityReport,
)


def test_verification_report_defaults():
    report = VerificationReport()
    assert report.tests_run == 0
    assert report.passed == 0
    assert report.failed == 0
    assert report.new_failures == []
    assert report.repro_test_status == "NOT_RUN"
    assert report.test_runner == "pytest"


def test_verification_report_payload():
    report = VerificationReport(
        tests_run=5,
        passed=4,
        failed=1,
        new_failures=["tests/test_checkout.py::test_process_cart"],
        repro_test_status="PASS",
        duration_ms=145.2,
    )
    data = report.model_dump()
    assert data["tests_run"] == 5
    assert len(data["new_failures"]) == 1
    assert data["repro_test_status"] == "PASS"


def test_test_impact_manifest():
    manifest = TestImpactManifest(
        changed_files=["src/payment/client.py"],
        selected_tests=["tests/test_client.py", "tests/test_checkout.py"],
        is_fallback=False,
        rationale="client.py is directly imported by test_client and checkout.py",
    )
    assert len(manifest.selected_tests) == 2
    assert not manifest.is_fallback


def test_security_models():
    vuln = VulnFinding(
        severity="critical",
        cwe="CWE-89",
        file="src/auth/service.py",
        line=12,
        description="Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')",
        remediation_hint="Use parameterized queries instead of f-strings",
    )
    report = SecurityReport(
        passed=False,
        vulnerabilities=[vuln],
        new_vulnerabilities=[vuln],
    )
    assert not report.passed
    assert report.vulnerabilities[0].cwe == "CWE-89"
    assert len(report.new_vulnerabilities) == 1
