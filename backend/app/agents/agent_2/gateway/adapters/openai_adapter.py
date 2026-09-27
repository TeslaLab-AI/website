"""
OpenAI provider adapter for GPT-4o and GPT-4o-mini.
"""

from __future__ import annotations

import json
import os
from typing import Any
import httpx

from app.agents.agent_2.gateway.adapters.base import BaseLLMAdapter
from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.errors import LLMConfigurationError


class OpenAIAdapter(BaseLLMAdapter):
    """Adapter for OpenAI Chat Completions API."""

    API_URL = "https://api.openai.com/v1/chat/completions"

    SUPPORTED_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "o3-mini",
    ]

    MODEL_ALIASES = {
        "gpt-4o": "gpt-4o",
        "gpt-4o-mini": "gpt-4o-mini",
        "o3-mini": "o3-mini",
    }

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> list[str]:
        return self.SUPPORTED_MODELS

    def normalize_model_name(self, model: str) -> str:
        cleaned = model.strip().lower()
        return self.MODEL_ALIASES.get(cleaned, cleaned)

    def get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise LLMConfigurationError("OPENAI_API_KEY environment variable is missing", provider=self.provider_name)
        return key

    def _execute_completion(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
        **kwargs: Any,
    ) -> LLMResponse:
        api_key = self.get_api_key()

        api_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response_schema",
                    "strict": True,
                    "schema": json_schema,
                },
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        client = self._get_client()
        resp = client.post(self.API_URL, headers=headers, json=payload)
        resp.raise_for_status()

        data = resp.json()

        choices = data.get("choices", [])
        content_text = ""
        finish_reason = None
        if choices:
            content_text = choices[0].get("message", {}).get("content") or ""
            finish_reason = choices[0].get("finish_reason")

        raw_usage = data.get("usage", {})
        prompt_tokens = int(raw_usage.get("prompt_tokens", 0))
        completion_tokens = int(raw_usage.get("completion_tokens", 0))
        total_tokens = int(raw_usage.get("total_tokens", prompt_tokens + completion_tokens))

        usage = TokenUsage.compute(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        return LLMResponse(
            content=content_text,
            model=model,
            provider=self.provider_name,
            usage=usage,
            finish_reason=finish_reason,
        )
