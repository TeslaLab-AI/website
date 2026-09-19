"""
Normalized exceptions for LLM Gateway.
Ensures provider-specific error types and raw payloads do not leak outside the adapter layer.
"""

from __future__ import annotations
from typing import Any


class LLMError(Exception):
    """Base exception for all LLM Gateway errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int | None = None,
        retryable: bool = False,
        model: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        self.model = model
        self.details = details

    def __str__(self) -> str:
        code_str = f" [status {self.status_code}]" if self.status_code else ""
        model_str = f" (model: {self.model})" if self.model else ""
        return f"[{self.provider.upper()}]{code_str}{model_str}: {self.message}"


class LLMRateLimitError(LLMError):
    """Raised when provider hits rate limits (HTTP 429). Retryable."""

    def __init__(self, message: str, provider: str, model: str | None = None, **kwargs: Any) -> None:
        super().__init__(message, provider=provider, status_code=429, retryable=True, model=model, **kwargs)


class LLMServerError(LLMError):
    """Raised on provider internal or temporary server issues (HTTP 500, 502, 503, 504). Retryable."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int = 503,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            status_code=status_code,
            retryable=True,
            model=model,
            **kwargs,
        )


class LLMAuthenticationError(LLMError):
    """Raised on authentication or unauthorized failures (HTTP 401, 403). Non-retryable."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int = 401,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            status_code=status_code,
            retryable=False,
            model=model,
            **kwargs,
        )


class LLMInvalidRequestError(LLMError):
    """Raised on malformed request or parameter rejection (HTTP 400). Non-retryable."""

    def __init__(
        self,
        message: str,
        provider: str,
        status_code: int = 400,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            message,
            provider=provider,
            status_code=status_code,
            retryable=False,
            model=model,
            **kwargs,
        )


class LLMProviderUnavailableError(LLMError):
    """Raised on connection timeout or network unreachability. Retryable."""

    def __init__(self, message: str, provider: str, model: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            message,
            provider=provider,
            status_code=503,
            retryable=True,
            model=model,
            **kwargs,
        )


class LLMConfigurationError(LLMError):
    """Raised when API key or provider setup is missing or invalid. Non-retryable."""

    def __init__(self, message: str, provider: str, model: str | None = None, **kwargs: Any) -> None:
        super().__init__(
            message,
            provider=provider,
            status_code=None,
            retryable=False,
            model=model,
            **kwargs,
        )


def normalize_http_status_error(
    provider: str,
    status_code: int,
    error_text: str,
    model: str | None = None,
) -> LLMError:
    """Map an HTTP status code to a normalized LLM exception without leaking raw response."""
    clean_msg = error_text.strip() or f"HTTP {status_code} error from {provider}"
    # Truncate overly long error HTML/dumps to protect logs
    if len(clean_msg) > 300:
        clean_msg = clean_msg[:300] + "..."

    if status_code == 429:
        return LLMRateLimitError(clean_msg, provider=provider, model=model)
    elif status_code in (401, 403):
        return LLMAuthenticationError(clean_msg, provider=provider, status_code=status_code, model=model)
    elif status_code == 400:
        return LLMInvalidRequestError(clean_msg, provider=provider, status_code=status_code, model=model)
    elif status_code in (500, 502, 503, 504):
        return LLMServerError(clean_msg, provider=provider, status_code=status_code, model=model)
    else:
        return LLMError(
            clean_msg,
            provider=provider,
            status_code=status_code,
            retryable=(status_code >= 500),
            model=model,
        )
