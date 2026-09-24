"""
Purpose:
Day 5 Shared Contracts and Data Models for Engineer 3 (Tasks 43, 44, 45).

Includes:
1. EvaluationMetrics: 10 core performance dimensions (Task 43 / AC-E3-D5-01).
2. AutonomousTriggerPayload & TriggerSession: Webhook ingestion with mandatory
   safety pause at ROOT_CAUSE (Task 44 / AC-E3-D5-02).
3. BenchmarkThresholdAudit: Verification against all 7 Stage 0 quantitative
   thresholds (Task 45 / AC-E3-D5-03).
4. DemoScenario: Tracking the 4 live demonstration workflows (Task 45 / AC-E3-D5-04).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from agents.agent_3.day4_models import UnifiedFinding, FindingContext


# ─────────────────────────────────────────────────────────────────────────────
# 1. Task 43 Contract: EvaluationMetrics (10 Core Dimensions)
# ─────────────────────────────────────────────────────────────────────────────

class EvaluationMetrics(BaseModel):
    """
    Standardized measurement schema tracking all 10 core Stage 0 performance dimensions.
    Must be computed strictly from persistent event telemetry with zero estimation.
    """
    # 1. Task success rate: percentage of tasks reaching PR_READY/COMPLETE with PASS
    task_success_rate: float = Field(..., ge=0.0, le=1.0, description="Rate of tasks successfully reaching PR completion")
    
    # 2. Root-cause accuracy: percentage of diagnoses matching true fault
    root_cause_accuracy: float = Field(..., ge=0.0, le=1.0, description="Accuracy of root-cause diagnostic assessments")
    
    # 3. Plan validity rate: percentage of plans syntactically valid & targeting correct components
    plan_validity_rate: float = Field(..., ge=0.0, le=1.0, description="Percentage of synthesized plans valid for execution")
    
    # 4. First-pass fix rate: percentage passing validation on attempt 1 without repair loop
    first_pass_fix_rate: float = Field(..., ge=0.0, le=1.0, description="Percentage of findings fixed on first attempt")
    
    # 5. Repair convergence rate: percentage of initially failing tasks converging in <= 3 rounds
    repair_convergence_rate: float = Field(..., ge=0.0, le=1.0, description="Convergence rate of self-healing repair loop")
    
    # 6. Regression rate: percentage of candidate patches that broke existing regression tests
    regression_rate: float = Field(..., ge=0.0, le=1.0, description="Percentage of patches introducing functional regressions")
    
    # 7. Time to PR: average elapsed time from ingestion to open PR manifest (in seconds)
    time_to_pr_sec: float = Field(..., ge=0.0, description="Average elapsed time from finding ingestion to PR manifest")
    
    # 8. Cost per task: average accumulated USD expenditure per task
    cost_per_task_usd: float = Field(..., ge=0.0, description="Average accumulated execution cost in USD")
    
    # 9. Token efficiency: ratio of productive patch tokens vs total generated tokens
    token_efficiency: float = Field(..., ge=0.0, le=1.0, description="Token efficiency ratio")
    
    # 10. Human intervention rate: percentage of tasks requiring operator intervention
    human_intervention_rate: float = Field(..., ge=0.0, le=1.0, description="Percentage of tasks requiring human intervention")

    # Aggregate Counters
    total_tasks: int = Field(default=0, ge=0, description="Total number of tasks evaluated")
    tasks_passed: int = Field(default=0, ge=0, description="Number of tasks reaching PASS verdict")
    benchmark_repo: str = Field(default="repo_stage0_benchmark", description="Evaluated benchmark repository ID")
    generated_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Task 44 Contract: AutonomousTriggerPayload & TriggerSessionState
# ─────────────────────────────────────────────────────────────────────────────

class TriggerSessionState(str, Enum):
    """
    State machine stages for autonomous ingestion.
    Mandatory Invariant: Pipeline must strictly halt at ROOT_CAUSE and enter HUMAN_REVIEW.
    """
    INGESTED = "INGESTED"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE = "ROOT_CAUSE"          # Mandatory safety pause boundary
    HUMAN_REVIEW = "HUMAN_REVIEW"      # Awaiting human authorization
    APPROVED = "APPROVED"              # Human clicked [Approve Plan & Fix]
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    HALTED = "HALTED"


class AutonomousTriggerPayload(BaseModel):
    """
    Webhook intake schema receiving automated scanner alerts.
    """
    webhook_id: str = Field(..., description="Unique webhook event identifier")
    source: str = Field(default="automated_scanner", description="Ingestion source (e.g. sast, dependabot, sentry)")
    finding: UnifiedFinding = Field(..., description="Canonical unified finding payload")
    received_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class TriggerSession(BaseModel):
    """
    Execution state for semi-autonomous trigger sessions with hard-coded root-cause pause.
    """
    session_id: str = Field(..., description="Unique trigger session identifier")
    finding: UnifiedFinding = Field(..., description="Active finding being processed")
    state: TriggerSessionState = Field(default=TriggerSessionState.INGESTED, description="Active session state")
    
    root_cause: Optional[str] = Field(default=None, description="Diagnostic root-cause assessment")
    suggested_fix: Optional[str] = Field(default=None, description="Proposed remediation strategy")
    
    investigation_time_sec: float = Field(default=0.0, description="Elapsed time to reach ROOT_CAUSE state (<60s target)")
    paused_at_root_cause: bool = Field(default=False, description="True if safely paused at ROOT_CAUSE awaiting human review")
    approved_by: Optional[str] = Field(default=None, description="Identifier of human operator who approved execution")
    
    context: Optional[FindingContext] = Field(default=None, description="FindingContext populated upon resumed execution")
    trace: List[str] = Field(default_factory=list, description="Chronological record of state transitions")
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Task 45 Contract: BenchmarkThresholdAudit & DemoScenario
# ─────────────────────────────────────────────────────────────────────────────

class BenchmarkThresholdAudit(BaseModel):
    """
    Audits the 10-finding benchmark run against all 7 Stage 0 quantitative thresholds:
    1. Investigation success > 80%
    2. Reproduction success > 70%
    3. Plan success > 70%
    4. Execution/repair success > 60%
    5. False positive rate < 15%
    6. End-to-end latency < 10 min (600s)
    7. Cost < $1.00 per task
    """
    investigation_success_rate: float = Field(..., description="Actual investigation success rate (>80% required)")
    reproduction_success_rate: float = Field(..., description="Actual reproduction success rate (>70% required)")
    plan_success_rate: float = Field(..., description="Actual plan success rate (>70% required)")
    execution_success_rate: float = Field(..., description="Actual execution/repair success rate (>60% required)")
    false_positive_rate: float = Field(..., description="Actual false positive rate (<15% required)")
    e2e_latency_sec: float = Field(..., description="Average end-to-end time per task (<600s required)")
    cost_per_task_usd: float = Field(..., description="Average cost per task (<$1.00 required)")

    thresholds_met: Dict[str, bool] = Field(default_factory=dict, description="Status for each individual threshold")
    all_thresholds_met: bool = Field(default=False, description="True if ALL 7 thresholds are strictly satisfied")
    audited_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class DemoScenario(BaseModel):
    """
    Record of an individual live demonstration scenario executed during Stage 0 capstone.
    """
    scenario_id: str = Field(..., description="Unique demo scenario identifier (e.g. DEMO-01-BUG)")
    scenario_type: str = Field(..., description="Type: AUTOMATED_BUG, DEPENDENCY_UPGRADE, SECURITY_FIX, MANUAL_DRIVE")
    finding_id: str = Field(..., description="Associated finding ID")
    title: str = Field(..., description="Scenario display title")
    status: str = Field(default="SUCCESS", description="Execution status: SUCCESS or FAILED")
    duration_sec: float = Field(default=0.0, description="Duration of live scenario in seconds")
    pr_branch: Optional[str] = Field(default=None, description="Generated git branch name")
    pr_title: Optional[str] = Field(default=None, description="Generated PR title")
    summary: str = Field(default="", description="Summary of live scenario outcome")
