"""
TeslaLab AI — State Models Bridge for app.agents.agent_1.
"""

try:
    from backend.agents.agent_1.state_models import (
        AgentSessionGraphState,
        TransitionRequest,
        IngestionResult,
    )
except (ImportError, ModuleNotFoundError):
    from agents.agent_1.state_models import (
        AgentSessionGraphState,
        TransitionRequest,
        IngestionResult,
    )

__all__ = [
    "AgentSessionGraphState",
    "TransitionRequest",
    "IngestionResult",
]
