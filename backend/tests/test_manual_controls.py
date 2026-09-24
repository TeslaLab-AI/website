"""
Purpose:
Task 41 Test Suite: Manual Control Layer (AC-E3-D4-02).
Verifies:
1. All 7 explicit manual actions:
   INVESTIGATE, REVIEW_DIAGNOSIS, EDIT_PLAN, APPROVE_EXECUTION, REVIEW_DIFF, RETRY, OPEN_PR.
2. Acceptance Criteria AC-E3-D4-02:
   Drives a bug lifecycle through all 7 actions, modifies the plan during Step 3,
   and verifies the agent executes the edited plan and opens the PR.
3. Human Override Precedence:
   Unauthorized commands immediately halt the automated loop.
4. Complete Audit Trail:
   All interventions and human overrides are captured in audit logs.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from agents.agent_3.day4_models import (
    ManualAction,
    ManualControlCommand,
    FindingCategory,
    UnifiedFinding,
)
from agents.agent_3.manual_controls import ManualControlSession
from tests.fixtures.day4_fixtures import SEEDED_FINDINGS_6, setup_workspace_for_finding


def test_manual_action_enum_and_command_validation():
    """
    Verifies that all 7 mandatory actions exist in the ManualAction enum.
    """
    expected_actions = {
        "INVESTIGATE",
        "REVIEW_DIAGNOSIS",
        "EDIT_PLAN",
        "APPROVE_EXECUTION",
        "REVIEW_DIFF",
        "RETRY",
        "OPEN_PR",
    }
    actual_actions = {a.value for a in ManualAction}
    assert expected_actions == actual_actions, f"Mismatch in manual actions: {actual_actions}"


def test_full_7_action_lifecycle_with_plan_edit_ac_e3_d4_02():
    """
    Acceptance Criteria AC-E3-D4-02:
    Drives a finding lifecycle through all 7 manual actions in sequence:
    1. Investigate
    2. Review Diagnosis
    3. Edit Plan (Operator modifies plan text/diff)
    4. Approve Execution
    5. Review Diff
    6. Retry
    7. Open PR

    Verifies that:
    - The human-edited plan is honored and executed.
    - All 7 actions are logged in the audit trail.
    - PR is generated and opened successfully.
    """
    finding = SEEDED_FINDINGS_6[0]  # BUG-PAGINATE-01

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_finding(tmp_dir, finding)
        session = ManualControlSession(finding, tmp_dir)

        # ─────────────────────────────────────────────────────────────────────
        # Action 1: INVESTIGATE
        # ─────────────────────────────────────────────────────────────────────
        cmd_1 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.INVESTIGATE,
            notes="Operator inspecting bug context and file paths",
        )
        res_1 = session.dispatch(cmd_1)
        assert res_1["status"] == "SUCCESS"
        assert res_1["data"]["finding_id"] == "BUG-PAGINATE-01"
        assert res_1["data"]["target_files_exist"] is True
        assert session.current_stage == "INVESTIGATING"

        # ─────────────────────────────────────────────────────────────────────
        # Action 2: REVIEW_DIAGNOSIS
        # ─────────────────────────────────────────────────────────────────────
        cmd_2 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.REVIEW_DIAGNOSIS,
            notes="Operator reviewing specialist analysis",
        )
        res_2 = session.dispatch(cmd_2)
        assert res_2["status"] == "SUCCESS"
        assert "Off-by-one" in res_2["data"]["diagnosis"]
        assert session.current_stage == "DIAGNOSED"

        # ─────────────────────────────────────────────────────────────────────
        # Action 3: EDIT_PLAN (AC-E3-D4-02 Core Requirement)
        # ─────────────────────────────────────────────────────────────────────
        custom_plan_notes = "Senior Reviewer override: ensure boundary uses exact page_size slice without off-by-one."
        cmd_3 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.EDIT_PLAN,
            edited_plan=custom_plan_notes,
            notes="Operator customized remediation plan wording and guardrails",
        )
        res_3 = session.dispatch(cmd_3)
        assert res_3["status"] == "SUCCESS"
        assert res_3["data"]["plan_was_edited"] is True
        assert session.plan_was_edited is True
        assert custom_plan_notes in session.context.diagnosis
        assert session.current_stage == "PLAN_EDITED"

        # ─────────────────────────────────────────────────────────────────────
        # Action 4: APPROVE_EXECUTION
        # ─────────────────────────────────────────────────────────────────────
        cmd_4 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.APPROVE_EXECUTION,
            notes="Operator approved applying code modifications",
        )
        res_4 = session.dispatch(cmd_4)
        assert res_4["status"] == "SUCCESS"
        assert session.current_stage == "EXECUTED"

        # ─────────────────────────────────────────────────────────────────────
        # Action 5: REVIEW_DIFF
        # ─────────────────────────────────────────────────────────────────────
        cmd_5 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.REVIEW_DIFF,
            notes="Operator verifying 5-signal validation results",
        )
        res_5 = session.dispatch(cmd_5)
        assert res_5["status"] == "SUCCESS"
        assert res_5["data"]["verdict"] == "PASS"
        assert res_5["data"]["score"] >= 0.90
        assert session.current_stage == "DIFF_REVIEWED"

        # ─────────────────────────────────────────────────────────────────────
        # Action 6: RETRY
        # ─────────────────────────────────────────────────────────────────────
        cmd_6 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.RETRY,
            notes="Operator triggered retry round for audit verification",
        )
        res_6 = session.dispatch(cmd_6)
        assert res_6["status"] == "SUCCESS"
        assert session.current_stage == "RETRY_READY"

        # Re-approve and re-validate after retry iteration
        session.dispatch(ManualControlCommand(session_id=session.session_id, action=ManualAction.APPROVE_EXECUTION))
        session.dispatch(ManualControlCommand(session_id=session.session_id, action=ManualAction.REVIEW_DIFF))

        # ─────────────────────────────────────────────────────────────────────
        # Action 7: OPEN_PR
        # ─────────────────────────────────────────────────────────────────────
        cmd_7 = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.OPEN_PR,
            notes="Operator approved final Pull Request submission",
        )
        res_7 = session.dispatch(cmd_7)
        assert res_7["status"] == "SUCCESS"
        assert session.current_stage == "PR_OPENED"
        assert res_7["data"]["pr_manifest"] is not None
        assert res_7["data"]["pr_manifest"]["branch_name"] == "fix/bug-paginate-01"
        assert "fix(BUG-PAGINATE-01)" in res_7["data"]["pr_manifest"]["title"]

        # ─────────────────────────────────────────────────────────────────────
        # Audit Trail Assertions
        # ─────────────────────────────────────────────────────────────────────
        audit_actions = [e["action"] for e in session.audit_log]
        for act in ManualAction:
            assert act.value in audit_actions, f"Action {act.value} not present in audit log: {audit_actions}"

        # Export audit log
        log_path = os.path.join(tmp_dir, "day4_manual_controls_trace.log")
        session.export_audit_log(log_path)
        assert os.path.exists(log_path)
        with open(log_path, "r", encoding="utf-8") as f:
            log_content = f.read()
        assert "MANUAL CONTROL AUDIT TRAIL" in log_content
        assert "Plan Edited: True" in log_content


def test_human_override_immediate_abort_precedence():
    """
    Invariant Test:
    Asserts that when an operator denies authorization (authorized=False),
    the session immediately halts and sets current_stage to 'PAUSED_BY_HUMAN'.
    """
    finding = SEEDED_FINDINGS_6[1]  # BUG-ZERO-FEE-02

    with tempfile.TemporaryDirectory() as tmp_dir:
        setup_workspace_for_finding(tmp_dir, finding)
        session = ManualControlSession(finding, tmp_dir)

        # Investigate
        session.dispatch(ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.INVESTIGATE,
        ))

        # Operator denies execution
        abort_cmd = ManualControlCommand(
            session_id=session.session_id,
            action=ManualAction.APPROVE_EXECUTION,
            authorized=False,
            notes="Security lead veto: potential compliance conflict",
        )
        res = session.dispatch(abort_cmd)

        assert res["status"] == "HALTED"
        assert session.is_paused is True
        assert session.current_stage == "PAUSED_BY_HUMAN"

        # Check audit trail recorded the halt
        last_entry = session.audit_log[-1]
        assert "HALTED" in last_entry["details"]
        assert "Security lead veto" in last_entry["notes"]
