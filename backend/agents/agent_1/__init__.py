"""
TeslaLab AI — Agent 1: Diagnosis & Foundation Lead
Package: backend.agents.agent_1

Responsibilities (Day 1 / Stage 0 Evaluation):
- Task 1: Contracts & Architecture Freeze (schemas, database tables, cross-language typing)
- Task 2: Finding → Task Ingestion & Idempotency Pipeline
- Task 3: 13-State Session Engine, LangGraph StateGraph, and Audit Logging
"""

from agents.agent_1.state_models import (
    AgentSessionGraphState,
    TransitionRequest,
    IngestionResult,
)
from agents.agent_1.session_engine import (
    validate_transition,
    InvalidStateTransitionError,
    PERMITTED_TRANSITIONS,
    create_session_graph,
)
from agents.agent_1.finding_ingestion import (
    FindingIngestionService,
    SEEDED_FINDINGS,
)
from agents.agent_1.diagnosis_agent import DiagnosisAgent

from agents.agent_1.event_bus import (
    AsyncEventBus,
    event_bus,
)

__all__ = [
    "DiagnosisAgent",
    "FindingIngestionService",
    "SEEDED_FINDINGS",
    "validate_transition",
    "InvalidStateTransitionError",
    "PERMITTED_TRANSITIONS",
    "create_session_graph",
    "AgentSessionGraphState",
    "TransitionRequest",
    "IngestionResult",
    "AsyncEventBus",
    "event_bus",
]

