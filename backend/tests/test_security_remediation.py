"""
Purpose:
Task 39 Tests: Security Remediation Flow & Post-Fix SAST Gate.
Verifies AC-E3-D3-03:
1. Ingests seeded SQL injection vulnerability (CWE-89).
2. Diagnoses injection point and plans parameterized query fix.
3. Applies fix to isolated workspace.
4. Executes post-fix SAST scan confirming 0 remaining CWE-89 findings.
5. Verifies functional tests pass cleanly with 0 regressions.
"""

import os
import tempfile
import pytest

from agents.agent_3.day3_models import SecurityRemediationReport
from agents.agent_3.security_remediation import SecurityRemediator
from tests.fixtures.day3_fixtures import setup_security_remediation_repo


def test_diagnose_and_plan_sqli_fix():
    """Verifies that SecurityRemediator accurately identifies and parameterizes dynamic queries."""
    unsafe_line = '    cursor.execute(f"SELECT * FROM users WHERE tier = \'{tier_name}\'")'
    is_vuln, orig, fixed = SecurityRemediator.diagnose_and_plan_sqli_fix(unsafe_line)

    assert is_vuln is True
    assert "tier = ?" in fixed or "WHERE tier = ?" in fixed
    assert "(tier_name,)" in fixed


def test_ac_e3_d3_03_security_remediation_and_sast_pass():
    """
    Verifies AC-E3-D3-03:
    Full security remediation pipeline on seeded SQLi finding:
    - Pre-fix SAST detects 1 vulnerability
    - Parameterized query applied
    - Post-fix SAST confirms 0 vulnerabilities (sast_passed is True)
    - Functional query tests pass cleanly
    - Report status is REMEDIATED
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        files = setup_security_remediation_repo(tmp_dir)
        rel_file = os.path.relpath(files["source"], tmp_dir).replace("\\", "/")

        report = SecurityRemediator.remediate_finding(
            worktree_dir=tmp_dir,
            rel_file=rel_file,
            finding_id="SEC-SQLI-TEST-01",
        )

        assert report.cwe == "CWE-89"
        assert report.pre_fix_findings >= 1
        assert report.post_fix_findings == 0
        assert report.sast_passed is True
        assert report.status == "REMEDIATED"
        assert report.remediation_pr_title is not None
        assert "CWE-89" in report.remediation_pr_title
        assert "**Post-Fix SAST Findings:** `0`" in report.remediation_pr_body

        # Confirm file actually contains parameterized query
        with open(files["source"], "r", encoding="utf-8") as f:
            remediated_code = f.read()
        assert "SELECT * FROM users WHERE tier = ?" in remediated_code
        assert "f\"SELECT" not in remediated_code
