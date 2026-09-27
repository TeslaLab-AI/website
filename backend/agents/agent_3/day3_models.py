"""
Purpose:
Day 3 Shared Contracts and Data Models for Engineer 3:
Tasks 37, 38, and 39 (Closed Loop PR, Dependency Agent, and Security Remediation).

Shared Contracts specified in Page 5 of Stage 0 Specification:
1. PRManifest: Structured metadata and description for automated GitHub Pull Request creation.
2. DependencyFinding: Vulnerability / version delta input for Dependency Agent.
3. DependencyPlan: Version bump plan, breaking change analysis, and code adjustment manifest.
4. SecurityRemediationReport: Pre/post SAST verification and remediation audit for security defects.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# 1. Task 37 Contract: PRManifest
# ─────────────────────────────────────────────────────────────────────────────

class PRManifest(BaseModel):
    """
    Shared Contract for automated Pull Request generation (Task 37).
    Standardizes title, markdown description, branches, labels, and verification proofs.
    """
    title: str = Field(..., description="Clear, descriptive PR title following conventional commit format")
    body_markdown: str = Field(..., description="Structured PR description markdown containing root cause, changes, test evidence")
    branch_name: str = Field(..., description="Isolated task branch name (e.g. task/bugfix-pagination-slice)")
    target_branch: str = Field(default="main", description="Target upstream branch to merge into")
    
    labels: List[str] = Field(
        default_factory=lambda: ["ai-generated", "bug-fix", "stage-0"],
        description="Mandatory GitHub labels per Task 37 specification"
    )
    linked_issue_id: Optional[str] = Field(default=None, description="Original issue or defect ticket ID (e.g. #42)")
    
    verification_badges: Dict[str, str] = Field(
        default_factory=dict,
        description="Verification badges indicating 5-Signal validation, TIA speedup, and SAST cleanliness"
    )
    
    pr_url: Optional[str] = Field(default=None, description="Live GitHub Pull Request URL or local bare remote reference")
    status: str = Field(default="DRAFT", description="PR status: DRAFT, OPEN, MERGED, FAILED")
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Task 38 Contract: DependencyFinding & DependencyPlan
# ─────────────────────────────────────────────────────────────────────────────

class DependencyFinding(BaseModel):
    """
    Input schema for the Dependency Agent (Task 38).
    Represents an outdated or vulnerable package detected in the workspace manifests.
    """
    package: str = Field(..., description="Name of the third-party package (e.g. 'requests', 'pydantic', 'lodash')")
    current_version: str = Field(..., description="Currently locked or declared version (e.g. '2.25.1')")
    target_version: str = Field(..., description="Target patched/upgraded version (e.g. '2.31.0')")
    advisory_id: Optional[str] = Field(default=None, description="Vulnerability or CVE reference (e.g. 'CVE-2023-32681', 'GHSA-j8r2-6x86-q33q')")
    severity: str = Field(default="HIGH", description="Severity ranking: LOW, MODERATE, HIGH, CRITICAL")
    description: str = Field(default="", description="Summary of vulnerability or upgrade motivation")
    ecosystem: str = Field(default="pip", description="Package manager ecosystem: 'pip' (Python) or 'npm' (JavaScript)")


class DependencyPlan(BaseModel):
    """
    Output schema produced by Dependency Agent (Task 38).
    Outlines manifest modifications, breaking API change mitigations, and test validation.
    """
    finding_id: str = Field(..., description="Identifier of the source DependencyFinding")
    package: str = Field(..., description="Package name being upgraded")
    manifest_file: str = Field(..., description="Relative path to package manifest (pyproject.toml, package.json, requirements.txt)")
    old_version: str = Field(..., description="Previous version constraint")
    new_version: str = Field(..., description="Upgraded version constraint")
    
    breaking_changes: List[str] = Field(default_factory=list, description="List of detected breaking API changes between versions")
    affected_call_sites: List[str] = Field(default_factory=list, description="Repo file paths and functions calling modified APIs")
    code_adjustments: Dict[str, str] = Field(default_factory=dict, description="Mapping of target files to corrective patch code")
    
    lockfile_updated: bool = Field(default=False, description="True if lockfile was successfully regenerated or verified")
    status: str = Field(default="PLANNED", description="Status: PLANNED, APPLIED, VALIDATED, REJECTED")
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Task 39 Contract: SecurityRemediationReport
# ─────────────────────────────────────────────────────────────────────────────

class SecurityRemediationReport(BaseModel):
    """
    Output schema for Security Remediation Flow (Task 39).
    Audits the full security fix lifecycle from initial SAST finding to verified post-fix scan.
    """
    finding_id: str = Field(..., description="Identifier of the security finding (e.g. 'SEC-SQLI-001')")
    cwe: str = Field(default="CWE-89", description="CWE classification identifier (e.g. CWE-89 for SQL Injection)")
    vulnerable_file: str = Field(..., description="File path containing the vulnerable code")
    vulnerable_line: int = Field(..., description="Line number of the security flaw")
    
    original_pattern: str = Field(..., description="Original unsafe code snippet (e.g. raw string concatenation in SQL query)")
    remediated_pattern: str = Field(..., description="Safe replacement (e.g. parameterized query with placeholder tuples)")
    
    pre_fix_findings: int = Field(..., description="Count of SAST findings prior to remediation (e.g. 1)")
    post_fix_findings: int = Field(..., description="Count of SAST findings after remediation (must be 0 for PASS)")
    sast_passed: bool = Field(default=False, description="True if post-fix SAST confirms 0 remaining vulnerabilities")
    
    remediation_pr_title: Optional[str] = Field(default=None, description="Title of generated security PR")
    remediation_pr_body: Optional[str] = Field(default=None, description="Detailed PR markdown explanation with remediation proof")
    status: str = Field(default="REMEDIATED", description="Outcome: REMEDIATED or FAILED")
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
