"""
TeslaLab AI — Agent 3: Verification & Intelligence Lead
Responsibilities (Tasks 31–33):
- Task 31: Independent Testing Agent (Zero-Trust execution & regression catch)
- Task 32: Test Impact Analysis (AST dependency graph & <25% speedup)
- Task 33: Security Agent (SAST, secret detection, CWE-89, Diff Security Gate)
"""

from app.agents.verification_models import (
    VerificationReport,
    TestImpactManifest,
    VulnFinding,
    SecurityReport,
)
from app.agents.independent_tester import (
    run_independent_verification,
    discover_tests_for_files,
)
from app.agents.test_impact import (
    select_impacted_tests,
    build_import_graph,
)
from app.agents.security_agent import (
    scan_codebase_security,
    diff_security_gate,
    scan_file_security,
)

__all__ = [
    "VerificationReport",
    "TestImpactManifest",
    "VulnFinding",
    "SecurityReport",
    "run_independent_verification",
    "discover_tests_for_files",
    "select_impacted_tests",
    "build_import_graph",
    "scan_codebase_security",
    "diff_security_gate",
    "scan_file_security",
]
