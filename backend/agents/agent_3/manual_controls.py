"""
Purpose:
Task 41: Manual Control Layer (AC-E3-D4-02).
Provides human-in-the-loop intervention hooks allowing an operator to pause,
inspect, edit, and resume finding lifecycles across 7 explicit manual actions.

The 7 Explicit Manual Actions:
1. INVESTIGATE: Inspects repository finding details and defect context.
2. REVIEW_DIAGNOSIS: Reviews specialist root-cause diagnosis.
3. EDIT_PLAN: Modifies proposed plan, repair strategy, or diff.
4. APPROVE_EXECUTION: Authorizes applying code modifications to the worktree.
5. REVIEW_DIFF: Inspects generated git diff; allows manual patch edits.
6. RETRY: Resets or retries execution after adjustments.
7. OPEN_PR: Authorizes final Pull Request generation and submission.

Architectural Invariants:
1. Human Overrides Precedence: Human edits and abort commands take immediate
   precedence over automated steps.
2. Complete Auditability: Every operator intervention is recorded in an audit trace log.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Any, Tuple

from agents.agent_3.day2_models import ValidationVerdict, RepairPlan
from agents.agent_3.day3_models import PRManifest
from agents.agent_3.day4_models import (
    ManualAction,
    ManualControlCommand,
    UnifiedFinding,
    FindingContext,
)
from agents.agent_3.unified_pipeline import (
    UnifiedFindingPipeline,
    SpecialistAnalysisAdapter,
    CommonPlanner,
    CommonExecutor,
    CommonTestingNode,
    CommonValidationNode,
    CommonPRNode,
)


class ManualControlSession:
    """
    Stateful human-in-the-loop session governing the remediation lifecycle
    under operator oversight.
    """

    def __init__(self, finding: UnifiedFinding, worktree_dir: str):
        self.finding = finding
        self.worktree_dir = worktree_dir
        self.session_id = f"manual_sess_{finding.finding_id}_{int(time.time())}"
        
        # Pipeline primitives
        self.analysis_adapter = SpecialistAnalysisAdapter()
        self.planner = CommonPlanner()
        self.executor = CommonExecutor()
        self.tester = CommonTestingNode()
        self.validator = CommonValidationNode()
        self.pr_node = CommonPRNode()
        
        # Execution State
        self.context: Optional[FindingContext] = None
        self.current_stage: str = "INITIALIZED"
        self.is_paused: bool = False
        self.is_aborted: bool = False
        self.plan_was_edited: bool = False
        self.diff_was_edited: bool = False
        
        # Audit Trail
        self.audit_log: List[Dict[str, Any]] = []
        self._record_audit("INITIALIZED", "Session created under manual control")

    def _record_audit(self, action: str, details: str, notes: Optional[str] = None) -> None:
        """Records an entry in the session audit trail."""
        entry = {
            "session_id": self.session_id,
            "finding_id": self.finding.finding_id,
            "action": action,
            "stage": self.current_stage,
            "details": details,
            "notes": notes or "",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.audit_log.append(entry)

    # ─────────────────────────────────────────────────────────────────────────
    # The 7 Explicit Manual Action Handlers
    # ─────────────────────────────────────────────────────────────────────────

    def action_investigate(self, notes: Optional[str] = None) -> Dict[str, Any]:
        """Action 1: Investigate defect and repository state."""
        self.current_stage = "INVESTIGATING"
        target_exists = all(
            os.path.exists(os.path.join(self.worktree_dir, f))
            for f in self.finding.target_files
        )
        details = {
            "finding_id": self.finding.finding_id,
            "category": self.finding.category.value,
            "title": self.finding.title,
            "target_files": self.finding.target_files,
            "target_files_exist": target_exists,
            "severity": self.finding.severity,
        }
        self._record_audit(ManualAction.INVESTIGATE.value, "Investigation complete", notes)
        return {"status": "SUCCESS", "action": ManualAction.INVESTIGATE.value, "data": details}

    def action_review_diagnosis(self, notes: Optional[str] = None) -> Dict[str, Any]:
        """Action 2: Review specialist root-cause diagnosis."""
        self.current_stage = "DIAGNOSED"
        self.context = self.analysis_adapter.analyze(self.finding, self.worktree_dir)
        self.context.session_id = self.session_id
        
        details = {
            "diagnosis": self.context.diagnosis,
            "suggested_fix": self.context.suggested_fix,
            "proposed_diff": self.context.current_diff,
        }
        self._record_audit(ManualAction.REVIEW_DIAGNOSIS.value, f"Diagnosis generated: {self.context.diagnosis}", notes)
        return {"status": "SUCCESS", "action": ManualAction.REVIEW_DIAGNOSIS.value, "data": details}

    def action_edit_plan(
        self,
        edited_plan: Optional[str] = None,
        edited_diff: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Action 3: Human edits the plan or candidate diff.
        Invariant: Human overrides take immediate precedence over agent defaults.
        """
        if not self.context:
            self.action_review_diagnosis()

        # Generate default plan from context
        self.context = self.planner.plan(self.context, self.worktree_dir)
        self.current_stage = "PLAN_EDITED"

        # Apply human overrides if provided
        if edited_plan:
            self.plan_was_edited = True
            self.context.plan.diagnosis = f"[HUMAN_EDITED] {edited_plan}"
            self.context.diagnosis = self.context.plan.diagnosis

        if edited_diff:
            self.diff_was_edited = True
            self.context.current_diff = edited_diff
            self.context.plan.adjusted_patch = edited_diff

        details = {
            "plan_was_edited": self.plan_was_edited,
            "diff_was_edited": self.diff_was_edited,
            "active_diagnosis": self.context.diagnosis,
            "active_patch": self.context.plan.adjusted_patch,
        }
        self._record_audit(
            ManualAction.EDIT_PLAN.value,
            f"Plan updated by operator. Overrides applied: plan={self.plan_was_edited}, diff={self.diff_was_edited}",
            notes,
        )
        return {"status": "SUCCESS", "action": ManualAction.EDIT_PLAN.value, "data": details}

    def action_approve_execution(self, notes: Optional[str] = None) -> Dict[str, Any]:
        """Action 4: Authorizes applying code modifications and running tests."""
        if not self.context or not self.context.plan:
            raise RuntimeError("Cannot approve execution without an active plan.")

        self.current_stage = "EXECUTING"
        self._record_audit(ManualAction.APPROVE_EXECUTION.value, "Operator authorized patch application", notes)

        # Apply patch to worktree
        self.context = self.executor.execute(self.context, self.worktree_dir)

        # Run tests on worktree
        self.context = self.tester.test(self.context, self.worktree_dir)

        self.current_stage = "EXECUTED"
        return {
            "status": "SUCCESS",
            "action": ManualAction.APPROVE_EXECUTION.value,
            "stage": self.current_stage,
        }

    def action_review_diff(
        self,
        edited_diff: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Action 5: Human reviews executed diff and runs 5-signal validation.
        Allows fine-grained diff adjustments before validation.
        """
        if not self.context:
            raise RuntimeError("No active context to review diff.")

        if edited_diff:
            self.diff_was_edited = True
            self.context.current_diff = edited_diff
            if self.context.plan:
                self.context.plan.adjusted_patch = edited_diff
            # Re-apply edited diff to worktree
            self.executor.apply_diff(self.worktree_dir, edited_diff)

        # Run 5-signal validation
        self.context = self.validator.validate(self.context, self.worktree_dir)
        self.current_stage = "DIFF_REVIEWED"

        verdict_status = self.context.verdict.verdict if self.context.verdict else "UNKNOWN"
        score = self.context.verdict.score if self.context.verdict else 0.0

        details = {
            "verdict": verdict_status,
            "score": score,
            "diff_was_edited": self.diff_was_edited,
            "current_diff": self.context.current_diff,
        }
        self._record_audit(
            ManualAction.REVIEW_DIFF.value,
            f"Diff reviewed. Validation Verdict: {verdict_status} ({score * 100:.0f}%)",
            notes,
        )
        return {"status": "SUCCESS", "action": ManualAction.REVIEW_DIFF.value, "data": details}

    def action_retry(self, notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Action 6: Operator triggers retry or re-plan iteration.
        """
        self.current_stage = "RETRYING"
        self._record_audit(ManualAction.RETRY.value, "Operator requested retry iteration", notes)
        
        # Reset validation verdict and re-plan
        if self.context:
            self.context.verdict = None
            self.context.stage = "PLANNER"
            self.context = self.planner.plan(self.context, self.worktree_dir)

        self.current_stage = "RETRY_READY"
        return {"status": "SUCCESS", "action": ManualAction.RETRY.value, "stage": self.current_stage}

    def action_open_pr(self, notes: Optional[str] = None) -> Dict[str, Any]:
        """
        Action 7: Human authorizes opening Pull Request.
        """
        if not self.context:
            raise RuntimeError("No active context to open PR.")

        if not self.context.verdict or self.context.verdict.verdict != "PASS":
            # Force validation before PR opening
            self.context = self.validator.validate(self.context, self.worktree_dir)

        self.context = self.pr_node.generate_pr(self.context, self.worktree_dir)
        self.current_stage = "PR_OPENED"

        details = {
            "pr_manifest": self.context.pr_manifest.model_dump() if self.context.pr_manifest else None,
            "stage": self.context.stage,
        }
        self._record_audit(
            ManualAction.OPEN_PR.value,
            f"PR opened: {self.context.pr_manifest.title if self.context.pr_manifest else 'FAILED'}",
            notes,
        )
        return {"status": "SUCCESS", "action": ManualAction.OPEN_PR.value, "data": details}

    # ─────────────────────────────────────────────────────────────────────────
    # Command Dispatcher & Override Invariants
    # ─────────────────────────────────────────────────────────────────────────

    def dispatch(self, command: ManualControlCommand) -> Dict[str, Any]:
        """
        Dispatches a structured ManualControlCommand to the appropriate action handler.
        Enforces:
        1. Human override: if authorized=False, immediately pause/abort execution.
        2. Plan/diff overrides are routed directly to handlers.
        """
        # Guardrail: Immediate Abort / Pause on unauthorized command
        if not command.authorized:
            self.is_paused = True
            self.current_stage = "PAUSED_BY_HUMAN"
            self._record_audit(
                command.action.value,
                f"EXECUTION HALTED: Operator denied authorization for {command.action.value}",
                command.notes,
            )
            return {
                "status": "HALTED",
                "action": command.action.value,
                "reason": "Operator denied authorization",
                "stage": self.current_stage,
            }

        action_map = {
            ManualAction.INVESTIGATE: lambda: self.action_investigate(notes=command.notes),
            ManualAction.REVIEW_DIAGNOSIS: lambda: self.action_review_diagnosis(notes=command.notes),
            ManualAction.EDIT_PLAN: lambda: self.action_edit_plan(
                edited_plan=command.edited_plan,
                edited_diff=command.edited_diff,
                notes=command.notes,
            ),
            ManualAction.APPROVE_EXECUTION: lambda: self.action_approve_execution(notes=command.notes),
            ManualAction.REVIEW_DIFF: lambda: self.action_review_diff(
                edited_diff=command.edited_diff,
                notes=command.notes,
            ),
            ManualAction.RETRY: lambda: self.action_retry(notes=command.notes),
            ManualAction.OPEN_PR: lambda: self.action_open_pr(notes=command.notes),
        }

        handler = action_map.get(command.action)
        if not handler:
            raise ValueError(f"Unknown manual action: {command.action}")

        return handler()

    def export_audit_log(self, filepath: str) -> None:
        """Writes formatted audit trail to log file."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"=== MANUAL CONTROL AUDIT TRAIL ===\n")
            f.write(f"Session ID: {self.session_id}\n")
            f.write(f"Finding ID: {self.finding.finding_id}\n")
            f.write(f"Total Actions: {len(self.audit_log)}\n")
            f.write(f"Plan Edited: {self.plan_was_edited}\n")
            f.write(f"Diff Edited: {self.diff_was_edited}\n\n")
            for entry in self.audit_log:
                f.write(f"[{entry['timestamp']}] [{entry['action']}] Stage: {entry['stage']}\n")
                f.write(f"  Details: {entry['details']}\n")
                if entry['notes']:
                    f.write(f"  Notes: {entry['notes']}\n")
                f.write("\n")
