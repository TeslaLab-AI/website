"""
Anthropic provider adapter for Claude 3.5 Sonnet and Claude 3.5 Haiku.
"""

from __future__ import annotations

import json
import os
from typing import Any
import httpx

from app.agents.agent_2.gateway.adapters.base import BaseLLMAdapter
from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.errors import LLMConfigurationError, LLMError


class AnthropicAdapter(BaseLLMAdapter):
    """Adapter for Anthropic Claude API."""

    API_URL = "https://api.anthropic.com/v1/messages"
    DEFAULT_API_VERSION = "2023-06-01"

    SUPPORTED_MODELS = [
        "claude-3-5-sonnet",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku",
        "claude-3-5-haiku-20241022",
        "claude-3-5-haiku-latest",
    ]

    MODEL_ALIASES = {
        "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku": "claude-3-5-haiku-20241022",
    }

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def supported_models(self) -> list[str]:
        return self.SUPPORTED_MODELS

    def normalize_model_name(self, model: str) -> str:
        cleaned = model.strip().lower()
        return self.MODEL_ALIASES.get(cleaned, cleaned)

    def get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY environment variable is missing", provider=self.provider_name)
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

        # Separate system messages from user/assistant messages
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})

        if not anthropic_messages:
            anthropic_messages.append({"role": "user", "content": "Hello"})

        if json_schema:
            schema_instruction = (
                f"\n\nYou MUST respond ONLY with valid JSON matching this schema:\n"
                f"{json.dumps(json_schema, indent=2)}\nDo not include any conversational preamble or markdown code fences."
            )
            system_parts.append(schema_instruction)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": anthropic_messages,
        }

        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": self.DEFAULT_API_VERSION,
            "content-type": "application/json",
        }

        client = self._get_client()
        resp = client.post(self.API_URL, headers=headers, json=payload)
        resp.raise_for_status()

        data = resp.json()

        # Extract text blocks
        content_text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )

        raw_usage = data.get("usage", {})
        prompt_tokens = int(raw_usage.get("input_tokens", 0))
        completion_tokens = int(raw_usage.get("output_tokens", 0))
        usage = TokenUsage.compute(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

        finish_reason = data.get("stop_reason")

        return LLMResponse(
            content=content_text,
            model=model,
            provider=self.provider_name,
            usage=usage,
            finish_reason=finish_reason,
        )
