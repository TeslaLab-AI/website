"""
TeslaLab AI — Agent 1: Diagnosis & Foundation Lead
Module: 13-State Session Engine & LangGraph StateGraph Skeleton.

Responsibilities (Task 3):
- 13-state transition engine:
  CREATED → TRIAGED → INVESTIGATING → REPRODUCING → ROOT_CAUSE → PLANNING →
  EXECUTING → TESTING → REPAIRING → PR_READY → HUMAN_REVIEW → MERGED / NEEDS_HUMAN
- LangGraph StateGraph skeleton hosting each state as an explicit graph node
- Transition validation guardrails (illegal jumps raise InvalidStateTransitionError / HTTP 400)
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from typing_extensions import TypedDict
from datetime import datetime, timezone

from app.contracts.schemas import SessionState


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state transition is attempted."""
    def __init__(self, current_state: SessionState, target_state: SessionState):
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            f"Illegal state transition from {current_state.value} to {target_state.value}."
        )


# Whitelist of permitted forward state transitions for the 13-state engine
PERMITTED_TRANSITIONS: Dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {
        SessionState.TRIAGED,
        SessionState.INVESTIGATING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.TRIAGED: {
        SessionState.INVESTIGATING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.INVESTIGATING: {
        SessionState.REPRODUCING,
        SessionState.ROOT_CAUSE,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.REPRODUCING: {
        SessionState.ROOT_CAUSE,
        SessionState.INVESTIGATING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.ROOT_CAUSE: {
        SessionState.PLANNING,
        SessionState.INVESTIGATING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.PLANNING: {
        SessionState.EXECUTING,
        SessionState.ROOT_CAUSE,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.EXECUTING: {
        SessionState.TESTING,
        SessionState.PLANNING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.TESTING: {
        SessionState.REPAIRING,
        SessionState.PR_READY,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.REPAIRING: {
        SessionState.EXECUTING,
        SessionState.TESTING,
        SessionState.PLANNING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.PR_READY: {
        SessionState.HUMAN_REVIEW,
        SessionState.REPAIRING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.HUMAN_REVIEW: {
        SessionState.MERGED,
        SessionState.REPAIRING,
        SessionState.NEEDS_HUMAN,
    },
    SessionState.MERGED: set(),       # Terminal state
    SessionState.NEEDS_HUMAN: set(),  # Terminal state
}


def validate_transition(current: SessionState, target: SessionState) -> bool:
    """
    Validates if transitioning from `current` to `target` is legal.
    Raises InvalidStateTransitionError if illegal.
    """
    allowed = PERMITTED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(current, target)
    return True


# LangGraph State & Skeleton
class AgentSessionGraphState(TypedDict):
    session_id: str
    task_id: str
    workspace_id: str
    current_state: str
    history: List[Dict[str, Any]]
    error: Optional[str]
    triage_report: Optional[Dict[str, Any]]
    root_cause_analysis: Optional[Dict[str, Any]]


def create_session_graph():
    """
    Builds the LangGraph StateGraph skeleton hosting each of the 13 states as explicit nodes.
    """
    try:
        from langgraph.graph import StateGraph, END, START
    except ImportError:
        return None

    builder: StateGraph = StateGraph(AgentSessionGraphState)  # type: ignore[arg-type]

    def _make_node(state_enum: SessionState):
        def _node_fn(state: AgentSessionGraphState) -> AgentSessionGraphState:
            now_iso = datetime.now(timezone.utc).isoformat()
            history = list(state.get("history", []))
            history.append({
                "from_state": state.get("current_state"),
                "to_state": state_enum.value,
                "timestamp": now_iso,
            })
            return {
                **state,
                "current_state": state_enum.value,
                "history": history,
            }
        return _node_fn

    for s in SessionState:
        builder.add_node(s.value, _make_node(s))

    # Entry point connects to CREATED
    builder.add_edge(START, SessionState.CREATED.value)

    # Wire forward edges
    builder.add_edge(START, SessionState.CREATED.value)
    builder.add_edge(SessionState.CREATED.value, SessionState.TRIAGED.value)
    
    def _route_after_triage(state: AgentSessionGraphState) -> str:
        triage_report = state.get("triage_report")
        if triage_report and not triage_report.get("auto_fix_feasible", True):
            return SessionState.NEEDS_HUMAN.value
        return SessionState.INVESTIGATING.value

    builder.add_conditional_edges(
        SessionState.TRIAGED.value,
        _route_after_triage,
        {
            SessionState.INVESTIGATING.value: SessionState.INVESTIGATING.value,
            SessionState.NEEDS_HUMAN.value: SessionState.NEEDS_HUMAN.value,
        }
    )
    builder.add_edge(SessionState.INVESTIGATING.value, SessionState.REPRODUCING.value)
    builder.add_edge(SessionState.REPRODUCING.value, SessionState.ROOT_CAUSE.value)
    builder.add_edge(SessionState.ROOT_CAUSE.value, SessionState.PLANNING.value)
    builder.add_edge(SessionState.PLANNING.value, SessionState.EXECUTING.value)
    builder.add_edge(SessionState.EXECUTING.value, SessionState.TESTING.value)

    # Testing branches to PR_READY or REPAIRING
    def _route_after_testing(state: AgentSessionGraphState) -> str:
        err = state.get("error")
        if err:
            return SessionState.REPAIRING.value
        return SessionState.PR_READY.value

    builder.add_conditional_edges(
        SessionState.TESTING.value,
        _route_after_testing,
        {
            SessionState.PR_READY.value: SessionState.PR_READY.value,
            SessionState.REPAIRING.value: SessionState.REPAIRING.value,
        },
    )

    builder.add_edge(SessionState.REPAIRING.value, SessionState.EXECUTING.value)
    builder.add_edge(SessionState.PR_READY.value, SessionState.HUMAN_REVIEW.value)
    builder.add_edge(SessionState.HUMAN_REVIEW.value, SessionState.MERGED.value)

    # Terminal states
    builder.add_edge(SessionState.MERGED.value, END)
    builder.add_edge(SessionState.NEEDS_HUMAN.value, END)

    return builder.compile()
