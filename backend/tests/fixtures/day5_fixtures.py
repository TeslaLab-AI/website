"""
Purpose:
Day 5 Test Fixtures for Engineer 3 (Tasks 43–45).

Includes:
1. 10 Seeded Benchmark Findings (5 Bugs, 3 Dependencies, 2 Security):
   - Bug 1: BUG-PAGINATE-01 (Pagination slice boundary off-by-one)
   - Bug 2: BUG-ZERO-FEE-02 (Fee calculator zero/negative guardrail)
   - Bug 3: BUG-BOOL-FLAG-03 (Inverted boolean validator)
   - Bug 4: BUG-SLUG-HYPHEN-04 (String sanitizer whitespace hyphenation)
   - Bug 5: BUG-CHECKOUT-TOTAL-05 (Cart total calculation defect)
   - Dep 1: DEP-REQ-01 (Requests security bump CVE-2023-32681)
   - Dep 2: DEP-PYD-02 (Pydantic V2 breaking upgrade)
   - Dep 3: DEP-LODASH-03 (Lodash prototype pollution CVE-2020-8203)
   - Security 1: SEC-SQLI-01 (CWE-89 SQL Injection parameterized query)
   - Security 2: SEC-HARDCODED-JWT-02 (CWE-798 Hardcoded secret token in config)
2. Isolated workspace setup functions for all 10 benchmark findings.
3. Benchmark ground-truth telemetry fixture for Task 43 metric audit.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Any

from agents.agent_3.day4_models import (
    FindingCategory,
    UnifiedFinding,
)
from tests.fixtures.day2_fixtures import (
    setup_repair_benchmark_repo,
    setup_bug2_zero_fee_repo,
    setup_bug4_inverted_boolean_repo,
    setup_bug5_string_sanitizer_repo,
)
from tests.fixtures.day3_fixtures import (
    setup_dependency_repo_pyproject,
    setup_dependency_repo_breaking_api,
    setup_security_remediation_repo,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. The 10 Seeded Canonical Benchmark Findings
# ─────────────────────────────────────────────────────────────────────────────

SEEDED_FINDINGS_10: List[UnifiedFinding] = [
    # Finding 1 (Bug 1): Pagination Slice Boundary
    UnifiedFinding(
        finding_id="BUG-PAGINATE-01",
        category=FindingCategory.BUG,
        title="Off-by-one boundary calculation in catalog pagination slice",
        description="paginate_items slice end boundary omits the 5th item when page_size=5.",
        severity="HIGH",
        target_files=["src/catalog/paginate.py"],
        repo_id="repo_stage0_benchmark",
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
        repo_id="repo_stage0_benchmark",
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
        repo_id="repo_stage0_benchmark",
        metadata={"defect_type": "BOOLEAN_FLAG"},
    ),
    # Finding 4 (Bug 4): String Sanitizer Hyphenation
    UnifiedFinding(
        finding_id="BUG-SLUG-HYPHEN-04",
        category=FindingCategory.BUG,
        title="Slug sanitizer fails to replace spaces with hyphens",
        description="sanitize_slug lowercases text but leaves whitespace intact instead of hyphenating.",
        severity="LOW",
        target_files=["src/utils/sanitizer.py"],
        repo_id="repo_stage0_benchmark",
        metadata={"defect_type": "SANITIZATION"},
    ),
    # Finding 5 (Bug 5): Checkout Total Regression
    UnifiedFinding(
        finding_id="BUG-CHECKOUT-TOTAL-05",
        category=FindingCategory.BUG,
        title="Checkout cart calculation returns 0.0 total",
        description="process_cart returns 0.0 due to erroneous stub, breaking checkout flow.",
        severity="HIGH",
        target_files=["src/payment/checkout.py"],
        repo_id="repo_stage0_benchmark",
        metadata={"defect_type": "REGRESSION"},
    ),
    # Finding 6 (Dep 1): Requests Security Bump
    UnifiedFinding(
        finding_id="DEP-REQ-01",
        category=FindingCategory.DEPENDENCY,
        title="CVE-2023-32681: Outdated requests 2.25.1 vulnerability",
        description="Requests leaks Proxy-Authorization header during cross-origin redirect.",
        severity="HIGH",
        target_files=["pyproject.toml"],
        repo_id="repo_stage0_benchmark",
        metadata={"package": "requests", "current": "2.25.1", "target": "2.31.0", "cve": "CVE-2023-32681"},
    ),
    # Finding 7 (Dep 2): Pydantic V2 Breaking Upgrade
    UnifiedFinding(
        finding_id="DEP-PYD-02",
        category=FindingCategory.DEPENDENCY,
        title="Pydantic V1 -> V2 breaking API upgrade",
        description="Pydantic 1.8.2 upgraded to 2.4.2; requires migrating parse_obj to model_validate.",
        severity="MEDIUM",
        target_files=["requirements.txt", "src/models/user.py"],
        repo_id="repo_stage0_benchmark",
        metadata={"package": "pydantic", "current": "1.8.2", "target": "2.4.2", "breaking": True},
    ),
    # Finding 8 (Dep 3): Lodash Security Upgrade
    UnifiedFinding(
        finding_id="DEP-LODASH-03",
        category=FindingCategory.DEPENDENCY,
        title="CVE-2020-8203: Prototype pollution in lodash < 4.17.21",
        description="Lodash vulnerable to prototype pollution via zipObjectDeep function.",
        severity="HIGH",
        target_files=["package.json"],
        repo_id="repo_stage0_benchmark",
        metadata={"package": "lodash", "current": "4.17.19", "target": "4.17.21", "cve": "CVE-2020-8203"},
    ),
    # Finding 9 (Security 1): CWE-89 SQL Injection
    UnifiedFinding(
        finding_id="SEC-SQLI-01",
        category=FindingCategory.SECURITY,
        title="CWE-89: SQL Injection in user tier query",
        description="cursor.execute uses dynamic string interpolation rather than parameterized placeholders.",
        severity="CRITICAL",
        target_files=["src/db/user_repo.py"],
        repo_id="repo_stage0_benchmark",
        metadata={"cwe": "CWE-89", "rule": "avoid-dynamic-sql-injection"},
    ),
    # Finding 10 (Security 2): CWE-798 Hardcoded Secret
    UnifiedFinding(
        finding_id="SEC-HARDCODED-JWT-02",
        category=FindingCategory.SECURITY,
        title="CWE-798: Hardcoded secret key in JWT authenticator",
        description="Hardcoded JWT secret token in source code violates zero-secret security policy.",
        severity="CRITICAL",
        target_files=["src/auth/jwt.py"],
        repo_id="repo_stage0_benchmark",
        metadata={"cwe": "CWE-798", "rule": "avoid-hardcoded-secret"},
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Workspace Setup Functions for New Day 5 Findings
# ─────────────────────────────────────────────────────────────────────────────

def setup_bug_checkout_total_repo(tmp_dir: str) -> Dict[str, str]:
    """Sets up workspace for BUG-CHECKOUT-TOTAL-05."""
    src_dir = os.path.join(tmp_dir, "src", "payment")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    checkout_file = os.path.join(src_dir, "checkout.py")
    with open(checkout_file, "w", encoding="utf-8") as f:
        f.write("""def calculate_fee(amount: float) -> float:
    return amount * 0.02

def process_cart(total: float) -> float:
    # BUG: Erroneous zero cart return
    return 0.0
""")

    test_file = os.path.join(test_dir, "test_checkout.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("""from src.payment.checkout import process_cart

def test_process_cart():
    assert process_cart(100.0) == 102.0, "Expected cart total with fee"
""")

    return {"source": checkout_file, "test": test_file}


def setup_dep_lodash_repo(tmp_dir: str) -> Dict[str, str]:
    """Sets up workspace for DEP-LODASH-03."""
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(test_dir, exist_ok=True)

    pkg_json_file = os.path.join(tmp_dir, "package.json")
    with open(pkg_json_file, "w", encoding="utf-8") as f:
        f.write("""{
  "name": "teslalab-auth",
  "version": "1.0.0",
  "dependencies": {
    "lodash": "4.17.19"
  }
}
""")

    test_file = os.path.join(test_dir, "test_lodash.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("""import json
import os

def test_lodash_version():
    with open("package.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["dependencies"]["lodash"] == "4.17.21"
""")

    return {"manifest": pkg_json_file, "test": test_file}


def setup_sec_hardcoded_jwt_repo(tmp_dir: str) -> Dict[str, str]:
    """Sets up workspace for SEC-HARDCODED-JWT-02."""
    src_dir = os.path.join(tmp_dir, "src", "auth")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    jwt_file = os.path.join(src_dir, "jwt.py")
    with open(jwt_file, "w", encoding="utf-8") as f:
        f.write("""import os

# VULNERABILITY: CWE-798 Hardcoded secret token
JWT_SECRET = "sk_live_9948271038472910482910"

def get_jwt_secret() -> str:
    return JWT_SECRET
""")

    test_file = os.path.join(test_dir, "test_jwt.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("""import os
from src.auth.jwt import get_jwt_secret

def test_jwt_secret_loaded():
    os.environ["JWT_SECRET"] = "production_secure_token_123"
    assert get_jwt_secret() == "production_secure_token_123"
""")

    return {"source": jwt_file, "test": test_file}


def setup_workspace_for_day5_finding(worktree_dir: str, finding: UnifiedFinding) -> Dict[str, str]:
    """
    Sets up an isolated, defect-populated workspace for any of the 10 benchmark findings.
    """
    fid = finding.finding_id
    if fid == "BUG-PAGINATE-01":
        return setup_repair_benchmark_repo(worktree_dir)
    elif fid == "BUG-ZERO-FEE-02":
        return setup_bug2_zero_fee_repo(worktree_dir)
    elif fid == "BUG-BOOL-FLAG-03":
        return setup_bug4_inverted_boolean_repo(worktree_dir)
    elif fid == "BUG-SLUG-HYPHEN-04":
        return setup_bug5_string_sanitizer_repo(worktree_dir)
    elif fid == "BUG-CHECKOUT-TOTAL-05":
        return setup_bug_checkout_total_repo(worktree_dir)
    elif fid == "DEP-REQ-01":
        return setup_dependency_repo_pyproject(worktree_dir)
    elif fid == "DEP-PYD-02":
        return setup_dependency_repo_breaking_api(worktree_dir)
    elif fid == "DEP-LODASH-03":
        return setup_dep_lodash_repo(worktree_dir)
    elif fid == "SEC-SQLI-01":
        return setup_security_remediation_repo(worktree_dir)
    elif fid == "SEC-HARDCODED-JWT-02":
        return setup_sec_hardcoded_jwt_repo(worktree_dir)
    else:
        raise ValueError(f"Unknown benchmark finding ID: {fid}")
