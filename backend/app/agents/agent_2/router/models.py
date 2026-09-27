"""
Data models for Model Router v1.
Defines model tiers, routing configurations, and routing decision objects.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ModelTier(str, Enum):
    """Supported model capability and cost tiers."""
    FAST = "fast"
    STRONG = "strong"
    REASONING = "reasoning"


class TierConfig(BaseModel):
    """Configuration for a specific model tier."""
    model_config = ConfigDict(extra="ignore")

    primary_model: str = Field(..., description="Default model selected for this tier")
    provider: str | None = Field(default=None, description="Optional explicit provider identifier")
    fallback_model: str | None = Field(default=None, description="Tier-level fallback model")
    allowed_models: list[str] = Field(default_factory=list, description="All allowed models in this tier")


class TaskRule(BaseModel):
    """Routing rule mapped to a specific task type."""
    model_config = ConfigDict(extra="ignore")

    tier: str = Field(..., description="Target model tier (fast, strong, reasoning)")
    override_model: str | None = Field(default=None, description="Optional direct model override for this task")


class RouterConfig(BaseModel):
    """Complete configuration-driven routing table."""
    model_config = ConfigDict(extra="ignore")

    default_tier: str = Field(default="strong", description="Fallback tier when task type is unknown")
    tiers: dict[str, TierConfig] = Field(..., description="Tier specifications (fast, strong, reasoning)")
    task_rules: dict[str, TaskRule] = Field(..., description="Task type to tier mappings")
    complexity_escalations: dict[str, str] = Field(
        default_factory=lambda: {
            "high": "reasoning",
            "complex": "reasoning",
            "critical": "reasoning",
        },
        description="Complexity hints that escalate task tier",
    )


class ModelRoute(BaseModel):
    """The resolved model routing decision for a given task."""
    model_config = ConfigDict(extra="ignore")

    task_type: str = Field(..., description="Requested task type")
    tier: str = Field(..., description="Selected capability tier (fast, strong, reasoning)")
    model: str = Field(..., description="Selected primary model")
    provider: str = Field(..., description="Selected provider (openai, anthropic, deepseek, gemini)")
    fallback_model: str | None = Field(default=None, description="Recommended fallback model")
    is_override: bool = Field(default=False, description="Whether this route resulted from a runtime tier override")
    reason: str = Field(default="", description="Explanation for routing resolution")
