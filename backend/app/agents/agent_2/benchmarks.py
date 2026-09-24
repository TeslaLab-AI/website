"""
Seeded RootCauseAnalysis Benchmark Cases for Engineer 2 (Agent 2).

Provides the canonical 5 seeded bug diagnoses from Engineer 1:
1. finding-101: SQL Injection in user search query (app/db/users.py)
2. finding-102: NoneType has no attribute 'strip' (app/services/profile.py)
3. finding-103: Hardcoded API token (app/payments/stripe.py)
4. finding-104: Missing CSRF token validation (server.js)
5. finding-105: Known vulnerability in pinned cryptography dependency (requirements.txt)
"""

from __future__ import annotations
from pydantic import BaseModel, Field

from app.agents.agent_2.planner import RootCauseAnalysis, ContextPack
from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ReadFileArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    OpenPrArgs,
)


class BenchmarkCase(BaseModel):
    """Container for a seeded benchmark case."""
    case_id: str = Field(..., description="Unique case identifier (e.g. finding-101)")
    name: str = Field(..., description="Human-readable benchmark name")
    rca: RootCauseAnalysis = Field(..., description="RootCauseAnalysis diagnosis payload")
    context: ContextPack = Field(..., description="ContextPack repository and environment context")
    expected_affected_file: str = Field(..., description="File affected by the diagnosis")
    expected_complexity: str = Field(..., description="Expected severity/complexity")


# ── Benchmark 1: SQL Injection ──────────────────────────────
BENCHMARK_CASE_1 = BenchmarkCase(
    case_id="finding-101",
    name="SQL Injection in user search query",
    rca=RootCauseAnalysis(
        finding_id="finding-101",
        title="SQL Injection in user search query",
        description="String interpolation allows SQL injection in search_users function.",
        file_path="app/db/users.py",
        line_number=42,
        root_cause="Query string formatted with f-string instead of parameterized query.",
        suggested_fix="Use parameterized cursor.execute with tuple parameters.",
        severity="High",
        cwe="CWE-89",
    ),
    context=ContextPack(
        repo_name="demo-repo",
        file_content=(
            "import os\n"
            "def search_users(cursor, query):\n"
            "    sql = f'SELECT * FROM users WHERE name = \"{query}\"'\n"
            "    cursor.execute(sql)\n"
            "    return cursor.fetchall()\n"
        ),
        test_command="pytest tests/test_users.py",
    ),
    expected_affected_file="app/db/users.py",
    expected_complexity="High",
)

# ── Benchmark 2: Null Pointer / NoneType ────────────────────
BENCHMARK_CASE_2 = BenchmarkCase(
    case_id="finding-102",
    name="NoneType has no attribute 'strip'",
    rca=RootCauseAnalysis(
        finding_id="finding-102",
        title="NoneType has no attribute 'strip'",
        description="User bio can be None when profile is updated without bio.",
        file_path="app/services/profile.py",
        line_number=18,
        root_cause="profile.bio accessed directly without null check.",
        suggested_fix="Check if bio is not None before stripping.",
        severity="Medium",
    ),
    context=ContextPack(
        repo_name="demo-repo",
        file_content=(
            "def clean_bio(bio: str | None) -> str:\n"
            "    return bio.strip()\n"
        ),
        test_command="pytest tests/test_profile.py",
    ),
    expected_affected_file="app/services/profile.py",
    expected_complexity="Medium",
)

# ── Benchmark 3: Hardcoded Credentials ──────────────────────
BENCHMARK_CASE_3 = BenchmarkCase(
    case_id="finding-103",
    name="Hardcoded API token",
    rca=RootCauseAnalysis(
        finding_id="finding-103",
        title="Hardcoded API token",
        description="Hardcoded Stripe test key found in payment processor.",
        file_path="app/payments/stripe.py",
        line_number=8,
        root_cause="API key committed directly into source code.",
        suggested_fix="Read key from os.environ['STRIPE_API_KEY'].",
        severity="Critical",
    ),
    context=ContextPack(
        repo_name="demo-repo",
        file_content="STRIPE_KEY = 'sk_test_12345'\n",
        test_command="pytest tests/test_payments.py",
    ),
    expected_affected_file="app/payments/stripe.py",
    expected_complexity="Critical",
)

# ── Benchmark 4: Missing CSRF Protection ────────────────────
BENCHMARK_CASE_4 = BenchmarkCase(
    case_id="finding-104",
    name="Missing CSRF token validation",
    rca=RootCauseAnalysis(
        finding_id="finding-104",
        title="Missing CSRF token validation",
        description="State-changing POST handler does not validate CSRF token.",
        file_path="server.js",
        line_number=22,
        root_cause="Express route lacks csrfProtection middleware.",
        suggested_fix="Attach csrfProtection to route handler.",
        severity="Medium",
        cwe="CWE-352",
    ),
    context=ContextPack(
        repo_name="demo-repo",
        file_content="app.post('/transfer', handleTransfer);\n",
        test_command="npm test",
    ),
    expected_affected_file="server.js",
    expected_complexity="Medium",
)

# ── Benchmark 5: Vulnerable Dependency ──────────────────────
BENCHMARK_CASE_5 = BenchmarkCase(
    case_id="finding-105",
    name="Known vulnerability in pinned cryptography dependency",
    rca=RootCauseAnalysis(
        finding_id="finding-105",
        title="Known vulnerability in pinned cryptography dependency",
        description="Cryptography 41.0.0 has known CVE-2023-49083.",
        file_path="requirements.txt",
        line_number=5,
        root_cause="Outdated dependency pinned in requirements manifest.",
        suggested_fix="Bump cryptography to 42.0.8.",
        severity="High",
        cwe="CWE-1395",
    ),
    context=ContextPack(
        repo_name="demo-repo",
        file_content="cryptography==41.0.0\nfastapi==0.115.0\n",
        test_command="pytest",
    ),
    expected_affected_file="requirements.txt",
    expected_complexity="High",
)

SEEDED_BENCHMARK_CASES: list[BenchmarkCase] = [
    BENCHMARK_CASE_1,
    BENCHMARK_CASE_2,
    BENCHMARK_CASE_3,
    BENCHMARK_CASE_4,
    BENCHMARK_CASE_5,
]


def get_seeded_benchmarks() -> list[BenchmarkCase]:
    """Return a shallow copy of the 5 seeded benchmark cases."""
    return list(SEEDED_BENCHMARK_CASES)


def get_benchmark_by_id(case_id: str) -> BenchmarkCase:
    """Retrieve benchmark case by finding ID or case ID."""
    clean_id = case_id.strip().lower()
    for case in SEEDED_BENCHMARK_CASES:
        if case.case_id.lower() == clean_id or case.rca.finding_id.lower() == clean_id:
            return case
    raise KeyError(f"Unknown benchmark case ID: {case_id}")
