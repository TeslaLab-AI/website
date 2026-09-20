"""
DeepSeek provider adapter for DeepSeek-V3 and DeepSeek-R1.
"""

from __future__ import annotations

import json
import os
from typing import Any
import httpx

from app.agents.agent_2.gateway.adapters.base import BaseLLMAdapter
from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.errors import LLMConfigurationError


class DeepSeekAdapter(BaseLLMAdapter):
    """Adapter for DeepSeek API (compatible with OpenAI format)."""

    API_URL = "https://api.deepseek.com/v1/chat/completions"

    SUPPORTED_MODELS = [
        "deepseek-v3",
        "deepseek-r1",
        "deepseek-chat",
        "deepseek-reasoner",
    ]

    MODEL_ALIASES = {
        "deepseek-v3": "deepseek-chat",
        "deepseek-r1": "deepseek-reasoner",
    }

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def supported_models(self) -> list[str]:
        return self.SUPPORTED_MODELS

    def normalize_model_name(self, model: str) -> str:
        cleaned = model.strip().lower()
        return self.MODEL_ALIASES.get(cleaned, cleaned)

    def get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise LLMConfigurationError("DEEPSEEK_API_KEY environment variable is missing", provider=self.provider_name)
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

        if json_schema:
            schema_text = (
                f"\n\nJSON Schema requirement:\nYou MUST reply ONLY in valid JSON matching this schema:\n"
                f"{json.dumps(json_schema, indent=2)}"
            )
            # Append schema prompt to first system message or create one
            found_system = False
            for m in api_messages:
                if m["role"] == "system":
                    m["content"] += schema_text
                    found_system = True
                    break
            if not found_system:
                api_messages.insert(0, {"role": "system", "content": schema_text})

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_schema:
            payload["response_format"] = {"type": "json_object"}

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
            choice_msg = choices[0].get("message", {})
            content_text = choice_msg.get("content") or choice_msg.get("reasoning_content") or ""
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
