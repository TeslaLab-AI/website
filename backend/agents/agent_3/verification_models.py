"""
Purpose:
Defines the shared data contracts for Engineer 3 verification pipeline.

Contracts:
- VerificationReport: Independent test outcomes and reproduction test status.
- TestImpactManifest: Targeted test selection with fallback metadata.
- VulnFinding: Standardized security vulnerability with CWE classification.
- SecurityReport: Pre/post diff security analysis and gate decision.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class VerificationReport(BaseModel):
    """Output contract for Task 31: Independent Testing Agent."""
    tests_run: int = Field(default=0, description="Total number of tests executed")
    passed: int = Field(default=0, description="Number of passing tests")
    failed: int = Field(default=0, description="Number of failing tests")
    new_failures: List[str] = Field(default_factory=list, description="Tests failing due to newly injected regressions")
    repro_test_status: str = Field(default="NOT_RUN", description="Status of reproduction test: PASS, FAIL, or NOT_RUN")
    duration_ms: float = Field(default=0.0, description="Execution duration in milliseconds")
    test_runner: str = Field(default="pytest", description="Runner utilized (pytest, npm, smoke_check)")
    logs: str = Field(default="", description="Console output and stack traces")


class TestImpactManifest(BaseModel):
    """Output contract for Task 32: Test Impact Analysis."""
    __test__ = False
    changed_files: List[str] = Field(default_factory=list, description="Source files modified in the diff")
    selected_tests: List[str] = Field(default_factory=list, description="Targeted test files to execute")
    is_fallback: bool = Field(default=False, description="True if dependency graph was ambiguous and fell back to directory tests")
    rationale: str = Field(default="", description="Explanation of dependency traversal or fallback reasoning")


class VulnFinding(BaseModel):
    """Individual vulnerability finding with CWE taxonomy."""
    severity: str = Field(..., description="Vulnerability severity: low, medium, high, critical")
    cwe: str = Field(..., description="Common Weakness Enumeration ID (e.g. CWE-89, CWE-798)")
    file: str = Field(..., description="File path relative to repository root")
    line: int = Field(default=1, description="Line number where vulnerability was detected")
    description: str = Field(..., description="Detailed description of the security defect")
    remediation_hint: str = Field(default="", description="Actionable recommendation to fix the defect")


class SecurityReport(BaseModel):
    """Output contract for Task 33: Security Agent and Diff Security Gate."""
    passed: bool = Field(default=True, description="True if no high/critical vulnerabilities exist and diff gate passes")
    vulnerabilities: List[VulnFinding] = Field(default_factory=list, description="All detected vulnerabilities")
    new_vulnerabilities: List[VulnFinding] = Field(default_factory=list, description="Vulnerabilities newly introduced by the diff")
    resolved_vulnerabilities: List[VulnFinding] = Field(default_factory=list, description="Prior vulnerabilities resolved by the diff")
    raw_output: str = Field(default="", description="Raw scanner logs or summaries")
