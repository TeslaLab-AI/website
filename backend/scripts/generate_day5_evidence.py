"""
Purpose:
Automates generation of all required Day 5 Capstone submission evidence for Engineer 3.

Produces (per Page 6 of Stage 0 Specification):
1. evidence/evaluation_report.json & evidence/evaluation_report.csv
   (Task 43 / AC-E3-D5-01: Real measurement dashboard of 10 core dimensions)
2. evidence/day5_autonomous_trigger_trace.log
   (Task 44 / AC-E3-D5-02: Webhook intake, auto-investigation, safety pause at ROOT_CAUSE, approval, PR)
3. evidence/day5_stage0_benchmark_report.json
   (Task 45 / AC-E3-D5-03: 10-finding benchmark audited against all 7 Stage 0 quantitative thresholds)
4. evidence/day5_demo_execution_manifest.json
   (Task 45 / AC-E3-D5-04: Rehearsal logs of 4 live demo scenarios)
5. evidence/day5_sprint_acceptance_signoff.md
   (Task 45 / AC-E3-D5-04: Multi-engineer sign-off document for Stage 0 completion)
"""

import json
import os
import sys
import tempfile
import time

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.agent_3.day5_models import (
    AutonomousTriggerPayload,
    TriggerSessionState,
)
from agents.agent_3.evaluation_engine import EvaluationEngine
from agents.agent_3.autonomous_trigger import AutonomousTriggerEngine
from agents.agent_3.stage0_capstone_demo import Stage0CapstoneOrchestrator
from tests.fixtures.day5_fixtures import SEEDED_FINDINGS_10, setup_workspace_for_day5_finding


def main():
    evidence_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "evidence"))
    os.makedirs(evidence_dir, exist_ok=True)
    print(f"[START] Generating Day 5 Stage 0 Capstone Evidence into: {evidence_dir}\n")

    orchestrator = Stage0CapstoneOrchestrator(benchmark_repo="repo_stage0_benchmark")

    # ─────────────────────────────────────────────────────────────
    # Evidence 1 & 3: 10-Finding Benchmark Execution & Threshold Audit
    # ─────────────────────────────────────────────────────────────
    print("1. Running 10-finding benchmark pipeline and 7 quantitative thresholds audit...")
    contexts, metrics, audit = orchestrator.run_benchmark_10_findings()

    # Export Evaluation Reports (JSON + CSV)
    json_path = os.path.join(evidence_dir, "evaluation_report.json")
    csv_path = os.path.join(evidence_dir, "evaluation_report.csv")
    orchestrator.eval_engine.export_json(json_path)
    orchestrator.eval_engine.export_csv(csv_path)
    print(f"   [SUCCESS] Exported: {json_path}")
    print(f"   [SUCCESS] Exported: {csv_path}")

    # Export Stage 0 Benchmark Audit Report
    benchmark_report_path = os.path.join(evidence_dir, "day5_stage0_benchmark_report.json")
    benchmark_payload = {
        "benchmark_repository": "repo_stage0_benchmark",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_findings_evaluated": len(contexts),
        "all_thresholds_met": audit.all_thresholds_met,
        "threshold_evaluations": audit.thresholds_met,
        "threshold_metrics": audit.model_dump(),
        "findings_breakdown": [
            {
                "finding_id": ctx.finding.finding_id,
                "category": ctx.finding.category.value,
                "title": ctx.finding.title,
                "stage": ctx.stage,
                "verdict": ctx.verdict.verdict if ctx.verdict else "UNKNOWN",
                "score": ctx.verdict.score if ctx.verdict else 0.0,
                "execution_trace": ctx.execution_trace,
                "pr_branch": ctx.pr_manifest.branch_name if ctx.pr_manifest else None,
            }
            for ctx in contexts
        ],
        "metrics_summary": metrics.model_dump(),
    }
    with open(benchmark_report_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_payload, f, indent=2)
    print(f"   [SUCCESS] Exported: {benchmark_report_path}")

    # Print ASCII Dashboard
    print("\n" + orchestrator.eval_engine.render_ascii_dashboard())

    # ─────────────────────────────────────────────────────────────
    # Evidence 2: Autonomous Trigger Session & Safety Gate Trace Log
    # ─────────────────────────────────────────────────────────────
    print("\n2. Simulating Autonomous Trigger Webhook & Human Safety Gate...")
    with tempfile.TemporaryDirectory() as trigger_worktree:
        # Seed workspace with BUG-PAGINATE-01
        bug_finding = SEEDED_FINDINGS_10[0]
        setup_workspace_for_day5_finding(trigger_worktree, bug_finding)

        trigger_engine = AutonomousTriggerEngine()
        payload = AutonomousTriggerPayload(
            webhook_id="WH-ALERT-DAY5-CAPSTONE",
            source="github_dependabot_and_sast",
            finding=bug_finding,
        )

        session = trigger_engine.ingest_webhook(
            payload,
            worktree_dir=trigger_worktree,
            auto_start_investigation=True,
        )
        assert session.state == TriggerSessionState.HUMAN_REVIEW
        assert session.paused_at_root_cause is True

        # Operator review and approval
        resumed_ctx = trigger_engine.approve_session(
            session_id=session.session_id,
            approved_by="lead-engineer-3@teslalab.ai",
            notes="Root cause verified. Approved for automated branch, fix, validation, and PR creation.",
        )
        updated_session = trigger_engine.get_session(session.session_id)
        assert updated_session.state == TriggerSessionState.COMPLETED

        trigger_log_path = os.path.join(evidence_dir, "day5_autonomous_trigger_trace.log")
        trigger_engine.export_trace_log(trigger_log_path)
        print(f"   [SUCCESS] Exported: {trigger_log_path}")

    # ─────────────────────────────────────────────────────────────
    # Evidence 4: 4 Live Demo Scenarios Execution Manifest
    # ─────────────────────────────────────────────────────────────
    print("\n3. Rehearsing 4 Live Demonstration Scenarios...")
    demo_scenarios = orchestrator.run_live_demo_scenarios()
    demo_manifest_path = os.path.join(evidence_dir, "day5_demo_execution_manifest.json")
    with open(demo_manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_scenarios": len(demo_scenarios),
            "all_passed": all(s.status == "SUCCESS" for s in demo_scenarios),
            "scenarios": [s.model_dump() for s in demo_scenarios],
        }, f, indent=2)
    print(f"   [SUCCESS] Exported: {demo_manifest_path}")

    # ─────────────────────────────────────────────────────────────
    # Evidence 5: Multi-Engineer Stage 0 Sprint Acceptance Sign-Off
    # ─────────────────────────────────────────────────────────────
    print("\n4. Generating Multi-Engineer Sprint Acceptance Sign-Off Document...")
    signoff_md_path = os.path.join(evidence_dir, "day5_sprint_acceptance_signoff.md")
    signoff_content = orchestrator.generate_signoff_document(audit, demo_scenarios)
    with open(signoff_md_path, "w", encoding="utf-8") as f:
        f.write(signoff_content)
    print(f"   [SUCCESS] Exported: {signoff_md_path}")

    print("\n[COMPLETE] All 5 Day 5 Capstone Evidence artifacts generated successfully!")


if __name__ == "__main__":
    main()
