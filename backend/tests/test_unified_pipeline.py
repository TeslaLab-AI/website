"""
Purpose:
Task 40 Test Suite: Unified Finding Pipeline (AC-E3-D4-01).
Verifies:
1. Architectural Invariant: Core stages (Planner, Executor, Testing, Validation, PR)
   have ZERO finding-type conditionals.
2. 6-Finding Batch Execution: 3 Bugs, 2 Dependencies, 1 Security defect all process
   through the exact same pipeline sequence to reach COMPLETE with PASS and PR generated.
3. Trace Homogeneity: 100% of findings execute the identical trace:
   ANALYSIS -> PLANNER -> EXECUTOR -> TESTING -> VALIDATION -> PR -> COMPLETE.
"""

from __future__ import annotations

import ast
import inspect
import os
import tempfile
import pytest

from agents.agent_3.day4_models import FindingCategory, UnifiedFinding, FindingContext
from agents.agent_3.unified_pipeline import (
    UnifiedFindingPipeline,
    SpecialistAnalysisAdapter,
    CommonPlanner,
    CommonExecutor,
    CommonTestingNode,
    CommonValidationNode,
    CommonPRNode,
)
from tests.fixtures.day4_fixtures import SEEDED_FINDINGS_6, setup_workspace_for_finding


class FindingTypeConditionalDetector(ast.NodeVisitor):
    """
    AST Visitor that scans for category conditionals in AST nodes.
    Detects patterns like: if node.category == ... or if category in ...
    """

    def __init__(self):
        self.forbidden_branches: list[tuple[int, str]] = []

    def visit_If(self, node: ast.If):
        # Convert test expression to string
        test_str = ast.unparse(node.test)
        if any(keyword in test_str for keyword in ["category", "FindingCategory", "BUG", "DEPENDENCY", "SECURITY"]):
            self.forbidden_branches.append((node.lineno, test_str))
        self.generic_visit(node)


def test_core_stages_zero_category_conditionals_architecture():
    """
    Architectural Invariant Test:
    Asserts that CommonPlanner, CommonExecutor, CommonTestingNode, CommonValidationNode,
    and CommonPRNode contain ZERO finding-type conditionals in their source code.
    """
    core_classes = [
        CommonPlanner,
        CommonExecutor,
        CommonTestingNode,
        CommonValidationNode,
        CommonPRNode,
    ]

    for cls in core_classes:
        src = inspect.getsource(cls)
        tree = ast.parse(src)
        detector = FindingTypeConditionalDetector()
        detector.visit(tree)

        assert not detector.forbidden_branches, (
            f"Architectural Invariant Violated in {cls.__name__}: "
            f"Found category conditional branch at lines: {detector.forbidden_branches}"
        )


def test_specialist_analysis_adapter_dispatch():
    """
    Verifies that the SpecialistAnalysisAdapter correctly delegates findings
    to the respective specialist analyzers and initializes FindingContext.
    """
    adapter = SpecialistAnalysisAdapter()

    for finding in SEEDED_FINDINGS_6:
        ctx = adapter.analyze(finding, worktree_dir=".")
        assert isinstance(ctx, FindingContext)
        assert ctx.finding.finding_id == finding.finding_id
        assert ctx.stage == "ANALYSIS"
        assert ctx.execution_trace == ["ANALYSIS"]
        assert len(ctx.diagnosis) > 10
        assert len(ctx.suggested_fix) > 5
        assert len(ctx.current_diff) > 10


def test_unified_pipeline_individual_execution():
    """
    Tests an individual bug finding end-to-end through the pipeline stages.
    """
    pipeline = UnifiedFindingPipeline()
    finding = SEEDED_FINDINGS_6[0]  # BUG-PAGINATE-01

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_finding(tmp_dir, finding)
        ctx = pipeline.process_finding(tmp_dir, finding)

        assert ctx.stage == "COMPLETE"
        assert ctx.verdict is not None
        assert ctx.verdict.verdict == "PASS"
        assert ctx.verdict.score >= 0.90
        assert ctx.pr_manifest is not None
        assert ctx.execution_trace == [
            "ANALYSIS",
            "PLANNER",
            "EXECUTOR",
            "TESTING",
            "VALIDATION",
            "PR",
            "COMPLETE",
        ]


def test_batch_run_all_6_seeded_findings_ac_e3_d4_01():
    """
    Acceptance Criteria AC-E3-D4-01:
    6-finding batch test (3 Bugs, 2 Deps, 1 Security).
    Asserts:
    1. 100% of findings (6/6) route through common Planner, Executor, Testing, Validation, and PR.
    2. All 6 findings reach PASS verdict with PR manifested.
    3. Zero stage divergence across finding categories.
    """
    pipeline = UnifiedFindingPipeline()
    assert len(SEEDED_FINDINGS_6) == 6

    # Verify category composition: exactly 3 Bugs, 2 Deps, 1 Security
    categories = [f.category for f in SEEDED_FINDINGS_6]
    assert categories.count(FindingCategory.BUG) == 3
    assert categories.count(FindingCategory.DEPENDENCY) == 2
    assert categories.count(FindingCategory.SECURITY) == 1

    # Run batch pipeline across all 6 isolated workspaces
    results = pipeline.batch_run(SEEDED_FINDINGS_6)

    assert len(results) == 6, f"Expected 6 batch results, got {len(results)}"

    expected_trace = [
        "ANALYSIS",
        "PLANNER",
        "EXECUTOR",
        "TESTING",
        "VALIDATION",
        "PR",
        "COMPLETE",
    ]

    for ctx in results:
        fid = ctx.finding.finding_id
        # 1. Assert identical execution sequence
        assert ctx.execution_trace == expected_trace, (
            f"Finding {fid} deviated from expected trace: {ctx.execution_trace}"
        )
        # 2. Assert final stage is COMPLETE
        assert ctx.stage == "COMPLETE", f"Finding {fid} finished in non-complete stage: {ctx.stage}"
        # 3. Assert validation engine passed
        assert ctx.verdict is not None, f"Finding {fid} missing validation verdict"
        assert ctx.verdict.verdict == "PASS", (
            f"Finding {fid} validation failed: {ctx.verdict.failure_reasons}"
        )
        assert ctx.verdict.score >= 0.90, f"Finding {fid} score {ctx.verdict.score} below threshold"
        # 4. Assert PR manifest generated
        assert ctx.pr_manifest is not None, f"Finding {fid} missing PR manifest"
        assert ctx.pr_manifest.branch_name.startswith("fix/")
        assert len(ctx.pr_manifest.body_markdown) > 0
        assert len(ctx.current_diff) > 0
        assert ctx.pr_manifest.title.startswith("fix(")

