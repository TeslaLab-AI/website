"""
Purpose:
Day 4 Test Fixtures for Engineer 3 (Tasks 40–42).

Includes:
1. 6 Seeded Findings for Batch Unified Pipeline Execution (Task 40 / AC-E3-D4-01):
   - 3 Bugs (Pagination off-by-one, Zero fee calculation, Inverted boolean flag)
   - 2 Dependencies (Requests security bump, Pydantic V2 breaking change upgrade)
   - 1 Security Defect (CWE-89 SQL Injection)
2. Seeded Memory Records for Memory Retrieval & Cross-Repo Isolation (Task 42 / AC-E3-D4-03 & AC-E3-D4-04).
"""

from __future__ import annotations

import os
from typing import Dict, List, Any

from agents.agent_3.day4_models import (
    FindingCategory,
    UnifiedFinding,
    MemoryRecord,
)
from tests.fixtures.day2_fixtures import (
    setup_repair_benchmark_repo,
    setup_bug2_zero_fee_repo,
    setup_bug4_inverted_boolean_repo,
)
from tests.fixtures.day3_fixtures import (
    setup_dependency_repo_pyproject,
    setup_dependency_repo_breaking_api,
    setup_security_remediation_repo,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. The 6 Seeded Canonical Findings (Task 40)
# ─────────────────────────────────────────────────────────────────────────────

SEEDED_FINDINGS_6: List[UnifiedFinding] = [
    # Finding 1 (Bug 1): Pagination Slice Boundary
    UnifiedFinding(
        finding_id="BUG-PAGINATE-01",
        category=FindingCategory.BUG,
        title="Off-by-one boundary calculation in catalog pagination slice",
        description="paginate_items slice end boundary omits the 5th item when page_size=5.",
        severity="HIGH",
        target_files=["src/catalog/paginate.py"],
        repo_id="repo_stage0_main",
        metadata={"defect_type": "OFF_BY_ONE", "expected_items": 5, "actual_items": 4},
    ),
    # Finding 2 (Bug 2): Zero Fee Guardrail
    UnifiedFinding(
        finding_id="BUG-ZERO-FEE-02",
        category=FindingCategory.BUG,
        title="Fee calculator returns negative value on zero amount",
        description="calculate_fee fails to handle amount <= 0.0, returning negative fee.",
        severity="MEDIUM",
        target_files=["src/payment/client.py"],
        repo_id="repo_stage0_main",
        metadata={"defect_type": "ZERO_FEE", "amount": 0.0},
    ),
    # Finding 3 (Bug 3): Inverted Boolean Validator
    UnifiedFinding(
        finding_id="BUG-BOOL-FLAG-03",
        category=FindingCategory.BUG,
        title="Inverted boolean validation in auth token checker",
        description="validate_token returns False for valid tokens and True for invalid ones.",
        severity="HIGH",
        target_files=["src/auth/validator.py"],
        repo_id="repo_stage0_main",
        metadata={"defect_type": "BOOLEAN_FLAG"},
    ),
    # Finding 4 (Dep 1): Requests Security Bump
    UnifiedFinding(
        finding_id="DEP-REQ-01",
        category=FindingCategory.DEPENDENCY,
        title="CVE-2023-32681: Outdated requests 2.25.1 vulnerability",
        description="Requests leaks Proxy-Authorization header during cross-origin redirect.",
        severity="HIGH",
        target_files=["pyproject.toml"],
        repo_id="repo_stage0_main",
        metadata={"package": "requests", "current": "2.25.1", "target": "2.31.0", "cve": "CVE-2023-32681"},
    ),
    # Finding 5 (Dep 2): Pydantic V2 Breaking Upgrade
    UnifiedFinding(
        finding_id="DEP-PYD-02",
        category=FindingCategory.DEPENDENCY,
        title="Pydantic V1 -> V2 breaking API upgrade",
        description="Pydantic 1.8.2 upgraded to 2.4.2; requires migrating parse_obj to model_validate.",
        severity="MEDIUM",
        target_files=["requirements.txt", "src/models/user.py"],
        repo_id="repo_stage0_main",
        metadata={"package": "pydantic", "current": "1.8.2", "target": "2.4.2", "breaking": True},
    ),
    # Finding 6 (Security 1): CWE-89 SQL Injection
    UnifiedFinding(
        finding_id="SEC-SQLI-01",
        category=FindingCategory.SECURITY,
        title="CWE-89: SQL Injection in user tier query",
        description="cursor.execute uses dynamic string interpolation rather than parameterized placeholders.",
        severity="CRITICAL",
        target_files=["src/db/user_repo.py"],
        repo_id="repo_stage0_main",
        metadata={"cwe": "CWE-89", "rule": "avoid-dynamic-sql-injection"},
    ),
]


def setup_workspace_for_finding(worktree_dir: str, finding: UnifiedFinding) -> Dict[str, str]:
    """
    Prepares a clean, isolated workspace populated with the corresponding defect
    for any of the 6 canonical seeded findings.
    """
    if finding.finding_id == "BUG-PAGINATE-01":
        return setup_repair_benchmark_repo(worktree_dir)
    elif finding.finding_id == "BUG-ZERO-FEE-02":
        return setup_bug2_zero_fee_repo(worktree_dir)
    elif finding.finding_id == "BUG-BOOL-FLAG-03":
        return setup_bug4_inverted_boolean_repo(worktree_dir)
    elif finding.finding_id == "DEP-REQ-01":
        return setup_dependency_repo_pyproject(worktree_dir)
    elif finding.finding_id == "DEP-PYD-02":
        return setup_dependency_repo_breaking_api(worktree_dir)
    elif finding.finding_id == "SEC-SQLI-01":
        return setup_security_remediation_repo(worktree_dir)
    else:
        raise ValueError(f"Unknown seeded finding ID: {finding.finding_id}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Seeded Memory Records for Retrieval & Tenant Isolation (Task 42)
# ─────────────────────────────────────────────────────────────────────────────

SEEDED_MEMORIES_TENANT_A: List[MemoryRecord] = [
    MemoryRecord(
        task_id="TASK-MEM-A01",
        repo_id="repo_alpha",
        finding_type="BUG",
        root_cause_pattern="Database connection pool timeout due to missing timeout parameter",
        solution_pattern="Set pool_timeout=30.0 and max_overflow=10 on engine create_pool()",
        affected_files=["src/db/connection.py"],
        outcome="SUCCESS",
        human_feedback="Approved by reviewer: fixed persistent connection drops",
    ),
    MemoryRecord(
        task_id="TASK-MEM-A02",
        repo_id="repo_alpha",
        finding_type="BUG",
        root_cause_pattern="Pagination slice off-by-one boundary omitting final item",
        solution_pattern="Set upper slice index to start + page_size instead of start + (page_size - 1)",
        affected_files=["src/catalog/paginate.py"],
        outcome="SUCCESS",
        human_feedback="Clean boundary fix, 0 regressions",
    ),
]

SEEDED_MEMORIES_TENANT_B: List[MemoryRecord] = [
    MemoryRecord(
        task_id="TASK-MEM-B01",
        repo_id="repo_beta",
        finding_type="SECURITY",
        root_cause_pattern="Hardcoded JWT secret token in configuration",
        solution_pattern="Load JWT_SECRET from os.environ.get('JWT_SECRET')",
        affected_files=["src/auth/jwt.py"],
        outcome="SUCCESS",
        human_feedback="Security audit passed",
    ),
]
