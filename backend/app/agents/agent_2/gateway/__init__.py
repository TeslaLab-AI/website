"""
LLM Gateway package for Engineer 2 (Agent 2).
Provides unified multi-provider routing, resilient retries, fallback handling,
and normalized responses across Anthropic, OpenAI, DeepSeek, and Google Gemini.
"""

from app.agents.agent_2.gateway.models import (
    LLMMessage,
    TokenUsage,
    LLMResponse,
)
from app.agents.agent_2.gateway.errors import (
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMAuthenticationError,
    LLMInvalidRequestError,
    LLMProviderUnavailableError,
    LLMConfigurationError,
    normalize_http_status_error,
)
from app.agents.agent_2.gateway.adapters import (
    BaseLLMAdapter,
    AnthropicAdapter,
    OpenAIAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
)
from app.agents.agent_2.gateway.telemetry import (
    TelemetryRecord,
    GatewayTelemetry,
    default_telemetry,
)
from app.agents.agent_2.gateway.gateway import (
    LLMGateway,
    default_gateway,
    complete,
)

__all__ = [
    "LLMMessage",
    "TokenUsage",
    "LLMResponse",
    "LLMError",
    "LLMRateLimitError",
    "LLMServerError",
    "LLMAuthenticationError",
    "LLMInvalidRequestError",
    "LLMProviderUnavailableError",
    "LLMConfigurationError",
    "normalize_http_status_error",
    "BaseLLMAdapter",
    "AnthropicAdapter",
    "OpenAIAdapter",
    "DeepSeekAdapter",
    "GeminiAdapter",
    "TelemetryRecord",
    "GatewayTelemetry",
    "default_telemetry",
    "LLMGateway",
    "default_gateway",
    "complete",
]
