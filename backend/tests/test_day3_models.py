"""
Purpose:
Tests for Day 3 Shared Contracts and Data Models (Tasks 37–39).
Verifies serialization, default values, and schema constraints for:
- PRManifest (Task 37)
- DependencyFinding & DependencyPlan (Task 38)
- SecurityRemediationReport (Task 39)
"""

import pytest
from agents.agent_3.day3_models import (
    PRManifest,
    DependencyFinding,
    DependencyPlan,
    SecurityRemediationReport,
)


def test_pr_manifest_model():
    """Verifies PRManifest defaults and mandatory labels per Task 37."""
    manifest = PRManifest(
        title="fix(catalog): resolve off-by-one boundary in pagination slice",
        body_markdown="## Summary\nResolves boundary fault.\n## Verification\n5/5 PASS",
        branch_name="task/bugfix-pagination-slice",
        linked_issue_id="#42",
        verification_badges={"5-signal": "PASS", "sast": "CLEAN"},
    )

    assert manifest.target_branch == "main"
    assert "ai-generated" in manifest.labels
    assert "bug-fix" in manifest.labels
    assert "stage-0" in manifest.labels
    assert manifest.linked_issue_id == "#42"
    assert manifest.status == "DRAFT"

    payload = manifest.model_dump()
    assert payload["branch_name"] == "task/bugfix-pagination-slice"
    assert payload["labels"] == ["ai-generated", "bug-fix", "stage-0"]


def test_dependency_models():
    """Verifies DependencyFinding and DependencyPlan contracts per Task 38."""
    finding = DependencyFinding(
        package="requests",
        current_version="2.25.1",
        target_version="2.31.0",
        advisory_id="CVE-2023-32681",
        severity="HIGH",
        description="Header leak on cross-origin redirect",
        ecosystem="pip",
    )
    assert finding.package == "requests"
    assert finding.severity == "HIGH"

    plan = DependencyPlan(
        finding_id="DEP-REQ-01",
        package="requests",
        manifest_file="pyproject.toml",
        old_version="2.25.1",
        new_version="2.31.0",
        breaking_changes=[],
        affected_call_sites=["src/client/api.py"],
        code_adjustments={},
        lockfile_updated=True,
        status="PLANNED",
    )
    assert plan.manifest_file == "pyproject.toml"
    assert plan.lockfile_updated is True
    assert plan.status == "PLANNED"


def test_security_remediation_model():
    """Verifies SecurityRemediationReport schema per Task 39."""
    report = SecurityRemediationReport(
        finding_id="SEC-SQLI-01",
        cwe="CWE-89",
        vulnerable_file="src/db/user_repo.py",
        vulnerable_line=3,
        original_pattern='cursor.execute(f"SELECT * FROM users WHERE tier = \'{tier_name}\'")',
        remediated_pattern='cursor.execute("SELECT * FROM users WHERE tier = ?", (tier_name,))',
        pre_fix_findings=1,
        post_fix_findings=0,
        sast_passed=True,
        remediation_pr_title="sec(db): remediate CWE-89 SQL injection via parameterized queries",
        status="REMEDIATED",
    )
    assert report.cwe == "CWE-89"
    assert report.pre_fix_findings == 1
    assert report.post_fix_findings == 0
    assert report.sast_passed is True
    assert report.status == "REMEDIATED"
