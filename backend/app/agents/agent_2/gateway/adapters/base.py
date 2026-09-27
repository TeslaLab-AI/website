"""
Base adapter interface for LLM providers.
Defines contracts and normalization utilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import time
from typing import Any, Sequence
import httpx
from pydantic import BaseModel

from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.errors import (
    LLMError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    normalize_http_status_error,
)


class BaseLLMAdapter(ABC):
    """Abstract base class for provider-specific LLM adapters."""

    def __init__(
        self,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._timeout = timeout

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'anthropic', 'openai', 'deepseek', 'gemini')."""
        ...

    @property
    @abstractmethod
    def supported_models(self) -> list[str]:
        """List of model identifiers or aliases supported by this adapter."""
        ...

    def supports_model(self, model: str) -> bool:
        """Check if this adapter supports the requested model."""
        target = model.strip().lower()
        return any(target == m.lower() or target.startswith(m.lower()) for m in self.supported_models)

    def normalize_model_name(self, model: str) -> str:
        """Map aliases to official model string."""
        return model.strip()

    @abstractmethod
    def get_api_key(self) -> str:
        """Retrieve API key from config or environment. Must raise LLMConfigurationError if absent."""
        ...

    def _get_client(self) -> httpx.Client:
        """Return injected client or new standard client."""
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=self._timeout)

    @staticmethod
    def normalize_messages(messages: Sequence[dict[str, Any] | LLMMessage]) -> list[LLMMessage]:
        """Validate and standardize input messages into a list of LLMMessage objects."""
        if not messages:
            raise LLMInvalidRequestError("Messages list cannot be empty", provider="gateway")

        normalized: list[LLMMessage] = []
        for msg in messages:
            if isinstance(msg, LLMMessage):
                normalized.append(msg)
            elif isinstance(msg, dict):
                normalized.append(LLMMessage(role=msg["role"], content=str(msg["content"])))
            else:
                raise LLMInvalidRequestError(f"Unsupported message type: {type(msg)}", provider="gateway")
        return normalized

    @staticmethod
    def extract_schema_dict(json_schema: dict[str, Any] | type[BaseModel] | None) -> dict[str, Any] | None:
        """Extract dictionary representation of JSON schema."""
        if json_schema is None:
            return None
        if isinstance(json_schema, type) and issubclass(json_schema, BaseModel):
            return json_schema.model_json_schema()
        if isinstance(json_schema, dict):
            return json_schema
        raise LLMInvalidRequestError("json_schema must be a dict or Pydantic BaseModel class", provider="gateway")

    def complete(
        self,
        messages: Sequence[dict[str, Any] | LLMMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Execute completion with execution timing and error normalization.
        Calls _execute_completion internally.
        """
        norm_messages = self.normalize_messages(messages)
        norm_model = self.normalize_model_name(model)
        schema_dict = self.extract_schema_dict(json_schema)

        start_time = time.perf_counter()
        try:
            response = self._execute_completion(
                messages=norm_messages,
                model=norm_model,
                temperature=temperature,
                max_tokens=max_tokens,
                json_schema=schema_dict,
                **kwargs,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            response.latency_ms = round(elapsed_ms, 2)

            # If json_schema was requested and response not yet parsed, attempt parse
            if schema_dict is not None and response.parsed is None:
                try:
                    response.parsed = json.loads(response.content)
                except Exception:
                    response.parsed = None

            return response

        except httpx.HTTPStatusError as exc:
            raise normalize_http_status_error(
                provider=self.provider_name,
                status_code=exc.response.status_code,
                error_text=exc.response.text,
                model=norm_model,
            ) from None
        except httpx.RequestError as exc:
            raise LLMProviderUnavailableError(
                f"Network/transport failure communicating with {self.provider_name}: {exc}",
                provider=self.provider_name,
                model=norm_model,
            ) from None
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"Unexpected error in {self.provider_name} adapter: {exc}",
                provider=self.provider_name,
                model=norm_model,
            ) from None

    @abstractmethod
    def _execute_completion(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Provider-specific call logic. Must return LLMResponse with raw response shielded."""
        ...
