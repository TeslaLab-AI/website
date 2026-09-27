"""
TeslaLab AI — Session Engine Bridge for app.agents.agent_1.
"""

try:
    from backend.agents.agent_1.session_engine import (
        InvalidStateTransitionError,
        PERMITTED_TRANSITIONS,
        validate_transition,
        AgentSessionGraphState,
        create_session_graph,
    )
except (ImportError, ModuleNotFoundError):
    from agents.agent_1.session_engine import (
        InvalidStateTransitionError,
        PERMITTED_TRANSITIONS,
        validate_transition,
        AgentSessionGraphState,
        create_session_graph,
    )

__all__ = [
    "InvalidStateTransitionError",
    "PERMITTED_TRANSITIONS",
    "validate_transition",
    "AgentSessionGraphState",
    "create_session_graph",
]
