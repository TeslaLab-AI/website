"""
Purpose:
Task 36: Full Autonomous Repair Loop & Circuit Breakers.
Implements the end-to-end cyclical repair loop:
PLAN -> EXECUTE -> TEST -> VALIDATE -> (if FAIL) REPAIR -> REPLAN -> RE-EXECUTE -> RE-TEST -> VALIDATE -> PR_READY.

Architecture & Circuit Breakers:
1. Hard Cost Ceiling: Halts immediately if accumulated cost exceeds $0.50 (AC-E3-D2-03).
2. Timeout Breaker: Halts immediately if elapsed duration exceeds 300 seconds (AC-E3-D2-03).
3. Cyclic Diff Prevention: Hashes diffs with SHA-256; halts immediately if an identical
   patch hash repeats (preventing infinite loops) (AC-E3-D2-03).
4. Telemetry: Emits granular LoopIterationEvent records across all states.

Acceptance Criteria:
- AC-E3-D2-03: Tripping any of the 3 circuit breakers halts loop cleanly with informative error state.
- AC-E3-D2-04: Resolves >= 3 of 5 seeded benchmark bugs unattended within <= 3 rounds to reach PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Callable, Dict, List, Optional, Tuple, Any

from agents.agent_3.day2_models import (
    CheckResult,
    ValidationVerdict,
    RepairPlan,
    LoopState,
    LoopIterationEvent,
)
from agents.agent_3.validation_engine import ValidationEngine
from agents.agent_3.repair_agent import RepairAgent


def compute_diff_hash(diff_text: str) -> str:
    """Computes SHA-256 hex digest of normalized diff text."""
    normalized = diff_text.strip().replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class AutonomousRepairLoop:
    """
    Autonomous cyclical engine managing repair attempts and circuit breakers.
    """

    def __init__(
        self,
        session_id: str = "default_session",
        max_attempts: int = 3,
        max_cost: float = 0.50,
        max_time_sec: float = 300.0,
    ):
        self.state = LoopState(
            session_id=session_id,
            current_step="PLAN",
            attempt_count=0,
            max_attempts=max_attempts,
            accumulated_cost=0.0,
            max_cost=max_cost,
            elapsed_time_sec=0.0,
            max_time_sec=max_time_sec,
            diff_history=[],
            diff_hashes=[],
            circuit_breaker_tripped=False,
            trip_reason=None,
            events=[],
        )

    def record_event(
        self,
        step: str,
        status: str,
        details: Dict[str, Any],
        cost: float = 0.0,
    ) -> LoopIterationEvent:
        """Emits and records a telemetry event in loop state history."""
        event = LoopIterationEvent(
            iteration=self.state.attempt_count,
            step=step,
            status=status,
            details=details,
            cost=cost,
        )
        self.state.events.append(event)
        return event

    def check_circuit_breakers(
        self,
        new_diff: str = "",
        step_cost: float = 0.0,
        step_time: float = 0.0,
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates the 3 mandatory circuit breakers:
        1. Cost ceiling ($0.50)
        2. Timeout ceiling (300.0s)
        3. Cyclic diff prevention (SHA-256 match)

        Returns (is_tripped, trip_reason).
        """
        # Breaker 1: Cumulative Cost Ceiling ($0.50)
        projected_cost = self.state.accumulated_cost + step_cost
        if projected_cost > self.state.max_cost:
            reason = (
                f"CIRCUIT_BREAKER_COST: Accumulated cost ${projected_cost:.3f} "
                f"exceeds hard ceiling of ${self.state.max_cost:.2f} USD."
            )
            return True, reason

        # Breaker 2: Execution Timeout Ceiling (300 seconds)
        projected_time = self.state.elapsed_time_sec + step_time
        if projected_time > self.state.max_time_sec:
            reason = (
                f"CIRCUIT_BREAKER_TIMEOUT: Elapsed time {projected_time:.1f}s "
                f"exceeds maximum threshold of {self.state.max_time_sec:.1f}s."
            )
            return True, reason

        # Breaker 3: Cyclic Diff Prevention
        if new_diff and new_diff.strip():
            diff_hash = compute_diff_hash(new_diff)
            if diff_hash in self.state.diff_hashes:
                reason = (
                    f"CIRCUIT_BREAKER_CYCLIC_DIFF: Patch hash {diff_hash[:12]} was already "
                    f"attempted in a previous iteration. Halting cycle to avoid infinite loop."
                )
                return True, reason

        return False, None

    def trip_circuit_breaker(self, reason: str) -> None:
        """Sets circuit breaker tripped state and halts execution cleanly."""
        self.state.circuit_breaker_tripped = True
        self.state.trip_reason = reason
        self.state.current_step = "HALTED_CIRCUIT_BREAKER"
        self.record_event(
            step="CIRCUIT_BREAKER",
            status="TRIPPED",
            details={"reason": reason},
            cost=0.0,
        )

    def run_loop(
        self,
        worktree_dir: str,
        initial_diff: str,
        task_desc: str,
        target_files: List[str],
        repro_test_path: Optional[str] = None,
        apply_repair_callback: Optional[Callable[[RepairPlan, str], bool]] = None,
        step_cost: float = 0.02,
        step_time: float = 1.0,
    ) -> Tuple[LoopState, Optional[ValidationVerdict]]:
        """
        Executes the autonomous loop through convergence or circuit breaker halt.
        """
        current_diff = initial_diff
        last_verdict: Optional[ValidationVerdict] = None

        while True:
            # ─────────────────────────────────────────────────────────────────
            # Step A: Check Circuit Breakers before entering evaluation
            # ─────────────────────────────────────────────────────────────────
            tripped, trip_reason = self.check_circuit_breakers(
                new_diff=current_diff,
                step_cost=step_cost,
                step_time=step_time,
            )
            if tripped:
                self.trip_circuit_breaker(trip_reason or "Unknown breaker tripped")
                break

            # Register diff and update resource counters
            diff_hash = compute_diff_hash(current_diff)
            self.state.diff_hashes.append(diff_hash)
            self.state.diff_history.append(current_diff)
            self.state.accumulated_cost = round(self.state.accumulated_cost + step_cost, 4)
            self.state.elapsed_time_sec = round(self.state.elapsed_time_sec + step_time, 2)

            # ─────────────────────────────────────────────────────────────────
            # Step B: VALIDATE using 5-Signal Engine
            # ─────────────────────────────────────────────────────────────────
            self.state.current_step = "VALIDATE"
            self.record_event(
                step="VALIDATE",
                status="IN_PROGRESS",
                details={"diff_hash": diff_hash[:10], "attempt": self.state.attempt_count},
                cost=step_cost,
            )

            last_verdict = ValidationEngine.evaluate(
                worktree_dir=worktree_dir,
                diff_text=current_diff,
                task_desc=task_desc,
                target_files=target_files,
                repro_test_path=repro_test_path,
            )

            # ─────────────────────────────────────────────────────────────────
            # Step C: Branch on PASS vs FAIL
            # ─────────────────────────────────────────────────────────────────
            if last_verdict.verdict == "PASS":
                self.state.current_step = "PR_READY"
                self.record_event(
                    step="PR_READY",
                    status="SUCCESS",
                    details={"score": last_verdict.score, "attempts": self.state.attempt_count},
                )
                break

            # If FAIL: transition to REPAIR
            self.record_event(
                step="VALIDATE",
                status="FAILURE",
                details={"failure_reasons": last_verdict.failure_reasons},
            )

            # Check attempt limit
            if self.state.attempt_count >= self.state.max_attempts:
                self.state.current_step = "NEEDS_HUMAN"
                self.record_event(
                    step="REPAIR",
                    status="NEEDS_HUMAN",
                    details={
                        "reason": f"Exceeded max repair attempts ({self.state.max_attempts}). Escalating to human."
                    },
                )
                break

            # ─────────────────────────────────────────────────────────────────
            # Step D: REPAIR — Synthesize new plan
            # ─────────────────────────────────────────────────────────────────
            self.state.attempt_count += 1
            self.state.current_step = "REPAIR"

            repair_plan = RepairAgent.generate_repair_plan(
                session_id=self.state.session_id,
                current_attempt=self.state.attempt_count,
                failed_diff=current_diff,
                verdict=last_verdict,
            )

            self.record_event(
                step="REPAIR",
                status=repair_plan.status,
                details={
                    "diagnosis": repair_plan.diagnosis,
                    "target_components": repair_plan.target_components,
                },
            )

            if repair_plan.status == "NEEDS_HUMAN":
                self.state.current_step = "NEEDS_HUMAN"
                break

            # ─────────────────────────────────────────────────────────────────
            # Step E: Apply Repair Patch and loop back
            # ─────────────────────────────────────────────────────────────────
            current_diff = repair_plan.adjusted_patch

            # Apply changes to actual worktree files via callback or default applier
            if apply_repair_callback:
                applied = apply_repair_callback(repair_plan, worktree_dir)
                if not applied:
                    self.state.current_step = "NEEDS_HUMAN"
                    break

            self.state.current_step = "REPLAN"

        return self.state, last_verdict

    def export_state_history(self, output_path: str) -> None:
        """Dumps loop execution history and events to JSON file for evidence."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        payload = self.state.model_dump()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def export_circuit_breaker_log(self, output_path: str) -> None:
        """Dumps circuit breaker audit trail to text file for evidence."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"=== CIRCUIT BREAKER AUDIT LOG ===\n")
            f.write(f"Session ID: {self.state.session_id}\n")
            f.write(f"Tripped: {self.state.circuit_breaker_tripped}\n")
            f.write(f"Trip Reason: {self.state.trip_reason or 'None'}\n")
            f.write(f"Accumulated Cost: ${self.state.accumulated_cost:.3f} / Max: ${self.state.max_cost:.2f}\n")
            f.write(f"Elapsed Time: {self.state.elapsed_time_sec:.1f}s / Max: {self.state.max_time_sec:.1f}s\n")
            f.write(f"Unique Diffs Evaluated: {len(self.state.diff_hashes)}\n")
            f.write(f"Total Telemetry Events: {len(self.state.events)}\n")
