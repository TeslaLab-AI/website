"""
Tests for Task 19: LLM Gateway.

Comprehensive offline test suite verifying:
1. All 4 provider adapters (Anthropic, OpenAI, DeepSeek, Gemini) return normalized LLMResponse.
2. Gateway routes correctly to provider/model for all 8 target models.
3. 429 rate limit triggers exponential backoff retry.
4. Retry happens no more than 3 times (bounded retries).
5. 503 service unavailable is handled and retried.
6. Persistent provider failure triggers fallback model/provider.
7. Provider errors are normalized across providers without leaking raw structures.
8. Latency is recorded in LLMResponse and telemetry.
9. Prompt, completion, and total token usage is recorded.
10. Hermetic and deterministic offline testing (zero real secrets required).
"""

from __future__ import annotations

import json
from typing import Any
import httpx
import pytest
from pydantic import BaseModel

from app.agents.agent_2.gateway.models import LLMMessage, LLMResponse, TokenUsage
from app.agents.agent_2.gateway.errors import (
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMConfigurationError,
)
from app.agents.agent_2.gateway.adapters.anthropic_adapter import AnthropicAdapter
from app.agents.agent_2.gateway.adapters.openai_adapter import OpenAIAdapter
from app.agents.agent_2.gateway.adapters.deepseek_adapter import DeepSeekAdapter
from app.agents.agent_2.gateway.adapters.gemini_adapter import GeminiAdapter
from app.agents.agent_2.gateway.gateway import LLMGateway, complete
from app.agents.agent_2.gateway.telemetry import GatewayTelemetry


# ─────────────────────────────────────────────────────────────
# Fixtures and Mock Transports
# ─────────────────────────────────────────────────────────────

def make_anthropic_transport(content="Fixed code", input_tokens=15, output_tokens=25, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, text=f"Anthropic error {status_code}")
        body = {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": content}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
        return httpx.Response(200, json=body)
    return httpx.MockTransport(handler)


def make_openai_transport(content="OpenAI fix", prompt_tokens=12, completion_tokens=18, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, text=f"OpenAI error {status_code}")
        body = {
            "id": "chatcmpl_123",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        return httpx.Response(200, json=body)
    return httpx.MockTransport(handler)


def make_deepseek_transport(content="DeepSeek fix", prompt_tokens=14, completion_tokens=22, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, text=f"DeepSeek error {status_code}")
        body = {
            "id": "deepseek_123",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        return httpx.Response(200, json=body)
    return httpx.MockTransport(handler)


def make_gemini_transport(content="Gemini fix", prompt_tokens=20, completion_tokens=30, status_code=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, text=f"Gemini error {status_code}")
        body = {
            "candidates": [{
                "content": {"parts": [{"text": content}], "role": "model"},
                "finishReason": "STOP",
                "index": 0,
            }],
            "usageMetadata": {
                "promptTokenCount": prompt_tokens,
                "candidatesTokenCount": completion_tokens,
                "totalTokenCount": prompt_tokens + completion_tokens,
            },
        }
        return httpx.Response(200, json=body)
    return httpx.MockTransport(handler)


# ─────────────────────────────────────────────────────────────
# Test Cases
# ─────────────────────────────────────────────────────────────

class TestLLMGateway:

    def test_01_all_providers_return_normalized_llm_response(self):
        """1. Each provider adapter returns the same normalized LLMResponse structure."""
        anthropic = AnthropicAdapter(
            api_key="test-key",
            http_client=httpx.Client(transport=make_anthropic_transport("Anthropic text", 10, 20)),
        )
        openai = OpenAIAdapter(
            api_key="test-key",
            http_client=httpx.Client(transport=make_openai_transport("OpenAI text", 15, 25)),
        )
        deepseek = DeepSeekAdapter(
            api_key="test-key",
            http_client=httpx.Client(transport=make_deepseek_transport("DeepSeek text", 12, 18)),
        )
        gemini = GeminiAdapter(
            api_key="test-key",
            http_client=httpx.Client(transport=make_gemini_transport("Gemini text", 30, 40)),
        )

        messages = [{"role": "user", "content": "Hello test"}]

        resp_ant = anthropic.complete(messages, model="claude-3-5-sonnet")
        resp_oai = openai.complete(messages, model="gpt-4o")
        resp_dsk = deepseek.complete(messages, model="deepseek-v3")
        resp_gem = gemini.complete(messages, model="gemini-1.5-pro")

        adapters_and_responses = [
            ("anthropic", resp_ant, 10, 20),
            ("openai", resp_oai, 15, 25),
            ("deepseek", resp_dsk, 12, 18),
            ("gemini", resp_gem, 30, 40),
        ]

        for provider, resp, exp_prompt, exp_comp in adapters_and_responses:
            assert isinstance(resp, LLMResponse)
            assert resp.provider == provider
            assert resp.content
            assert isinstance(resp.usage, TokenUsage)
            assert resp.usage.prompt_tokens == exp_prompt
            assert resp.usage.completion_tokens == exp_comp
            assert resp.usage.total_tokens == exp_prompt + exp_comp
            # Convenience property assertions
            assert resp.prompt_tokens == exp_prompt
            assert resp.completion_tokens == exp_comp
            assert resp.total_tokens == exp_prompt + exp_comp
            assert resp.latency_ms >= 0.0
            assert resp.latency >= 0.0
            assert resp.finish_reason is not None

            # Verify raw provider leakage does NOT exist on the schema
            d = resp.model_dump()
            assert "choices" not in d
            assert "candidates" not in d
            assert "usageMetadata" not in d

    def test_02_gateway_routes_to_correct_provider_and_model(self):
        """2. Gateway routes to the correct provider/model for all 8 target models."""
        test_models = [
            ("claude-3-5-sonnet", "anthropic"),
            ("claude-3-5-haiku", "anthropic"),
            ("gpt-4o", "openai"),
            ("gpt-4o-mini", "openai"),
            ("deepseek-v3", "deepseek"),
            ("deepseek-r1", "deepseek"),
            ("gemini-1.5-pro", "gemini"),
            ("gemini-1.5-flash", "gemini"),
        ]

        gateway = LLMGateway(
            adapters=[
                AnthropicAdapter(api_key="k", http_client=httpx.Client(transport=make_anthropic_transport())),
                OpenAIAdapter(api_key="k", http_client=httpx.Client(transport=make_openai_transport())),
                DeepSeekAdapter(api_key="k", http_client=httpx.Client(transport=make_deepseek_transport())),
                GeminiAdapter(api_key="k", http_client=httpx.Client(transport=make_gemini_transport())),
            ]
        )

        messages = [{"role": "user", "content": "ping"}]
        for model_name, expected_provider in test_models:
            resp = gateway.complete(messages=messages, model=model_name)
            assert resp.provider == expected_provider, f"Expected {expected_provider} for model {model_name}, got {resp.provider}"

    def test_03_429_causes_retry(self):
        """3. 429 rate limit triggers exponential backoff retry and succeeds if transient."""
        call_count = 0
        slept_durations = []

        def failing_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(429, text="Rate limit exceeded. Try again.")
            return httpx.Response(200, json={
                "id": "1",
                "choices": [{"message": {"role": "assistant", "content": "Recovered!"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            })

        gateway = LLMGateway(
            adapters=[
                OpenAIAdapter(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(failing_handler)))
            ],
            max_retries=3,
            backoff_factor=0.1,
            sleep_fn=slept_durations.append,
        )

        resp = gateway.complete(messages=[{"role": "user", "content": "test"}], model="gpt-4o")

        assert resp.content == "Recovered!"
        assert call_count == 3  # Failed attempt 1, failed attempt 2, succeeded attempt 3
        assert len(slept_durations) == 2
        # Backoff: 0.1 * 2^0 = 0.1, 0.1 * 2^1 = 0.2
        assert pytest.approx(slept_durations[0], 0.01) == 0.1
        assert pytest.approx(slept_durations[1], 0.01) == 0.2

    def test_04_retry_happens_no_more_than_3_times(self):
        """4. Retry happens no more than 3 times (max attempts = 4, then raises without infinite loop)."""
        call_count = 0
        slept_durations = []

        def always_429(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(429, text="Persistent rate limit")

        gateway = LLMGateway(
            adapters=[
                OpenAIAdapter(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(always_429)))
            ],
            max_retries=3,
            backoff_factor=0.01,
            sleep_fn=slept_durations.append,
            fallback_map={},  # Disable fallback to test primary retry ceiling
        )

        with pytest.raises(LLMRateLimitError) as exc_info:
            gateway.complete(messages=[{"role": "user", "content": "test"}], model="gpt-4o")

        assert exc_info.value.status_code == 429
        assert call_count == 4  # 1 initial + 3 retries = exactly 4
        assert len(slept_durations) == 3

    def test_05_503_is_handled(self):
        """5. 503 Service Unavailable is handled and retried."""
        call_count = 0

        def temporary_503(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(503, text="Service Temporarily Unavailable")
            return httpx.Response(200, json={
                "id": "2",
                "choices": [{"message": {"role": "assistant", "content": "Server recovered"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 8, "total_tokens": 16},
            })

        gateway = LLMGateway(
            adapters=[
                OpenAIAdapter(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(temporary_503)))
            ],
            max_retries=3,
            sleep_fn=lambda _: None,
        )

        resp = gateway.complete(messages=[{"role": "user", "content": "test"}], model="gpt-4o")
        assert resp.content == "Server recovered"
        assert call_count == 2

    def test_06_persistent_provider_failure_triggers_fallback(self):
        """6. Persistent provider failure triggers configured fallback model/provider."""
        primary_calls = 0
        fallback_calls = 0

        def failing_anthropic(request: httpx.Request) -> httpx.Response:
            nonlocal primary_calls
            primary_calls += 1
            return httpx.Response(503, text="Anthropic major outage")

        def working_openai(request: httpx.Request) -> httpx.Response:
            nonlocal fallback_calls
            fallback_calls += 1
            return httpx.Response(200, json={
                "id": "fb_1",
                "choices": [{"message": {"role": "assistant", "content": "OpenAI fallback response"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            })

        gateway = LLMGateway(
            adapters=[
                AnthropicAdapter(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(failing_anthropic))),
                OpenAIAdapter(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(working_openai))),
            ],
            max_retries=3,
            sleep_fn=lambda _: None,
            fallback_map={"claude-3-5-sonnet": "gpt-4o"},
        )

        resp = gateway.complete(
            messages=[{"role": "user", "content": "Perform task"}],
            model="claude-3-5-sonnet",
        )

        # Primary was called 4 times (1 initial + 3 retries)
        assert primary_calls == 4
        # Fallback was called and succeeded
        assert fallback_calls == 1
        assert resp.model == "gpt-4o"
        assert resp.provider == "openai"
        assert resp.content == "OpenAI fallback response"

        # Check telemetry reflects fallback
        recent = gateway.telemetry.get_recent(1)[0]
        assert recent.fallback_triggered is True
        assert recent.model == "gpt-4o"

    def test_07_provider_errors_are_normalized(self):
        """7. Provider errors are normalized into common error types without leaking raw payloads."""
        # 401 Unauthorized -> LLMAuthenticationError
        adp_401 = AnthropicAdapter(
            api_key="k",
            http_client=httpx.Client(transport=make_anthropic_transport(status_code=401)),
        )
        with pytest.raises(LLMAuthenticationError) as exc_401:
            adp_401.complete([{"role": "user", "content": "hi"}], model="claude-3-5-sonnet")
        assert exc_401.value.status_code == 401
        assert exc_401.value.retryable is False

        # 400 Bad Request -> LLMInvalidRequestError
        adp_400 = OpenAIAdapter(
            api_key="k",
            http_client=httpx.Client(transport=make_openai_transport(status_code=400)),
        )
        with pytest.raises(LLMInvalidRequestError) as exc_400:
            adp_400.complete([{"role": "user", "content": "hi"}], model="gpt-4o")
        assert exc_400.value.status_code == 400
        assert exc_400.value.retryable is False

        # Network disconnect -> LLMProviderUnavailableError
        def disconnect_handler(req: httpx.Request):
            raise httpx.ConnectError("Connection refused by peer")

        adp_net = DeepSeekAdapter(
            api_key="k",
            http_client=httpx.Client(transport=httpx.MockTransport(disconnect_handler)),
        )
        with pytest.raises(LLMProviderUnavailableError) as exc_net:
            adp_net.complete([{"role": "user", "content": "hi"}], model="deepseek-v3")
        assert exc_net.value.retryable is True

    def test_08_latency_is_recorded(self):
        """8. Latency is recorded in milliseconds and telemetry."""
        telemetry = GatewayTelemetry()
        gateway = LLMGateway(
            adapters=[
                GeminiAdapter(api_key="k", http_client=httpx.Client(transport=make_gemini_transport()))
            ],
            telemetry=telemetry,
        )

        resp = gateway.complete(messages=[{"role": "user", "content": "hi"}], model="gemini-1.5-flash")
        assert resp.latency_ms >= 0.0
        assert resp.latency >= 0.0

        records = telemetry.get_recent(1)
        assert len(records) == 1
        assert records[0].latency_ms >= 0.0
        assert records[0].model == "gemini-1.5-flash"
        assert records[0].success is True

    def test_09_token_usage_is_recorded(self):
        """9. Prompt, completion, and total token usage is recorded."""
        telemetry = GatewayTelemetry()
        gateway = LLMGateway(
            adapters=[
                AnthropicAdapter(
                    api_key="k",
                    http_client=httpx.Client(transport=make_anthropic_transport(input_tokens=42, output_tokens=84)),
                )
            ],
            telemetry=telemetry,
        )

        resp = gateway.complete(messages=[{"role": "user", "content": "Count tokens"}], model="claude-3-5-sonnet")

        assert resp.prompt_tokens == 42
        assert resp.completion_tokens == 84
        assert resp.total_tokens == 126

        record = telemetry.get_recent(1)[0]
        assert record.prompt_tokens == 42
        assert record.completion_tokens == 84
        assert record.total_tokens == 126

    def test_10_no_secrets_required_for_offline_tests(self, monkeypatch):
        """10. Offline tests execute deterministically without any API keys or network access."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        # Injected clients and mock transports work hermetically without environment secrets
        mock_gateway = LLMGateway(
            adapters=[
                AnthropicAdapter(api_key="mock", http_client=httpx.Client(transport=make_anthropic_transport())),
                OpenAIAdapter(api_key="mock", http_client=httpx.Client(transport=make_openai_transport())),
                DeepSeekAdapter(api_key="mock", http_client=httpx.Client(transport=make_deepseek_transport())),
                GeminiAdapter(api_key="mock", http_client=httpx.Client(transport=make_gemini_transport())),
            ]
        )

        for model in ["claude-3-5-sonnet", "gpt-4o", "deepseek-v3", "gemini-1.5-pro"]:
            res = mock_gateway.complete([{"role": "user", "content": "offline"}], model=model)
            assert res.content
            assert res.provider

    def test_11_json_schema_enforcement_and_parsing(self):
        """Bonus: json_schema parameter triggers structured output parsing."""
        class FixRecommendation(BaseModel):
            fix: str
            confidence: float

        json_payload = json.dumps({"fix": "Add null check", "confidence": 0.95})

        adapter = OpenAIAdapter(
            api_key="k",
            http_client=httpx.Client(transport=make_openai_transport(content=json_payload)),
        )

        resp = adapter.complete(
            messages=[{"role": "user", "content": "Suggest fix"}],
            model="gpt-4o",
            json_schema=FixRecommendation,
        )

        assert resp.parsed == {"fix": "Add null check", "confidence": 0.95}

    def test_12_non_retryable_auth_error_fails_immediately_without_retry(self):
        """Authentication error (401) must fail immediately without wasting retries."""
        call_count = 0

        def auth_fail(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(401, text="Unauthorized: Invalid API Key")

        gateway = LLMGateway(
            adapters=[
                OpenAIAdapter(api_key="invalid", http_client=httpx.Client(transport=httpx.MockTransport(auth_fail)))
            ],
            max_retries=3,
        )

        with pytest.raises(LLMAuthenticationError):
            gateway.complete(messages=[{"role": "user", "content": "hi"}], model="gpt-4o")

        # Must NOT retry on 401
        assert call_count == 1
