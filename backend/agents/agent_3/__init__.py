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

from .day3_models import (
    PRManifest,
    DependencyFinding,
    DependencyPlan,
    SecurityRemediationReport,
)

from .day4_models import (
    FindingCategory,
    UnifiedFinding,
    FindingContext,
    ManualAction,
    ManualControlCommand,
    MemoryRecord,
    ContextPack,
)

from .validation_engine import ValidationEngine
from .repair_agent import RepairAgent, FailureDiagnosticParser
from .autonomous_loop import AutonomousRepairLoop, compute_diff_hash
from .pr_generator import generate_pr_markdown, build_pr_manifest
from .github_pr_client import GitHubPRClient, ClosedLoopPipeline
from .dependency_agent import DependencyAgent, DependencyInspector, BreakingChangeAnalyzer
from .unified_pipeline import (
    UnifiedFindingPipeline,
    SpecialistAnalysisAdapter,
    CommonPlanner,
    CommonExecutor,
    CommonTestingNode,
    CommonValidationNode,
    CommonPRNode,
)

from .manual_controls import ManualControlSession
from .solution_memory import (
    SolutionMemoryStore,
    SolutionIndexer,
    MemoryRetriever,
    ContextBuilder,
    compute_text_embedding,
    cosine_similarity,
)

from .day5_models import (
    EvaluationMetrics,
    AutonomousTriggerPayload,
    TriggerSessionState,
    TriggerSession,
    BenchmarkThresholdAudit,
    DemoScenario,
)

from .evaluation_engine import (
    EvaluationEngine,
    SessionTelemetryRecord,
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
    "PRManifest",
    "DependencyFinding",
    "DependencyPlan",
    "SecurityRemediationReport",
    "FindingCategory",
    "UnifiedFinding",
    "FindingContext",
    "ManualAction",
    "ManualControlCommand",
    "MemoryRecord",
    "ContextPack",
    "ValidationEngine",
    "RepairAgent",
    "FailureDiagnosticParser",
    "AutonomousRepairLoop",
    "compute_diff_hash",
    "generate_pr_markdown",
    "build_pr_manifest",
    "GitHubPRClient",
    "ClosedLoopPipeline",
    "DependencyAgent",
    "DependencyInspector",
    "BreakingChangeAnalyzer",
    "SecurityRemediator",
    "UnifiedFindingPipeline",
    "SpecialistAnalysisAdapter",
    "CommonPlanner",
    "CommonExecutor",
    "CommonTestingNode",
    "CommonValidationNode",
    "CommonPRNode",
    "ManualControlSession",
    "SolutionMemoryStore",
    "SolutionIndexer",
    "MemoryRetriever",
    "ContextBuilder",
    "compute_text_embedding",
    "cosine_similarity",
    "EvaluationMetrics",
    "AutonomousTriggerPayload",
    "TriggerSessionState",
    "TriggerSession",
    "BenchmarkThresholdAudit",
    "DemoScenario",
    "EvaluationEngine",
    "SessionTelemetryRecord",
]











