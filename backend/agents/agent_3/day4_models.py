"""
Purpose:
Day 4 Shared Contracts and Data Models for Engineer 3:
Tasks 40, 41, and 42 (Unified Finding Pipeline, Manual Control Layer, and Solution Memory).

Shared Contracts specified in Page 5 of Stage 0 Specification:
1. UnifiedFinding & FindingContext: Canonical finding and pipeline execution state (Task 40).
2. ManualControlCommand: Human-in-the-loop actions and override schema (Task 41).
3. MemoryRecord & ContextPack: Vector solution memory and few-shot injection context (Task 42).
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from agents.agent_3.day2_models import ValidationVerdict, RepairPlan
from agents.agent_3.day3_models import PRManifest


# ─────────────────────────────────────────────────────────────────────────────
# 1. Task 40 Contract: UnifiedFinding & FindingContext
# ─────────────────────────────────────────────────────────────────────────────

class FindingCategory(str, Enum):
    """Canonical categorization of engineering findings."""
    BUG = "BUG"
    SECURITY = "SECURITY"
    DEPENDENCY = "DEPENDENCY"


class UnifiedFinding(BaseModel):
    """
    Canonical finding input consumed by the Unified Finding Pipeline (Task 40).
    Unifies Bug, Security, and Dependency defects under one homogeneous contract.
    """
    finding_id: str = Field(..., description="Unique finding identifier (e.g. BUG-PAGINATE-01, SEC-SQLI-01)")
    category: FindingCategory = Field(..., description="Category: BUG, SECURITY, or DEPENDENCY")
    title: str = Field(..., description="Short summary of the issue")
    description: str = Field(default="", description="Detailed issue description or error trace")
    severity: str = Field(default="MEDIUM", description="Severity: LOW, MEDIUM, HIGH, CRITICAL")
    
    target_files: List[str] = Field(default_factory=list, description="Target source files implicated by finding")
    repo_id: str = Field(default="default_repo", description="Repository tenant identifier for strict isolation")
    
    # Optional category-specific metadata payload
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Auxiliary data (e.g. CVE ID, package versions)")
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class FindingContext(BaseModel):
    """
    Execution context shared across all unified pipeline stages:
    Analysis -> Planner -> Executor -> Testing -> Validation -> PR.
    """
    session_id: str = Field(..., description="Execution session identifier")
    finding: UnifiedFinding = Field(..., description="Canonical source finding being processed")
    
    diagnosis: str = Field(default="", description="Root-cause diagnostic assessment")
    suggested_fix: str = Field(default="", description="Targeted repair strategy")
    
    plan: Optional[RepairPlan] = Field(default=None, description="Active execution plan synthesized by planner")
    current_diff: str = Field(default="", description="Latest candidate unified patch diff")
    
    verdict: Optional[ValidationVerdict] = Field(default=None, description="5-Signal validation verdict")
    pr_manifest: Optional[PRManifest] = Field(default=None, description="Generated PR manifest upon successful validation")
    
    stage: str = Field(default="ANALYSIS", description="Current pipeline stage: ANALYSIS, PLANNER, EXECUTOR, TESTING, VALIDATION, PR, COMPLETE, HALTED")
    execution_trace: List[str] = Field(default_factory=list, description="Chronological log of pipeline progression")
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Task 41 Contract: ManualControlCommand & ManualControlState
# ─────────────────────────────────────────────────────────────────────────────

class ManualAction(str, Enum):
    """The 7 explicit manual actions required by Task 41 specification."""
    INVESTIGATE = "INVESTIGATE"
    REVIEW_DIAGNOSIS = "REVIEW_DIAGNOSIS"
    EDIT_PLAN = "EDIT_PLAN"
    APPROVE_EXECUTION = "APPROVE_EXECUTION"
    REVIEW_DIFF = "REVIEW_DIFF"
    RETRY = "RETRY"
    OPEN_PR = "OPEN_PR"


class ManualControlCommand(BaseModel):
    """
    Operator intervention command for Human-in-the-loop oversight (Task 41).
    Allows pausing, editing, authorizing, or aborting pipeline execution.
    """
    session_id: str = Field(..., description="Target execution session ID")
    action: ManualAction = Field(..., description="Requested manual action (1 of 7)")
    authorized: bool = Field(default=True, description="True to authorize next stage; False to pause/abort")
    
    # Overrides provided by human operator
    edited_plan: Optional[str] = Field(default=None, description="Human-edited plan text or JSON")
    edited_diff: Optional[str] = Field(default=None, description="Human-edited unified diff patch")
    notes: Optional[str] = Field(default=None, description="Operator feedback or review comments")
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Task 42 Contract: MemoryRecord & ContextPack
# ─────────────────────────────────────────────────────────────────────────────

class MemoryRecord(BaseModel):
    """
    Vector solution memory schema (Task 42).
    Encapsulates a resolved defect, root cause pattern, and verified solution.
    Strictly partitioned by repo_id to prevent cross-tenant memory bleed.
    """
    task_id: str = Field(..., description="Completed session or finding task ID")
    repo_id: str = Field(..., description="Tenant repository identifier (strict isolation boundary)")
    finding_type: str = Field(..., description="Category: BUG, SECURITY, or DEPENDENCY")
    
    root_cause_pattern: str = Field(..., description="Abstracted root cause pattern (e.g. off-by-one slice, unescaped sql)")
    solution_pattern: str = Field(..., description="Verified corrective patch or structural adjustment")
    affected_files: List[str] = Field(default_factory=list, description="Files touched by the verified resolution")
    
    outcome: str = Field(default="SUCCESS", description="Outcome: SUCCESS or FAIL")
    human_feedback: Optional[str] = Field(default=None, description="Optional human operator rating or review comment")
    
    embedding: Optional[List[float]] = Field(default=None, description="Vector embedding representation for semantic retrieval")
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class ContextPack(BaseModel):
    """
    Output of ContextBuilder (Task 42).
    Injects past retrieved solutions as few-shot context alongside repository files.
    """
    finding_id: str = Field(..., description="Target finding ID")
    repo_id: str = Field(..., description="Target repository ID")
    
    retrieved_memories: List[MemoryRecord] = Field(
        default_factory=list,
        description="Top relevant past solutions retrieved for few-shot injection"
    )
    relevant_files: List[str] = Field(default_factory=list, description="Target repository source files")
    few_shot_context: str = Field(default="", description="Formatted few-shot examples prompt text")
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
