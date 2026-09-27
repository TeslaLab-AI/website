"""
TeslaLab AI — Agent 1: Diagnosis & Foundation Lead
Module: State Models and Agent Graph Definitions (Task 1 & Task 3).
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

from app.contracts.schemas import (
    SessionState,
    FindingCategory,
    FindingSeverity,
    TaskStatus,
    Finding,
    Task,
    Session,
    AgentEvent,
)


class AgentSessionGraphState(TypedDict):
    """LangGraph state representation for the 13-state agent session graph."""
    session_id: str
    task_id: str
    workspace_id: str
    current_state: str
    history: List[Dict[str, Any]]
    error: Optional[str]


class TransitionRequest(BaseModel):
    """Payload model for session transition requests."""
    target_state: SessionState
    payload: Dict[str, Any] = Field(default_factory=dict)


class IngestionResult(BaseModel):
    """Output contract for finding ingestion."""
    task_id: str
    session_id: str
    status: str
    is_existing: bool
    db_persisted: bool = False
