"""
Model Router package for Engineer 2 (Agent 2).
Provides task-aware routing across Fast, Strong, and Reasoning LLM model tiers.
"""

from app.agents.agent_2.router.models import (
    ModelTier,
    TierConfig,
    TaskRule,
    RouterConfig,
    ModelRoute,
)
from app.agents.agent_2.router.router import (
    ModelRouter,
    default_router,
    get_model_for_task,
)

__all__ = [
    "ModelTier",
    "TierConfig",
    "TaskRule",
    "RouterConfig",
    "ModelRoute",
    "ModelRouter",
    "default_router",
    "get_model_for_task",
]
