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


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique UUID of the agent session")
    task_id: str = Field(..., description="Associated task UUID")
    workspace_id: str = Field(..., description="Associated workspace UUID")
    current_state: SessionState = SessionState.CREATED
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


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: str = Field(..., description="Unique UUID of the event")
    session_id: str = Field(..., description="Associated session UUID")
    from_state: SessionState
    to_state: SessionState
    event_type: str = Field(..., min_length=1)
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
