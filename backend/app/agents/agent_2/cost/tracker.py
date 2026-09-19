"""
Core CostTracker Implementation for Agent 2.
Maintains granular per-call records and session-level cumulative accounting.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any, Sequence
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_2.cost.calculator import (
    CostBreakdown,
    CostCalculator,
    default_calculator,
)
from app.agents.agent_2.gateway.models import LLMResponse, TokenUsage


class CostRecord(BaseModel):
    """Immutable audit record for a single LLM call."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique call UUID")
    session_id: str = Field(default="default", description="Associated session or task ID")
    model: str = Field(..., description="Model identifier used")
    provider: str = Field(..., description="Provider name")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0, description="Total cost of this call in USD")
    prompt_cost_usd: float = Field(default=0.0, ge=0.0)
    completion_cost_usd: float = Field(default=0.0, ge=0.0)
    cached_cost_usd: float = Field(default=0.0, ge=0.0)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 UTC timestamp",
    )
    latency_ms: float = Field(default=0.0, ge=0.0)


class SessionCostSummary(BaseModel):
    """Cumulative token and financial summary for a task session."""
    model_config = ConfigDict(extra="ignore")

    session_id: str
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    call_count: int = 0
    budget_limit_usd: float = 0.50
    status: str = "active"  # "active" | "completed" | "NEEDS_HUMAN"

    @property
    def is_budget_exceeded(self) -> bool:
        return self.total_cost_usd >= self.budget_limit_usd

    @property
    def remaining_budget_usd(self) -> float:
        return max(0.0, round(self.budget_limit_usd - self.total_cost_usd, 8))


class CostTracker:
    """
    In-memory, thread-safe cost tracking service.
    Maintains historical per-call records and running aggregates per session.
    """

    def __init__(
        self,
        calculator: CostCalculator | None = None,
        default_budget_limit_usd: float = 0.50,
    ) -> None:
        self.calculator = calculator or default_calculator
        self.default_budget_limit_usd = default_budget_limit_usd
        self._lock = threading.Lock()
        self._records: list[CostRecord] = []
        self._session_records: dict[str, list[CostRecord]] = {}
        self._session_statuses: dict[str, str] = {}
        self._session_budgets: dict[str, float] = {}

    def set_session_budget(self, session_id: str, budget_limit_usd: float) -> None:
        """Configure custom budget limit for a session."""
        with self._lock:
            self._session_budgets[session_id] = budget_limit_usd

    def get_session_budget(self, session_id: str) -> float:
        """Retrieve budget limit for a session."""
        with self._lock:
            return self._session_budgets.get(session_id, self.default_budget_limit_usd)

    def set_session_status(self, session_id: str, status: str) -> None:
        """Update session lifecycle status (e.g. NEEDS_HUMAN)."""
        with self._lock:
            self._session_statuses[session_id] = status

    def get_session_status(self, session_id: str) -> str:
        """Get session lifecycle status."""
        with self._lock:
            return self._session_statuses.get(session_id, "active")

    def record_call(
        self,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        provider: str | None = None,
        session_id: str = "default",
        latency_ms: float = 0.0,
        call_id: str | None = None,
    ) -> CostRecord:
        """
        Compute cost breakdown and append an immutable record to session history.
        """
        breakdown = self.calculator.calculate_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            provider=provider,
        )

        record = CostRecord(
            call_id=call_id or str(uuid.uuid4()),
            session_id=session_id,
            model=breakdown.model,
            provider=breakdown.provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            total_tokens=breakdown.total_tokens,
            cost_usd=breakdown.total_cost_usd,
            prompt_cost_usd=breakdown.prompt_cost_usd,
            completion_cost_usd=breakdown.completion_cost_usd,
            cached_cost_usd=breakdown.cached_cost_usd,
            latency_ms=latency_ms,
        )

        with self._lock:
            self._records.append(record)
            if session_id not in self._session_records:
                self._session_records[session_id] = []
            self._session_records[session_id].append(record)

            # Check if this call caused cumulative budget to reach or exceed limit
            current_total = sum(r.cost_usd for r in self._session_records[session_id])
            budget = self._session_budgets.get(session_id, self.default_budget_limit_usd)
            if current_total >= budget:
                self._session_statuses[session_id] = "NEEDS_HUMAN"

        return record

    def record_response(
        self,
        response: LLMResponse,
        session_id: str = "default",
        cached_tokens: int = 0,
    ) -> CostRecord:
        """Convenience method to record usage directly from an LLMResponse."""
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        # Check if response usage carries cached_tokens
        usage_cached = getattr(response.usage, "cached_tokens", 0)
        if usage_cached > 0 or cached_tokens == 0:
            cached_tokens = usage_cached

        record = self.record_call(
            model=response.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            provider=response.provider,
            session_id=session_id,
            latency_ms=response.latency_ms,
        )

        # Attach computed cost_usd to response if attribute exists
        if hasattr(response, "cost_usd"):
            object.__setattr__(response, "cost_usd", record.cost_usd)

        return record

    def get_session_summary(self, session_id: str = "default") -> SessionCostSummary:
        """Compute running totals for a given session."""
        with self._lock:
            records = list(self._session_records.get(session_id, []))
            budget = self._session_budgets.get(session_id, self.default_budget_limit_usd)
            status = self._session_statuses.get(session_id, "active")

        prompt_tot = sum(r.prompt_tokens for r in records)
        comp_tot = sum(r.completion_tokens for r in records)
        cached_tot = sum(r.cached_tokens for r in records)
        total_toks = sum(r.total_tokens for r in records)
        total_cost = round(sum(r.cost_usd for r in records), 8)

        # Auto-detect NEEDS_HUMAN if cost reached or exceeded budget
        if total_cost >= budget and status != "completed":
            status = "NEEDS_HUMAN"

        return SessionCostSummary(
            session_id=session_id,
            total_prompt_tokens=prompt_tot,
            total_completion_tokens=comp_tot,
            total_cached_tokens=cached_tot,
            total_tokens=total_toks,
            total_cost_usd=total_cost,
            call_count=len(records),
            budget_limit_usd=budget,
            status=status,
        )

    def get_session_records(self, session_id: str = "default") -> list[CostRecord]:
        """Return shallow copy of all records for a session."""
        with self._lock:
            return list(self._session_records.get(session_id, []))

    def get_all_records(self) -> list[CostRecord]:
        """Return shallow copy of all recorded calls."""
        with self._lock:
            return list(self._records)

    def get_all_sessions(self) -> list[str]:
        """Return list of active session IDs."""
        with self._lock:
            return list(self._session_records.keys())

    def reset_session(self, session_id: str) -> None:
        """Clear records for a single session."""
        with self._lock:
            self._session_records.pop(session_id, None)
            self._session_statuses.pop(session_id, None)
            self._session_budgets.pop(session_id, None)
            self._records = [r for r in self._records if r.session_id != session_id]

    def reset_all(self) -> None:
        """Clear all tracking state."""
        with self._lock:
            self._records.clear()
            self._session_records.clear()
            self._session_statuses.clear()
            self._session_budgets.clear()


# Global default cost tracker singleton
default_cost_tracker = CostTracker()
