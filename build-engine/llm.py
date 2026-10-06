"""Gemini REST client used by the Build Engine."""
from __future__ import annotations

import os
import time

import httpx


def complete(system: str, user: str, json_mode: bool = False) -> str:
    """Complete one request through Gemini REST without exposing credentials."""
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL")
    if not api_key or not model:
        raise RuntimeError("GEMINI_API_KEY and GEMINI_MODEL must be set")
    body: dict[str, object] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
    }
    if json_mode:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for attempt in range(2):
        try:
            response = httpx.post(url, headers={"x-goog-api-key": api_key}, json=body, timeout=60)
        except httpx.HTTPError as exc:
            raise RuntimeError("Gemini request failed") from exc
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise RuntimeError(f"Gemini request failed with HTTP {response.status_code}")
        if response.is_error:
            raise RuntimeError(f"Gemini request failed with HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Gemini returned malformed JSON") from exc
        candidates = data.get("candidates") if isinstance(data, dict) else None
        content = candidates[0].get("content") if isinstance(candidates, list) and candidates else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts:
            raise RuntimeError("Gemini returned no usable candidate; response may be blocked")
        text = parts[0].get("text") if isinstance(parts[0], dict) else None
        if not isinstance(text, str) or not text:
            raise RuntimeError("Gemini returned no text")
        return text
    raise RuntimeError("Gemini request failed")
