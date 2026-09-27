"""
Centralized LLM Pricing Configuration.
Maintains token pricing rates for all supported providers and models.
Rates are defined per-token (in USD) with helper conversions from standard per-1M token rates.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ModelPricing(BaseModel):
    """Token pricing specification for a single model."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    model: str = Field(..., description="Canonical model identifier")
    provider: str = Field(..., description="Provider name (anthropic, openai, deepseek, gemini)")
    prompt_rate_per_token: float = Field(..., ge=0.0, description="USD cost per input prompt token")
    completion_rate_per_token: float = Field(..., ge=0.0, description="USD cost per generated completion token")
    cached_prompt_rate_per_token: float = Field(default=0.0, ge=0.0, description="USD cost per cached input token")

    @classmethod
    def from_per_million(
        cls,
        model: str,
        provider: str,
        prompt_per_m: float,
        completion_per_m: float,
        cached_per_m: float = 0.0,
    ) -> ModelPricing:
        """Construct ModelPricing from standard per-million-token USD prices."""
        return cls(
            model=model.strip().lower(),
            provider=provider.strip().lower(),
            prompt_rate_per_token=prompt_per_m / 1_000_000.0,
            completion_rate_per_token=completion_per_m / 1_000_000.0,
            cached_prompt_rate_per_token=cached_per_m / 1_000_000.0,
        )

    @property
    def prompt_rate_per_1k(self) -> float:
        return self.prompt_rate_per_token * 1_000.0

    @property
    def completion_rate_per_1k(self) -> float:
        return self.completion_rate_per_token * 1_000.0

    @property
    def cached_rate_per_1k(self) -> float:
        return self.cached_prompt_rate_per_token * 1_000.0


# Standard industry pricing per 1,000,000 tokens (USD)
DEFAULT_PRICING_TABLE: list[ModelPricing] = [
    # --- OpenAI ---
    ModelPricing.from_per_million(
        model="gpt-4o",
        provider="openai",
        prompt_per_m=2.50,
        completion_per_m=10.00,
        cached_per_m=1.25,
    ),
    ModelPricing.from_per_million(
        model="gpt-4o-mini",
        provider="openai",
        prompt_per_m=0.15,
        completion_per_m=0.60,
        cached_per_m=0.075,
    ),
    ModelPricing.from_per_million(
        model="o3-mini",
        provider="openai",
        prompt_per_m=1.10,
        completion_per_m=4.40,
        cached_per_m=0.55,
    ),
    # --- Anthropic ---
    ModelPricing.from_per_million(
        model="claude-3-5-sonnet",
        provider="anthropic",
        prompt_per_m=3.00,
        completion_per_m=15.00,
        cached_per_m=0.30,
    ),
    ModelPricing.from_per_million(
        model="claude-3-5-sonnet-20241022",
        provider="anthropic",
        prompt_per_m=3.00,
        completion_per_m=15.00,
        cached_per_m=0.30,
    ),
    ModelPricing.from_per_million(
        model="claude-3-5-haiku",
        provider="anthropic",
        prompt_per_m=0.80,
        completion_per_m=4.00,
        cached_per_m=0.08,
    ),
    ModelPricing.from_per_million(
        model="claude-3-5-haiku-20241022",
        provider="anthropic",
        prompt_per_m=0.80,
        completion_per_m=4.00,
        cached_per_m=0.08,
    ),
    # --- DeepSeek ---
    ModelPricing.from_per_million(
        model="deepseek-v3",
        provider="deepseek",
        prompt_per_m=0.14,
        completion_per_m=0.28,
        cached_per_m=0.014,
    ),
    ModelPricing.from_per_million(
        model="deepseek-chat",
        provider="deepseek",
        prompt_per_m=0.14,
        completion_per_m=0.28,
        cached_per_m=0.014,
    ),
    ModelPricing.from_per_million(
        model="deepseek-r1",
        provider="deepseek",
        prompt_per_m=0.55,
        completion_per_m=2.19,
        cached_per_m=0.14,
    ),
    ModelPricing.from_per_million(
        model="deepseek-reasoner",
        provider="deepseek",
        prompt_per_m=0.55,
        completion_per_m=2.19,
        cached_per_m=0.14,
    ),
    # --- Google Gemini ---
    ModelPricing.from_per_million(
        model="gemini-1.5-pro",
        provider="gemini",
        prompt_per_m=1.25,
        completion_per_m=5.00,
        cached_per_m=0.3125,
    ),
    ModelPricing.from_per_million(
        model="gemini-pro",
        provider="gemini",
        prompt_per_m=1.25,
        completion_per_m=5.00,
        cached_per_m=0.3125,
    ),
    ModelPricing.from_per_million(
        model="gemini-1.5-flash",
        provider="gemini",
        prompt_per_m=0.075,
        completion_per_m=0.30,
        cached_per_m=0.01875,
    ),
    ModelPricing.from_per_million(
        model="gemini-flash",
        provider="gemini",
        prompt_per_m=0.075,
        completion_per_m=0.30,
        cached_per_m=0.01875,
    ),
]


class PricingRegistry:
    """Registry maintaining pricing configurations across models."""

    def __init__(self, initial_pricings: list[ModelPricing] | None = None) -> None:
        self._pricing_map: dict[str, ModelPricing] = {}
        for p in (initial_pricings or DEFAULT_PRICING_TABLE):
            self.register(p)

    def register(self, pricing: ModelPricing) -> None:
        """Register or override pricing for a model."""
        self._pricing_map[pricing.model.strip().lower()] = pricing

    def get(self, model: str) -> ModelPricing:
        """Retrieve pricing for a model identifier, matching normalized aliases."""
        clean_name = model.strip().lower()
        if clean_name in self._pricing_map:
            return self._pricing_map[clean_name]

        # Check prefix/suffix alias matches
        for key, pricing in self._pricing_map.items():
            if key in clean_name or clean_name in key:
                return pricing

        raise KeyError(
            f"No pricing configured for model '{model}'. "
            f"Known models: {sorted(list(self._pricing_map.keys()))}"
        )

    def is_known(self, model: str) -> bool:
        """Check if pricing is registered for the specified model."""
        try:
            self.get(model)
            return True
        except KeyError:
            return False

    def list_all(self) -> dict[str, ModelPricing]:
        """Return all registered model pricings."""
        return dict(self._pricing_map)


# Global default pricing registry singleton
default_pricing_registry = PricingRegistry()
