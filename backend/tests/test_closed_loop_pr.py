"""
Purpose:
Tests for Task 37: Closed-Loop Bug -> PR Pipeline & PR Generator.
Verifies:
- AC-E3-D3-01: End-to-end bug finding travels through repair, validation, and produces an open PR.
- AC-E3-D3-04: PR body markdown contains root cause, changes, 5-signal test evidence, and mandatory labels.
"""

import os
import tempfile
import pytest

from agents.agent_3.day2_models import ValidationVerdict, CheckResult
from agents.agent_3.day3_models import PRManifest
from agents.agent_3.pr_generator import generate_pr_markdown, build_pr_manifest
from agents.agent_3.github_pr_client import GitHubPRClient, ClosedLoopPipeline
from agents.agent_3.repair_agent import RepairAgent
from tests.fixtures.day2_fixtures import setup_repair_benchmark_repo
from tests.fixtures.day3_fixtures import setup_git_repo_for_pr


def test_ac_e3_d3_04_pr_description_and_label_accuracy():
    """
    Verifies AC-E3-D3-04:
    GitHub PR body audit: includes AI authorship notice, root cause,
    target files, 5-signal test table, and mandatory labels ('ai-generated', 'bug-fix', 'stage-0').
    """
    mock_verdict = ValidationVerdict(
        verdict="PASS",
        score=1.0,
        checks={
            "requirements": CheckResult(name="requirements", passed=True, score=1.0, message="Scope matches"),
            "diff_quality": CheckResult(name="diff_quality", passed=True, score=1.0, message="Clean 2 lines diff"),
            "repro_test": CheckResult(name="repro_test", passed=True, score=1.0, message="Repro passed"),
            "regression_tests": CheckResult(name="regression_tests", passed=True, score=1.0, message="0 regressions"),
            "security_scan": CheckResult(name="security_scan", passed=True, score=1.0, message="SAST clean"),
        },
        failure_reasons=[],
    )

    manifest = build_pr_manifest(
        title="fix(catalog): resolve off-by-one pagination slice",
        root_cause="Slice end boundary was set to start + (page_size - 1), omitting the final item.",
        target_files=["src/catalog/paginate.py"],
        verdict=mock_verdict,
        branch_name="task/bugfix-pagination-slice",
        linked_issue_id="#101",
    )

    # Label audit
    assert "ai-generated" in manifest.labels
    assert "bug-fix" in manifest.labels
    assert "stage-0" in manifest.labels

    # Markdown body audit
    body = manifest.body_markdown
    assert "AI Authorship Notice" in body
    assert "TeslaLab AI — Stage 0 Autonomous Repair Agent" in body
    assert "Resolves #101" in body
    assert "Root Cause Analysis" in body
    assert "5-Signal Verification Results" in body
    assert "`requirements`" in body
    assert "`diff_quality`" in body
    assert "`repro_test`" in body
    assert "`regression_tests`" in body
    assert "`security_scan`" in body
    assert "✅ PASS" in body
    assert "Safety & Quality Checklist" in body


def test_ac_e3_d3_01_closed_loop_bug_to_pr_milestone():
    """
    Verifies AC-E3-D3-01:
    Executes full closed chain:
    Seeded Bug -> Ingestion -> Diagnosis -> Plan -> Autonomous Repair -> 5-Signal Validation PASS -> Branch Creation -> Remote Push -> Open PR.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Step A: Setup real local git repository with remote
        repo_info = setup_git_repo_for_pr(tmp_dir)
        worktree = repo_info["worktree"]

        # Step B: Inject benchmark bug files into worktree
        src_dir = os.path.join(worktree, "src", "catalog")
        test_dir = os.path.join(worktree, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(test_dir, exist_ok=True)

        paginate_file = os.path.join(src_dir, "paginate.py")
        with open(paginate_file, "w", encoding="utf-8") as f:
            f.write("""def paginate_items(items: list, page: int, page_size: int) -> list:
    start = (page - 1) * page_size
    end = start + (page_size - 1)
    return items[start:end]
""")

        repro_file = os.path.join(test_dir, "test_repro.py")
        with open(repro_file, "w", encoding="utf-8") as f:
            f.write("""from src.catalog.paginate import paginate_items

def test_repro():
    data = list(range(10))
    res = paginate_items(data, 1, 5)
    assert len(res) == 5
""")

        broken_diff = """--- a/src/catalog/paginate.py
+++ b/src/catalog/paginate.py
@@ -3,3 +3,3 @@
     start = (page - 1) * page_size
-    end = start + page_size
+    end = start + (page_size - 1)
     return items[start:end]
"""

        def repair_cb(plan, d):
            return RepairAgent.apply_repair_to_file(
                paginate_file,
                "end = start + (page_size - 1)",
                "end = start + page_size",
            )

        # Step C: Execute Closed-Loop Pipeline
        manifest, state, verdict = ClosedLoopPipeline.execute_bug_to_pr(
            session_id="session-closed-loop-01",
            worktree_dir=worktree,
            initial_diff=broken_diff,
            task_desc="Fix pagination slice boundary",
            target_files=["src/catalog/paginate.py"],
            repro_test_path=repro_file,
            apply_repair_callback=repair_cb,
            linked_issue_id="#42",
            remote_name="origin",
        )

        # Assertions on pipeline outcome
        assert state.current_step == "PR_READY"
        assert verdict.verdict == "PASS"
        assert manifest.status == "OPEN"
        assert manifest.pr_url is not None
        assert "https://github.com/TeslaLab-AI/website/pull/" in manifest.pr_url
        assert "ai-generated" in manifest.labels
        assert manifest.linked_issue_id == "#42"
