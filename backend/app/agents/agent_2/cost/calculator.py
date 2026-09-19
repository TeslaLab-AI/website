"""
Deterministic LLM Cost Calculator.
Calculates prompt, completion, and cached token costs using centralized model pricing.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_2.cost.pricing import (
    ModelPricing,
    PricingRegistry,
    default_pricing_registry,
)


class CostBreakdown(BaseModel):
    """Detailed financial breakdown for a single LLM invocation."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    model: str = Field(..., description="Canonical model used")
    provider: str = Field(..., description="LLM provider name")
    prompt_tokens: int = Field(default=0, ge=0, description="Input/prompt token count")
    completion_tokens: int = Field(default=0, ge=0, description="Output/completion token count")
    cached_tokens: int = Field(default=0, ge=0, description="Cached prompt token count")
    total_tokens: int = Field(default=0, ge=0, description="Sum of prompt and completion tokens")

    prompt_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost for prompt tokens in USD")
    completion_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost for completion tokens in USD")
    cached_cost_usd: float = Field(default=0.0, ge=0.0, description="Cost for cached tokens in USD")
    total_cost_usd: float = Field(default=0.0, ge=0.0, description="Total cost of call in USD")

    @property
    def cost_usd(self) -> float:
        """Alias for total_cost_usd for convenience."""
        return self.total_cost_usd


class CostCalculator:
    """
    Deterministic cost calculator for LLM invocations.
    Computes exact USD expenditure per call based on token counts and model pricing.
    """

    def __init__(self, registry: PricingRegistry | None = None) -> None:
        self.registry = registry or default_pricing_registry

    def calculate_cost(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        provider: str | None = None,
    ) -> CostBreakdown:
        """
        Calculate the precise dollar cost for an LLM call.

        Formula:
            prompt_cost = (prompt_tokens - cached_tokens) * prompt_rate
            cached_cost = cached_tokens * cached_rate
            completion_cost = completion_tokens * completion_rate
            total_cost = prompt_cost + cached_cost + completion_cost
        """
        if prompt_tokens < 0 or completion_tokens < 0 or cached_tokens < 0:
            raise ValueError("Token counts cannot be negative.")

        if cached_tokens > prompt_tokens:
            raise ValueError(
                f"cached_tokens ({cached_tokens}) cannot exceed prompt_tokens ({prompt_tokens})"
            )

        pricing = self.registry.get(model)
        resolved_provider = provider or pricing.provider

        uncached_prompt = prompt_tokens - cached_tokens
        prompt_cost = uncached_prompt * pricing.prompt_rate_per_token
        cached_cost = cached_tokens * pricing.cached_prompt_rate_per_token
        completion_cost = completion_tokens * pricing.completion_rate_per_token

        total_cost = prompt_cost + cached_cost + completion_cost
        total_tokens = prompt_tokens + completion_tokens

        # Round to 8 decimal places to eliminate floating point imprecision
        return CostBreakdown(
            model=pricing.model,
            provider=resolved_provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens,
            prompt_cost_usd=round(prompt_cost, 8),
            completion_cost_usd=round(completion_cost, 8),
            cached_cost_usd=round(cached_cost, 8),
            total_cost_usd=round(total_cost, 8),
        )

    def calculate_for_usage(
        self,
        model: str,
        usage: Any,
        provider: str | None = None,
    ) -> CostBreakdown:
        """Helper to calculate cost directly from TokenUsage or dict."""
        prompt_tokens = getattr(usage, "prompt_tokens", 0)
        completion_tokens = getattr(usage, "completion_tokens", 0)
        cached_tokens = getattr(usage, "cached_tokens", 0)

        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            cached_tokens = usage.get("cached_tokens", 0)

        return self.calculate_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            provider=provider,
        )


# Global default cost calculator singleton
default_calculator = CostCalculator()
