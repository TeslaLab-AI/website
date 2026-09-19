"""
Unified data models for LLM Gateway.
Provides standardized request and response structures used across all provider adapters.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    """Standardized chat message input."""
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant"] = Field(..., description="Message author role")
    content: str = Field(..., description="Message text content")


class TokenUsage(BaseModel):
    """Standardized token consumption metrics."""
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0, description="Tokens in input prompt")
    completion_tokens: int = Field(default=0, ge=0, description="Tokens in model output")
    total_tokens: int = Field(default=0, ge=0, description="Total tokens consumed")

    @classmethod
    def compute(cls, prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int | None = None) -> TokenUsage:
        tot = total_tokens if total_tokens is not None else (prompt_tokens + completion_tokens)
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=tot,
        )


class LLMResponse(BaseModel):
    """
    Standardized response returned by all provider adapters and LLM Gateway.
    Guarantees raw provider objects do not leak outside adapter layer.
    """
    model_config = ConfigDict(extra="ignore")

    content: str = Field(..., description="Generated text content from the LLM")
    model: str = Field(..., description="Normalized model identifier used")
    provider: str = Field(..., description="Underlying provider name (anthropic, openai, deepseek, gemini)")
    usage: TokenUsage = Field(default_factory=TokenUsage, description="Token usage statistics")
    latency_ms: float = Field(default=0.0, ge=0.0, description="Execution latency in milliseconds")
    finish_reason: str | None = Field(default=None, description="Reason model stopped generating (stop, length, etc.)")
    parsed: Any | None = Field(default=None, description="Structured parsed content if json_schema was requested")

    @property
    def prompt_tokens(self) -> int:
        return self.usage.prompt_tokens

    @property
    def completion_tokens(self) -> int:
        return self.usage.completion_tokens

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def latency(self) -> float:
        """Latency in seconds for convenience."""
        return self.latency_ms / 1000.0
