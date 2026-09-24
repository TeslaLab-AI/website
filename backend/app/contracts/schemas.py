"""
Purpose:
Frozen Day 1 Data Contracts for TeslaLab AI Stage 0.
Shared between Engineer 1 (Diagnosis), Engineer 2 (Planning), and Engineer 3 (Verification).

Contracts:
- Finding
- Task
- Session
- PlanSkeleton
- ToolCall
- AgentEvent
"""

from __future__ import annotations
from enum import Enum
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class FindingCategory(str, Enum):
    BUGS = "bugs"
    DEPENDENCIES = "dependencies"
    SECURITY = "security"
    TESTING = "testing"


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

class TriageSeverity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

class TriageReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    is_reproducible: bool = Field(..., description="Whether the bug has enough info to be reproducible")
    subsystem: str = Field(..., description="The subsystem this bug belongs to (e.g., auth, database, frontend)")
    severity: TriageSeverity
    estimated_complexity: str = Field(..., description="Estimation of complexity (e.g., low, medium, high)")
    auto_fix_feasible: bool = Field(..., description="Whether autonomous fixing is feasible")
    reason: str = Field(..., description="Reasoning for feasibility and severity")

class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mechanism: str = Field(..., description="The technical theory or mechanism.")
    supporting_evidence: List[str] = Field(default_factory=list, description="Specific lines or snippets supporting this theory.")
    contradicting_evidence: List[str] = Field(default_factory=list, description="Specific lines or snippets that cast doubt on this theory.")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in this hypothesis (0.0 to 1.0).")

class GitContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    introducing_commit: str = Field(..., description="The git commit SHA that introduced the culprit lines")
    author: str = Field(..., description="Author of the introducing commit")
    date: str = Field(..., description="Date of the introducing commit")
    commit_message: str = Field(..., description="Original commit message")
    original_intent_summary: str = Field(..., description="1-sentence LLM summary of the original developer intent based on the diff and message")

class RootCauseAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    # Required by Agent 2 (Planner)
    finding_id: str = Field(..., description="Unique ID of the finding or issue")
    title: str = Field(..., description="Short summary/title of the issue")
    description: str = Field(..., description="Detailed description of the issue")
    file_path: str = Field(..., description="Target file path in repository (culprit_file)")
    line_number: int = Field(default=1, ge=1, description="Primary line number of the issue")
    root_cause: str = Field(..., description="Root cause explanation")
    suggested_fix: str = Field(..., description="High-level fix strategy")
    severity: str = Field(default="Medium", description="Severity level: Low, Medium, High, Critical")
    cwe: Optional[str] = Field(default=None, description="Optional CWE identifier")
    
    # Required by Task 11 (Root Cause Agent v1)
    mechanism: str = Field(..., description="Technical mechanism of the defect (from the winning hypothesis)")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in this diagnosis")
    evidence_references: List[str] = Field(default_factory=list, description="Specific lines or snippets cited as evidence")
    hypothesis_tree: List[Hypothesis] = Field(default_factory=list, description="List of generated hypotheses before selecting the winner.")
    
    # Task 13 (Git History Intelligence)
    git_context: Optional[GitContext] = Field(default=None, description="Historical context of the culprit code")

class ReproductionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script_code: str = Field(..., description="The generated Python (pytest) test code that reproduces the bug")
    execution_log: str = Field(..., description="The stdout/stderr from executing the test in the sandbox")
    exit_code: int = Field(..., description="The exit code of the test execution")
    is_verified_failure: bool = Field(..., description="True if the test cleanly failed with the expected error")

class SessionState(str, Enum):
    CREATED = "CREATED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    REPRODUCING = "REPRODUCING"
    ROOT_CAUSE = "ROOT_CAUSE"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    TESTING = "TESTING"
    REPAIRING = "REPAIRING"
    PR_READY = "PR_READY"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    MERGED = "MERGED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique finding ID or code (e.g. FINDING-BUG-001 or UUID)")
    category: FindingCategory
    severity: FindingSeverity
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BugFinding(BaseModel):
    """Normalized schema for intake from Sentry, GitHub, and LLM extraction"""
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique ID for the bug (e.g. sentry-id, github-issue-id)")
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    stack_trace: Optional[str] = Field(default=None, description="Full stringified stack trace if available")
    files_hint: List[str] = Field(default_factory=list, description="List of exact file paths implicated in the crash or reproduction")
    environment: Dict[str, Any] = Field(default_factory=dict, description="Metadata tags, breadcrumbs, OS version, etc")


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique UUID of the task")
    workspace_id: str = Field(..., description="Associated workspace UUID")
    finding_id: str = Field(..., description="Referenced finding identifier")
    title: str = Field(..., min_length=1)
    category: FindingCategory
    severity: FindingSeverity
    status: TaskStatus = TaskStatus.OPEN
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    stack_trace: Optional[str] = Field(default=None, description="Stack trace related to the finding")
    logs: List[str] = Field(default_factory=list, description="Relevant log lines (±50 lines around error)")
    environment: Dict[str, Any] = Field(default_factory=dict, description="Environment metadata (Python/Node version, OS)")
    commit_hash: str = Field(..., description="Git commit hash at time of error")

class CodeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    file_path: str = Field(..., description="Path to the source file")
    function_name: Optional[str] = Field(default=None, description="Name of the function or class block")
    content: str = Field(..., description="Source code content")
    start_line: int = Field(..., description="Starting line number (1-indexed)")
    end_line: int = Field(..., description="Ending line number (1-indexed)")
    relevance_score: float = Field(default=0.0, description="Heuristic relevance score (higher is better)")

class ContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    chunks: List[CodeChunk] = Field(default_factory=list, description="Most relevant code chunks within token budget")
    total_tokens: int = Field(default=0, description="Total tokens consumed by the context pack")


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique UUID of the agent session")
    task_id: str = Field(..., description="Associated task UUID")
    workspace_id: str = Field(..., description="Associated workspace UUID")
    current_state: SessionState = SessionState.CREATED
    evidence_pack: Optional[EvidencePack] = Field(default=None, description="Collected raw evidence")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    step_index: int = Field(..., ge=0)
    tool_name: str = Field(..., min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    expected_output: Optional[str] = None


class PlanSkeleton(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique UUID of the plan")
    session_id: str = Field(..., description="Associated session UUID")
    task_id: str = Field(..., description="Associated task UUID")
    version: int = Field(default=1, ge=1)
    status: str = Field(default="draft")
    steps: List[ToolCall] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentEventType(str, Enum):
    SESSION_STARTED = "SESSION_STARTED"
    SEARCHING_REPOSITORY = "SEARCHING_REPOSITORY"
    READING_FILE = "READING_FILE"
    HYPOTHESIS_GENERATED = "HYPOTHESIS_GENERATED"
    PLAN_CREATED = "PLAN_CREATED"
    CODE_MODIFIED = "CODE_MODIFIED"
    TESTS_RUNNING = "TESTS_RUNNING"
    PR_OPENED = "PR_OPENED"
    STATE_TRANSITION = "state_transition"


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique UUID of the event")
    session_id: str = Field(..., description="Associated session UUID")
    from_state: SessionState = Field(default=SessionState.INVESTIGATING)
    to_state: SessionState = Field(default=SessionState.INVESTIGATING)
    event_type: str = Field(..., min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

