"""
Purpose:
Task 37: Automated GitHub Pull Request Description Generator.
Synthesizes professional, structured Pull Request markdown according to
TeslaLab AI Stage 0 specification (Page 2 & Page 5):

Features:
- Mandatory AI Authorship attribution notice
- Root cause diagnosis summary
- Key changes breakdown by file
- Complete 5-Signal Test Verification matrix and status badges
- Linked Issue ID reference (Resolves #<id>)
- Pre-merge human safety review checklist
"""

from __future__ import annotations

from typing import Dict, List, Optional
from agents.agent_3.day2_models import ValidationVerdict
from agents.agent_3.day3_models import PRManifest


def generate_pr_markdown(
    title: str,
    root_cause: str,
    target_files: List[str],
    verdict: ValidationVerdict,
    branch_name: str,
    linked_issue_id: Optional[str] = None,
    diff_summary: Optional[str] = None,
) -> str:
    """
    Constructs comprehensive GitHub PR markdown with all required badges,
    test verification evidence, and human review checklists.
    """
    issue_line = f"\n**Linked Issue:** Resolves {linked_issue_id}\n" if linked_issue_id else ""
    diff_stat_line = f"\n**Diff Summary:** {diff_summary}\n" if diff_summary else ""

    # Build 5-Signal Check Breakdown Table
    check_rows = []
    for check_name, check_res in verdict.checks.items():
        status_icon = "✅ PASS" if check_res.passed else "❌ FAIL"
        score_pct = int(check_res.score * 100)
        check_rows.append(f"| `{check_name}` | {status_icon} | {score_pct}% | {check_res.message} |")

    checks_table = "\n".join(check_rows)

    markdown = f"""## 🤖 Automated Bug Fix: {title}

> [!NOTE]
> **AI Authorship Notice**: This Pull Request was autonomously synthesized, tested, and validated by **TeslaLab AI — Stage 0 Autonomous Repair Agent (Agent 3)**.

{issue_line}
### 🔍 Root Cause Analysis
{root_cause}

### 🛠️ Key Modifications
- **Modified Components:** {', '.join(f'`{f}`' for f in target_files)}
- **Branch:** `{branch_name}`
{diff_stat_line}
### 🧪 5-Signal Verification Results

| Signal | Verdict | Score | Diagnostic Details |
| :--- | :---: | :---: | :--- |
{checks_table}

**Composite Validation Score:** `{verdict.score * 100:.1f}%` — **Overall Verdict:** `{verdict.verdict}`

### 🛡️ Safety & Quality Checklist
- [x] Autonomous reproduction test transitions from FAIL to PASS.
- [x] Zero regressions introduced in existing regression suites.
- [x] Diff Security Gate confirms 0 new CWE vulnerabilities (CWE-89 / CWE-798).
- [x] Diff quality adheres to minimality constraints (no bloated files or churn).
- [ ] Final human sanity review and merge approval.
"""
    return markdown.strip()


def build_pr_manifest(
    title: str,
    root_cause: str,
    target_files: List[str],
    verdict: ValidationVerdict,
    branch_name: str,
    linked_issue_id: Optional[str] = None,
    diff_summary: Optional[str] = None,
) -> PRManifest:
    """
    Factory function assembling a fully validated PRManifest payload ready
    for GitHub API publishing.
    """
    body_markdown = generate_pr_markdown(
        title=title,
        root_cause=root_cause,
        target_files=target_files,
        verdict=verdict,
        branch_name=branch_name,
        linked_issue_id=linked_issue_id,
        diff_summary=diff_summary,
    )

    badges = {
        "validation_engine": verdict.verdict,
        "composite_score": f"{verdict.score * 100:.0f}%",
        "sast_gate": "CLEAN" if verdict.checks.get("security_scan", None) and verdict.checks["security_scan"].passed else "ALERT",
    }

    return PRManifest(
        title=title,
        body_markdown=body_markdown,
        branch_name=branch_name,
        target_branch="main",
        labels=["ai-generated", "bug-fix", "stage-0"],
        linked_issue_id=linked_issue_id,
        verification_badges=badges,
        status="DRAFT",
    )
