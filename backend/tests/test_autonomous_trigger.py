"""
Purpose:
Task 44 Test Suite: Autonomous Trigger v1 & Safety Gate (AC-E3-D5-02).
Verifies:
1. Webhook Ingestion: Automated scanner alerts ingest seamlessly into TriggerSessions.
2. Auto-Investigation Speed: Investigation completes to root cause in < 60 seconds.
3. MANDATORY SAFETY PAUSE (AC-E3-D5-02):
   Session strictly halts at ROOT_CAUSE and enters HUMAN_REVIEW.
   Zero code changes on disk are permitted before human approval.
4. Post-Approval Resumed Execution:
   Operator clicks [Approve Plan & Fix], resuming autonomous execution through
   to successful 5-signal validation and PR generation.
5. Traceability: Audit log captures complete state sequence.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from agents.agent_3.day4_models import FindingCategory, UnifiedFinding
from agents.agent_3.day5_models import (
    AutonomousTriggerPayload,
    TriggerSessionState,
    TriggerSession,
)
from agents.agent_3.autonomous_trigger import AutonomousTriggerEngine
from tests.fixtures.day5_fixtures import SEEDED_FINDINGS_10, setup_workspace_for_day5_finding


def test_webhook_ingestion_and_auto_investigation_ac_e3_d5_02():
    """
    Acceptance Criteria AC-E3-D5-02 (Part 1):
    Inject test finding via webhook.
    Asserts:
    1. Session auto-progresses to ROOT_CAUSE in < 60 seconds.
    2. Strictly halts at ROOT_CAUSE and transitions to HUMAN_REVIEW.
    3. ZERO code changes made on disk prior to human approval.
    """
    engine = AutonomousTriggerEngine()
    finding = SEEDED_FINDINGS_10[0]  # BUG-PAGINATE-01

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_day5_finding(tmp_dir, finding)

        target_file = os.path.join(tmp_dir, "src", "catalog", "paginate.py")
        with open(target_file, "r", encoding="utf-8") as f:
            original_code = f.read()

        payload = AutonomousTriggerPayload(
            webhook_id="WH-ALERT-9901",
            source="sast_continuous_monitor",
            finding=finding,
        )

        # 1. Ingest via webhook (auto-triggers async investigation)
        session = engine.ingest_webhook(payload, worktree_dir=tmp_dir, auto_start_investigation=True)

        # Assertions on Auto-Investigation
        assert session is not None
        assert session.finding.finding_id == "BUG-PAGINATE-01"
        assert session.investigation_time_sec < 60.0, (
            f"Investigation latency {session.investigation_time_sec}s exceeded 60s target!"
        )

        # 2. Assert Mandatory Safety Pause at ROOT_CAUSE & HUMAN_REVIEW
        assert session.paused_at_root_cause is True
        assert session.state == TriggerSessionState.HUMAN_REVIEW
        assert "ROOT_CAUSE" in session.trace
        assert "HUMAN_REVIEW" in session.trace

        # 3. Root Cause Analysis Populated
        assert session.root_cause is not None
        assert "Off-by-one" in session.root_cause
        assert session.suggested_fix is not None

        # 4. HARD SAFETY GATE: Verify code on disk has NOT been modified
        with open(target_file, "r", encoding="utf-8") as f:
            current_code = f.read()
        assert current_code == original_code, (
            "SAFETY VIOLATION: Source code was modified before human authorization!"
        )


def test_approval_resumes_autonomous_execution_through_to_pr_ac_e3_d5_02():
    """
    Acceptance Criteria AC-E3-D5-02 (Part 2):
    Human operator clicks [Approve Plan & Fix].
    Asserts:
    1. Pipeline resumes execution through Planning, Executor, Testing, Validation, PR.
    2. Code modifications applied to disk post-approval.
    3. Final state is COMPLETED with PASS verdict and generated PR.
    """
    engine = AutonomousTriggerEngine()
    finding = SEEDED_FINDINGS_10[1]  # BUG-ZERO-FEE-02

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_day5_finding(tmp_dir, finding)

        client_file = os.path.join(tmp_dir, "src", "payment", "client.py")
        with open(client_file, "r", encoding="utf-8") as f:
            initial_code = f.read()

        payload = AutonomousTriggerPayload(
            webhook_id="WH-ALERT-9902",
            source="sentry_runtime_monitor",
            finding=finding,
        )

        # Ingest and pause at ROOT_CAUSE
        session = engine.ingest_webhook(payload, worktree_dir=tmp_dir)
        assert session.state == TriggerSessionState.HUMAN_REVIEW
        assert session.paused_at_root_cause is True

        # Human clicks [Approve Plan & Fix] via POST /sessions/{id}/approve
        context = engine.approve_session(
            session_id=session.session_id,
            approved_by="lead_security_engineer",
            notes="Authorized execution: fee calculation guardrail approved",
        )

        # Assert post-approval state progression
        updated_session = engine.get_session(session.session_id)
        assert updated_session is not None
        assert updated_session.state == TriggerSessionState.COMPLETED
        assert updated_session.approved_by == "lead_security_engineer"
        assert updated_session.paused_at_root_cause is False

        # Verify full state sequence
        expected_sequence = [
            "INGESTED",
            "INVESTIGATING",
            "ROOT_CAUSE",
            "HUMAN_REVIEW",
            "APPROVED",
            "EXECUTING",
            "COMPLETED",
        ]
        assert updated_session.trace == expected_sequence

        # Assert code was modified on disk post-approval
        with open(client_file, "r", encoding="utf-8") as f:
            post_approval_code = f.read()
        assert post_approval_code != initial_code
        assert "0.0 if amount <= 0.0" in post_approval_code

        # Assert validation passed and PR generated
        assert context.verdict is not None
        assert context.verdict.verdict == "PASS"
        assert context.pr_manifest is not None
        assert context.pr_manifest.branch_name.startswith("fix/bug-zero-fee")


def test_safety_guardrail_blocks_invalid_approval():
    """
    Verifies that approving an unknown or non-paused session raises an error.
    """
    engine = AutonomousTriggerEngine()

    with pytest.raises(ValueError, match="Session not found"):
        engine.approve_session("NON-EXISTENT-SESSION-ID")


def test_trace_log_export():
    """
    Verifies that audit trace logs export cleanly to disk.
    """
    engine = AutonomousTriggerEngine()
    finding = SEEDED_FINDINGS_10[5]  # DEP-REQ-01

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_day5_finding(tmp_dir, finding)
        payload = AutonomousTriggerPayload(webhook_id="WH-LOG-01", finding=finding)

        session = engine.ingest_webhook(payload, worktree_dir=tmp_dir)
        engine.approve_session(session.session_id, approved_by="qa_engineer")

        log_path = os.path.join(tmp_dir, "day5_autonomous_trigger_trace.log")
        engine.export_trace_log(log_path)

        assert os.path.exists(log_path)
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()

        assert "AUTONOMOUS TRIGGER V1 EXECUTION TRACE LOG" in log_content
        assert session.session_id in log_content
        assert "Safety Stop at ROOT_CAUSE" in log_content
        assert "Approved By: qa_engineer" in log_content
