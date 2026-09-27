"""
Google Gemini provider adapter for Gemini 1.5 Pro and Gemini 1.5 Flash.
"""

from __future__ import annotations

import json
import os
from typing import Any
import httpx

from app.agents.agent_2.gateway.adapters.base import BaseLLMAdapter
from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.errors import LLMConfigurationError


class GeminiAdapter(BaseLLMAdapter):
    """Adapter for Google Gemini REST API."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    SUPPORTED_MODELS = [
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-pro",
        "gemini-flash",
    ]

    MODEL_ALIASES = {
        "gemini-pro": "gemini-1.5-pro",
        "gemini-flash": "gemini-1.5-flash",
    }

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def supported_models(self) -> list[str]:
        return self.SUPPORTED_MODELS

    def normalize_model_name(self, model: str) -> str:
        cleaned = model.strip().lower()
        return self.MODEL_ALIASES.get(cleaned, cleaned)

    def get_api_key(self) -> str:
        if self._api_key:
            return self._api_key
        key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
        if not key:
            raise LLMConfigurationError(
                "GEMINI_API_KEY or GOOGLE_API_KEY environment variable is missing",
                provider=self.provider_name,
            )
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

        system_instructions: list[str] = []
        gemini_contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_instructions.append(msg.content)
            else:
                gemini_role = "model" if msg.role == "assistant" else "user"
                gemini_contents.append({
                    "role": gemini_role,
                    "parts": [{"text": msg.content}],
                })

        if not gemini_contents:
            gemini_contents.append({
                "role": "user",
                "parts": [{"text": "Hello"}],
            })

        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }

        if json_schema:
            gen_config["responseMimeType"] = "application/json"
            gen_config["responseSchema"] = json_schema
            system_instructions.append("Respond strictly with valid JSON conforming to the schema.")

        payload: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": gen_config,
        }

        if system_instructions:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_instructions)}]
            }

        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        url = f"{self.BASE_URL}/{model}:generateContent"

        client = self._get_client()
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()

        data = resp.json()

        content_parts: list[str] = []
        finish_reason = None
        candidates = data.get("candidates", [])
        if candidates:
            cand = candidates[0]
            finish_reason = cand.get("finishReason")
            parts = cand.get("content", {}).get("parts", [])
            for p in parts:
                if "text" in p:
                    content_parts.append(p["text"])

        content_text = "".join(content_parts)

        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = int(usage_meta.get("promptTokenCount", 0))
        completion_tokens = int(usage_meta.get("candidatesTokenCount", 0))
        total_tokens = int(usage_meta.get("totalTokenCount", prompt_tokens + completion_tokens))

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
