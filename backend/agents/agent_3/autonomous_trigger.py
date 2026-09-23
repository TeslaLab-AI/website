"""
Purpose:
Task 44: Autonomous Trigger v1 & Safety Gate (AC-E3-D5-02).
Implements a semi-autonomous ingestion pipeline for automated scanner findings
with a hard-coded safety stop at ROOT_CAUSE before any code modification.

Workflow:
1. Ingestion: Scanner finding arrives via webhook -> auto-creates task session.
2. Auto-Investigation: Asynchronously investigates defect and derives root cause in <60s.
3. MANDATORY SAFETY PAUSE: Strictly halts at ROOT_CAUSE state -> transitions to HUMAN_REVIEW.
   Architectural Invariant: ZERO automatic code modification permitted without human approval.
4. Human Approval: Operator clicks [Approve Plan & Fix] -> resumes execution through
   Planning, Sandbox Execution, Testing, Validation, and PR generation.

Acceptance Criteria:
- AC-E3-D5-02: Inject test finding via webhook; assert session auto-progresses to
  ROOT_CAUSE in <60s; verify it strictly halts until approval, then executes to completion.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Dict, List, Optional, Any, Tuple

from agents.agent_3.day4_models import UnifiedFinding, FindingContext
from agents.agent_3.day5_models import (
    AutonomousTriggerPayload,
    TriggerSessionState,
    TriggerSession,
)
from agents.agent_3.unified_pipeline import (
    SpecialistAnalysisAdapter,
    CommonPlanner,
    CommonExecutor,
    CommonTestingNode,
    CommonValidationNode,
    CommonPRNode,
)


class AutonomousTriggerEngine:
    """
    Engine managing automated scanner ingestion, auto-investigation,
    the mandatory ROOT_CAUSE safety pause, and post-approval execution.
    """

    def __init__(self):
        self.analysis_adapter = SpecialistAnalysisAdapter()
        self.planner = CommonPlanner()
        self.executor = CommonExecutor()
        self.tester = CommonTestingNode()
        self.validator = CommonValidationNode()
        self.pr_node = CommonPRNode()

        # Session registry: session_id -> TriggerSession
        self.sessions: Dict[str, TriggerSession] = {}
        # Worktree registry: session_id -> worktree_dir
        self._worktrees: Dict[str, str] = {}
        # Cached analysis contexts: session_id -> FindingContext
        self._contexts: Dict[str, FindingContext] = {}

    def ingest_webhook(
        self,
        payload: AutonomousTriggerPayload,
        worktree_dir: str,
        auto_start_investigation: bool = True,
    ) -> TriggerSession:
        """
        Step 1: Webhook intake receiving automated scanner alerts.
        Creates a new TriggerSession in INGESTED state.
        """
        session_id = f"TRIG-{payload.finding.finding_id}-{uuid.uuid4().hex[:6]}"
        session = TriggerSession(
            session_id=session_id,
            finding=payload.finding,
            state=TriggerSessionState.INGESTED,
            trace=["INGESTED"],
        )
        self.sessions[session_id] = session
        self._worktrees[session_id] = worktree_dir

        if auto_start_investigation:
            self.run_auto_investigation(session_id)

        return session

    def run_auto_investigation(self, session_id: str) -> TriggerSession:
        """
        Step 2: Auto-runs investigation to derive root cause and enforce safety pause.
        Must complete in <60 seconds and strictly halt at ROOT_CAUSE / HUMAN_REVIEW.
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        worktree_dir = self._worktrees.get(session_id, ".")

        # Transition to INVESTIGATING
        session.state = TriggerSessionState.INVESTIGATING
        session.trace.append("INVESTIGATING")
        t0 = time.time()

        # Execute specialist analysis to derive root cause
        context = self.analysis_adapter.analyze(session.finding, worktree_dir)
        context.session_id = session_id
        self._contexts[session_id] = context

        elapsed = round(time.time() - t0, 3)
        session.investigation_time_sec = elapsed
        session.root_cause = context.diagnosis
        session.suggested_fix = context.suggested_fix

        # ─────────────────────────────────────────────────────────────────────
        # MANDATORY SAFETY STOP: Halt at ROOT_CAUSE & enter HUMAN_REVIEW
        # ─────────────────────────────────────────────────────────────────────
        session.state = TriggerSessionState.ROOT_CAUSE
        session.trace.append("ROOT_CAUSE")
        session.paused_at_root_cause = True

        # Enter HUMAN_REVIEW: zero automatic code changes allowed
        session.state = TriggerSessionState.HUMAN_REVIEW
        session.trace.append("HUMAN_REVIEW")

        return session

    def approve_session(
        self,
        session_id: str,
        approved_by: str = "human_operator",
        notes: Optional[str] = None,
    ) -> FindingContext:
        """
        Step 3: Approval Action Hook (`POST /sessions/{id}/approve`).
        Human operator clicks [Approve Plan & Fix], authorizing code execution
        and resuming execution through Planning, Execution, Validation, and PR.
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if session.state != TriggerSessionState.HUMAN_REVIEW and not session.paused_at_root_cause:
            raise RuntimeError(
                f"Cannot approve session in state '{session.state}'. Must be in 'HUMAN_REVIEW'."
            )

        worktree_dir = self._worktrees.get(session_id, ".")
        context = self._contexts.get(session_id)
        if not context:
            raise RuntimeError(f"Missing analysis context for session: {session_id}")

        # Human authorization applied
        session.approved_by = approved_by
        session.paused_at_root_cause = False
        session.state = TriggerSessionState.APPROVED
        session.trace.append("APPROVED")

        # ─────────────────────────────────────────────────────────────────────
        # Resumed Execution: Planning -> Executor -> Testing -> Validation -> PR
        # ─────────────────────────────────────────────────────────────────────
        session.state = TriggerSessionState.EXECUTING
        session.trace.append("EXECUTING")

        # 1. Common Planner
        context = self.planner.plan(context, worktree_dir)

        # 2. Common Executor (Code changes applied to worktree)
        context = self.executor.execute(context, worktree_dir)

        # 3. Common Testing
        context = self.tester.test(context, worktree_dir)

        # 4. Common Validation
        context = self.validator.validate(context, worktree_dir)

        # 5. Common PR
        context = self.pr_node.generate_pr(context, worktree_dir)

        # Transition to COMPLETED
        session.state = TriggerSessionState.COMPLETED
        session.trace.append("COMPLETED")
        session.context = context

        return context

    def get_session(self, session_id: str) -> Optional[TriggerSession]:
        """Retrieves session state."""
        return self.sessions.get(session_id)

    def export_trace_log(self, filepath: str) -> None:
        """Exports audit trace log across all trigger sessions."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=== AUTONOMOUS TRIGGER V1 EXECUTION TRACE LOG ===\n\n")
            for sid, s in self.sessions.items():
                f.write(f"Session ID: {s.session_id}\n")
                f.write(f"Finding ID: {s.finding.finding_id} ({s.finding.title})\n")
                f.write(f"Investigation Latency: {s.investigation_time_sec:.3f}s (Target < 60s: {'PASS' if s.investigation_time_sec < 60 else 'FAIL'})\n")
                f.write(f"Safety Stop at ROOT_CAUSE: {s.paused_at_root_cause}\n")
                f.write(f"Approved By: {s.approved_by or 'None'}\n")
                f.write(f"State Sequence: {' -> '.join(s.trace)}\n")
                f.write(f"Final State: {s.state.value}\n")
                if s.context and s.context.verdict:
                    f.write(f"Validation Verdict: {s.context.verdict.verdict} ({s.context.verdict.score * 100:.0f}%)\n")
                if s.context and s.context.pr_manifest:
                    f.write(f"PR Generated: {s.context.pr_manifest.title} ({s.context.pr_manifest.branch_name})\n")
                f.write("-" * 80 + "\n\n")
