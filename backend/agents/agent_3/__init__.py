"""
TeslaLab AI — Agent 3: Verification & Intelligence Lead
Implementation location: backend/agents/agent_3/

Responsibilities (Tasks 31–33):
- Task 31: Independent Testing Agent (Zero-Trust verification & regression detection)
- Task 32: Test Impact Analysis (AST dependency graph & <25% speedup)
- Task 33: Security Agent (SAST, secret detection, CWE-89 SQLi, Diff Security Gate)
"""

from .verification_models import (
    VerificationReport,
    TestImpactManifest,
    VulnFinding,
    SecurityReport,
)
from .independent_tester import (
    run_independent_verification,
    discover_tests_for_files,
)
from .test_impact import (
    select_impacted_tests,
    build_import_graph,
)
from .security_agent import (
    scan_codebase_security,
    diff_security_gate,
    scan_file_security,
)

from .day2_models import (
    CheckResult,
    ValidationVerdict,
    RepairPlan,
    LoopState,
    LoopIterationEvent,
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
    "CheckResult",
    "ValidationVerdict",
    "RepairPlan",
    "LoopState",
    "LoopIterationEvent",
]
