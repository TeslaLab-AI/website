"""
Purpose:
Acceptance and unit tests for Task 33: Security Agent and Diff Security Gate.

Verifies:
- AC-E3-D1-03: Security Vulnerability Detection: Execute Security Agent on seeded
  SQL injection defect; assert detection with exact CWE-89 classification
  and remediation advice.
- Secret Detection: Detects hardcoded API keys and tokens (CWE-798).
- Diff Security Gate: Rejects patches introducing new vulnerabilities; approves clean fixes.
"""

import os
import tempfile
import pytest

from tests.fixtures.day1_fixtures import (
    SEEDED_SQL_INJECTION_CODE,
    SEEDED_SAFE_SQL_CODE,
    SEEDED_SECRET_LEAK_CODE,
    SAMPLE_DIFF_CLEAN,
    SAMPLE_DIFF_WITH_SQLI,
    SAMPLE_DIFF_WITH_SECRET,
)
from app.agents.security_agent import (
    scan_codebase_security,
    scan_file_security,
    diff_security_gate,
    CWE_SQLI,
    CWE_HARDCODED_SECRET,
)


def test_ac_e3_d1_03_seeded_sql_injection_detection():
    """
    AC-E3-D1-03 Acceptance Test:
    Execute Security Agent on seeded SQL injection defect.
    Asserts detection with exact CWE-89 classification and remediation advice.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        vuln_file = os.path.join(tmp_dir, "db_service.py")
        with open(vuln_file, "w", encoding="utf-8") as f:
            f.write(SEEDED_SQL_INJECTION_CODE)

        report = scan_codebase_security(tmp_dir)

        # Assertions for AC-E3-D1-03:
        assert not report.passed, "Security scan must fail when SQL injection is present"
        assert len(report.vulnerabilities) > 0, "Must detect at least one vulnerability"

        sqli_finding = next((v for v in report.vulnerabilities if v.cwe == CWE_SQLI), None)
        assert sqli_finding is not None, f"Expected {CWE_SQLI} in vulnerabilities, got: {report.vulnerabilities}"
        assert sqli_finding.cwe == "CWE-89", "Must report exact CWE-89 classification"
        assert sqli_finding.severity == "critical"
        assert "parameterized" in sqli_finding.remediation_hint.lower(), "Must provide remediation advice"
        assert sqli_finding.line > 0


def test_secret_detection_cwe_798():
    """Verify that hardcoded API tokens are detected with CWE-798."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        secret_file = os.path.join(tmp_dir, "auth_config.py")
        with open(secret_file, "w", encoding="utf-8") as f:
            f.write(SEEDED_SECRET_LEAK_CODE)

        report = scan_codebase_security(tmp_dir)

        assert not report.passed
        secret_finding = next((v for v in report.vulnerabilities if v.cwe == CWE_HARDCODED_SECRET), None)
        assert secret_finding is not None, f"Expected {CWE_HARDCODED_SECRET} in vulnerabilities"
        assert "environment variable" in secret_finding.remediation_hint.lower()


def test_diff_security_gate_rejects_sqli_patch():
    """Verify that Diff Security Gate rejects a patch introducing new SQL injection."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Initial clean repo
        service_file = os.path.join(tmp_dir, "service.py")
        with open(service_file, "w", encoding="utf-8") as f:
            f.write("def query_account(user_id):\n    return []\n")

        diff = """--- a/service.py
+++ b/service.py
@@ -1,2 +1,3 @@
 def query_account(user_id):
+    cursor.execute(f"SELECT * FROM accounts WHERE id = '{user_id}'")
     return []
"""

        gate_report = diff_security_gate(tmp_dir, diff)

        assert not gate_report.passed, "Diff security gate must reject patch introducing SQLi"
        assert any(v.cwe == CWE_SQLI for v in gate_report.new_vulnerabilities)
        assert "REJECTED" in gate_report.raw_output


def test_diff_security_gate_rejects_secret_patch():
    """Verify that Diff Security Gate rejects a patch introducing hardcoded credentials."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        gate_report = diff_security_gate(tmp_dir, SAMPLE_DIFF_WITH_SECRET)

        assert not gate_report.passed, "Diff security gate must reject patch introducing credentials"
        assert any(v.cwe == CWE_HARDCODED_SECRET for v in gate_report.new_vulnerabilities)


def test_diff_security_gate_approves_clean_fix():
    """Verify that Diff Security Gate approves a patch that resolves a vulnerability cleanly."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # File initially has SQL injection
        service_file = os.path.join(tmp_dir, "service.py")
        with open(service_file, "w", encoding="utf-8") as f:
            f.write(SEEDED_SQL_INJECTION_CODE)

        baseline = scan_codebase_security(tmp_dir)
        assert not baseline.passed

        # Now executor applies clean fix with parameterized query
        with open(service_file, "w", encoding="utf-8") as f:
            f.write(SEEDED_SAFE_SQL_CODE)

        clean_diff = """--- a/service.py
+++ b/service.py
@@ -6,2 +6,2 @@
-    query = f"SELECT id, username, email FROM users WHERE username = '{username}'"
-    cursor.execute(query)
+    query = "SELECT id, username, email FROM users WHERE username = ?"
+    cursor.execute(query, (username,))
"""

        gate_report = diff_security_gate(tmp_dir, clean_diff, baseline_report=baseline)

        assert gate_report.passed, "Diff security gate must approve clean fix"
        assert len(gate_report.new_vulnerabilities) == 0
        assert len(gate_report.resolved_vulnerabilities) > 0, "Must identify that prior SQLi is resolved"
        assert any(v.cwe == CWE_SQLI for v in gate_report.resolved_vulnerabilities)
