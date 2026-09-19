"""
LLM Gateway.
Provides a unified interface complete(...) for calling Anthropic, OpenAI, DeepSeek,
and Google Gemini with automatic retry (max 3, exponential backoff), fallback routing,
error normalization, and telemetry recording.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Sequence
from pydantic import BaseModel

from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse
from app.agents.agent_2.gateway.errors import (
    LLMError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMServerError,
    LLMProviderUnavailableError,
)
from app.agents.agent_2.gateway.adapters.base import BaseLLMAdapter
from app.agents.agent_2.gateway.adapters.anthropic_adapter import AnthropicAdapter
from app.agents.agent_2.gateway.adapters.openai_adapter import OpenAIAdapter
from app.agents.agent_2.gateway.adapters.deepseek_adapter import DeepSeekAdapter
from app.agents.agent_2.gateway.adapters.gemini_adapter import GeminiAdapter
from app.agents.agent_2.gateway.telemetry import GatewayTelemetry, default_telemetry

logger = logging.getLogger("llm_gateway")


class LLMGateway:
    """
    Unified LLM Gateway interface.
    Routes requests to appropriate provider adapters with resilience policies.
    """

    # Default fallback routes when primary model persistently fails
    DEFAULT_FALLBACK_MAP = {
        "claude-3-5-sonnet": "gpt-4o",
        "claude-3-5-sonnet-20241022": "gpt-4o",
        "claude-3-5-sonnet-latest": "gpt-4o",
        "claude-3-5-haiku": "gpt-4o-mini",
        "claude-3-5-haiku-20241022": "gpt-4o-mini",
        "claude-3-5-haiku-latest": "gpt-4o-mini",
        "gpt-4o": "gemini-1.5-pro",
        "gpt-4o-mini": "gemini-1.5-flash",
        "deepseek-v3": "gpt-4o-mini",
        "deepseek-chat": "gpt-4o-mini",
        "deepseek-r1": "claude-3-5-sonnet",
        "deepseek-reasoner": "claude-3-5-sonnet",
        "gemini-1.5-pro": "gpt-4o",
        "gemini-pro": "gpt-4o",
        "gemini-1.5-flash": "gpt-4o-mini",
        "gemini-flash": "gpt-4o-mini",
    }

    def __init__(
        self,
        adapters: list[BaseLLMAdapter] | None = None,
        telemetry: GatewayTelemetry | None = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        sleep_fn: Callable[[float], None] | None = None,
        fallback_map: dict[str, str] | None = None,
    ) -> None:
        self.telemetry = telemetry or default_telemetry
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.sleep_fn = sleep_fn or time.sleep
        self.fallback_map = fallback_map if fallback_map is not None else dict(self.DEFAULT_FALLBACK_MAP)

        self._adapters: dict[str, BaseLLMAdapter] = {}
        if adapters:
            for adp in adapters:
                self.register_adapter(adp)
        else:
            self.register_adapter(AnthropicAdapter())
            self.register_adapter(OpenAIAdapter())
            self.register_adapter(DeepSeekAdapter())
            self.register_adapter(GeminiAdapter())

    def register_adapter(self, adapter: BaseLLMAdapter) -> None:
        """Register a provider adapter."""
        self._adapters[adapter.provider_name.lower()] = adapter

    def get_adapter_for_model(self, model: str) -> BaseLLMAdapter:
        """Find the matching provider adapter for a requested model."""
        clean_model = model.strip()
        for adapter in self._adapters.values():
            if adapter.supports_model(clean_model):
                return adapter
        raise LLMInvalidRequestError(
            f"No provider adapter registered for model '{model}'. "
            f"Supported models: {[m for a in self._adapters.values() for m in a.supported_models]}",
            provider="gateway",
            model=model,
        )

    def _is_retryable_error(self, exc: Exception) -> bool:
        """Determine if an exception is considered a retryable rate-limit/server error."""
        if isinstance(exc, (LLMRateLimitError, LLMServerError, LLMProviderUnavailableError)):
            return True
        if isinstance(exc, LLMError):
            return exc.retryable or (exc.status_code in (429, 500, 502, 503, 504))
        return False

    def complete(
        self,
        messages: Sequence[dict[str, Any] | LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
        fallback_model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Execute completion across providers with retries, fallback, and telemetry.

        Args:
            messages: List of message dicts or LLMMessage objects
            model: Target model name (e.g. 'gpt-4o', 'claude-3-5-sonnet', 'deepseek-v3', 'gemini-1.5-pro')
            temperature: Sampling temperature
            max_tokens: Max output tokens
            json_schema: Optional JSON schema dictionary or Pydantic model class
            fallback_model: Explicit fallback model to use if primary persistently fails
            **kwargs: Extra arguments passed to adapter
        """
        primary_adapter = self.get_adapter_for_model(model)
        primary_provider = primary_adapter.provider_name

        total_attempts = 0
        last_exception: LLMError | None = None
        start_time = time.perf_counter()

        # Primary execution loop: 1 initial attempt + up to self.max_retries retries
        while total_attempts <= self.max_retries:
            total_attempts += 1
            try:
                response = primary_adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_schema=json_schema,
                    **kwargs,
                )

                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                self.telemetry.record(
                    model=response.model,
                    provider=response.provider,
                    latency_ms=elapsed_ms,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.total_tokens,
                    attempts=total_attempts,
                    fallback_triggered=False,
                    success=True,
                )
                return response

            except Exception as exc:
                if isinstance(exc, LLMError):
                    norm_exc = exc
                else:
                    norm_exc = LLMError(str(exc), provider=primary_provider, retryable=False, model=model)

                last_exception = norm_exc

                if not self._is_retryable_error(norm_exc) or total_attempts > self.max_retries:
                    logger.warning(
                        "LLMGateway primary failed on attempt %d/%d (model=%s): %s",
                        total_attempts,
                        self.max_retries + 1,
                        model,
                        norm_exc,
                    )
                    break

                # Exponential backoff: backoff_factor * 2^(attempt - 1)
                backoff = self.backoff_factor * (2 ** (total_attempts - 1))
                logger.info(
                    "LLMGateway retryable failure (attempt %d/%d, sleeping %.2fs, model=%s): %s",
                    total_attempts,
                    self.max_retries + 1,
                    backoff,
                    model,
                    norm_exc,
                )
                if backoff > 0:
                    self.sleep_fn(backoff)

        # Persistent failure reached on primary model. Evaluate fallback for retryable failures.
        if last_exception and self._is_retryable_error(last_exception):
            target_fallback = fallback_model or self.fallback_map.get(model.strip().lower())
            if target_fallback and target_fallback.strip().lower() != model.strip().lower():
                logger.warning(
                    "LLMGateway: Primary model '%s' persistently failed after %d attempts. Attempting fallback to '%s'",
                    model,
                    total_attempts,
                    target_fallback,
                )
                try:
                    fallback_adapter = self.get_adapter_for_model(target_fallback)
                    fb_response = fallback_adapter.complete(
                        messages=messages,
                        model=target_fallback,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_schema=json_schema,
                        **kwargs,
                    )

                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    self.telemetry.record(
                        model=fb_response.model,
                        provider=fb_response.provider,
                        latency_ms=elapsed_ms,
                        prompt_tokens=fb_response.prompt_tokens,
                        completion_tokens=fb_response.completion_tokens,
                        total_tokens=fb_response.total_tokens,
                        attempts=total_attempts + 1,
                        fallback_triggered=True,
                        success=True,
                    )
                    return fb_response

                except Exception as fb_exc:
                    logger.error("LLMGateway: Fallback model '%s' also failed: %s", target_fallback, fb_exc)
                    if isinstance(fb_exc, LLMError):
                        raise fb_exc
                    raise LLMError(
                        f"Fallback model '{target_fallback}' failed after primary failure: {fb_exc}",
                        provider="gateway",
                        model=target_fallback,
                    ) from fb_exc

        # Record failed telemetry before raising
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        self.telemetry.record(
            model=model,
            provider=primary_provider,
            latency_ms=elapsed_ms,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            attempts=total_attempts,
            fallback_triggered=False,
            success=False,
            error_type=type(last_exception).__name__ if last_exception else "UnknownError",
        )

        if last_exception is not None:
            raise last_exception
        raise LLMError("Unknown LLM execution failure", provider="gateway", model=model)


# Default global gateway instance
default_gateway = LLMGateway()


def complete(
    messages: Sequence[dict[str, Any] | LLMMessage],
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    json_schema: dict[str, Any] | type[BaseModel] | None = None,
    fallback_model: str | None = None,
    **kwargs: Any,
) -> LLMResponse:
    """
    Common LLM Gateway call interface.
    Delegates to default_gateway.
    """
    return default_gateway.complete(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        json_schema=json_schema,
        fallback_model=fallback_model,
        **kwargs,
    )
