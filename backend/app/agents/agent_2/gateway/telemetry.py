"""
Telemetry recorder for LLM Gateway.
Records latency, token consumption, model used, retry attempts, and fallback events.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import time
from typing import Any

logger = logging.getLogger("llm_gateway")


@dataclass
class TelemetryRecord:
    """Telemetry data captured for each gateway completion execution."""
    model: str
    provider: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    attempts: int
    fallback_triggered: bool = False
    success: bool = True
    error_type: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "model": self.model,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "attempts": self.attempts,
            "fallback_triggered": self.fallback_triggered,
            "success": self.success,
            "error_type": self.error_type,
        }


class GatewayTelemetry:
    """Manages recording and retrieval of LLM gateway telemetry."""

    def __init__(self, max_history: int = 200) -> None:
        self._history: deque[TelemetryRecord] = deque(maxlen=max_history)

    def record(
        self,
        model: str,
        provider: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        attempts: int,
        fallback_triggered: bool = False,
        success: bool = True,
        error_type: str | None = None,
    ) -> TelemetryRecord:
        rec = TelemetryRecord(
            model=model,
            provider=provider,
            latency_ms=round(latency_ms, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            attempts=attempts,
            fallback_triggered=fallback_triggered,
            success=success,
            error_type=error_type,
        )
        self._history.append(rec)

        # Standard structured logging
        status_str = "SUCCESS" if success else f"FAILURE({error_type})"
        fallback_str = " [FALLBACK]" if fallback_triggered else ""
        logger.info(
            "LLMGateway %s%s: provider=%s model=%s latency=%.2fms tokens=%d (prompt=%d, completion=%d) attempts=%d",
            status_str,
            fallback_str,
            provider,
            model,
            latency_ms,
            total_tokens,
            prompt_tokens,
            completion_tokens,
            attempts,
        )
        return rec

    def get_recent(self, count: int = 10) -> list[TelemetryRecord]:
        """Return the most recent N telemetry records."""
        items = list(self._history)
        return items[-count:] if count else items

    def clear(self) -> None:
        """Clear telemetry history."""
        self._history.clear()


# Default global telemetry instance
default_telemetry = GatewayTelemetry()
