"""
Session Cost Accumulator.
Provides structured session-level accounting across multiple tasks, tracking
running token consumption, cost accumulation, call counts, and session state.
"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_2.cost.tracker import CostRecord, SessionCostSummary


class SessionCostState(BaseModel):
    """
    Rich state model tracking complete session financial accounting.
    """
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
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    calls: list[CostRecord] = Field(default_factory=list)

    @property
    def is_budget_exceeded(self) -> bool:
        return self.total_cost_usd >= self.budget_limit_usd

    @property
    def remaining_budget_usd(self) -> float:
        return max(0.0, round(self.budget_limit_usd - self.total_cost_usd, 8))

    def add_call(self, record: CostRecord) -> None:
        """Accumulate a new call into running totals."""
        self.calls.append(record)
        self.call_count += 1
        self.total_prompt_tokens += record.prompt_tokens
        self.total_completion_tokens += record.completion_tokens
        self.total_cached_tokens += record.cached_tokens
        self.total_tokens += record.total_tokens
        self.total_cost_usd = round(self.total_cost_usd + record.cost_usd, 8)
        self.updated_at = datetime.now(timezone.utc).isoformat()

        # Check hard budget threshold
        if self.total_cost_usd >= self.budget_limit_usd and self.status != "completed":
            self.status = "NEEDS_HUMAN"

    def to_summary(self) -> SessionCostSummary:
        """Convert state to standardized SessionCostSummary."""
        return SessionCostSummary(
            session_id=self.session_id,
            total_prompt_tokens=self.total_prompt_tokens,
            total_completion_tokens=self.total_completion_tokens,
            total_cached_tokens=self.total_cached_tokens,
            total_tokens=self.total_tokens,
            total_cost_usd=self.total_cost_usd,
            call_count=self.call_count,
            budget_limit_usd=self.budget_limit_usd,
            status=self.status,
        )


class SessionCostManager:
    """
    Thread-safe manager for tracking cost accumulation across multiple concurrent sessions.
    """

    def __init__(self, default_budget_limit_usd: float = 0.50) -> None:
        self.default_budget_limit_usd = default_budget_limit_usd
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionCostState] = {}

    def get_or_create(self, session_id: str, budget_limit_usd: float | None = None) -> SessionCostState:
        """Get existing session state or initialize a new one."""
        with self._lock:
            if session_id not in self._sessions:
                limit = budget_limit_usd if budget_limit_usd is not None else self.default_budget_limit_usd
                self._sessions[session_id] = SessionCostState(
                    session_id=session_id,
                    budget_limit_usd=limit,
                )
            return self._sessions[session_id]

    def record_call(self, session_id: str, record: CostRecord) -> SessionCostState:
        """Record an execution call into the session state."""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionCostState(
                    session_id=session_id,
                    budget_limit_usd=self.default_budget_limit_usd,
                )
            state = self._sessions[session_id]
            state.add_call(record)
            return state

    def get_summary(self, session_id: str) -> SessionCostSummary:
        """Return the current summary for a session."""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id].to_summary()
            return SessionCostSummary(
                session_id=session_id,
                budget_limit_usd=self.default_budget_limit_usd,
                status="active",
            )

    def set_status(self, session_id: str, status: str) -> None:
        """Update session lifecycle status."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].status = status
                self._sessions[session_id].updated_at = datetime.now(timezone.utc).isoformat()

    def get_status(self, session_id: str) -> str:
        """Retrieve session status."""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id].status
            return "active"

    def list_sessions(self) -> list[str]:
        """Return list of known session IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def get_all_summaries(self) -> dict[str, SessionCostSummary]:
        """Return summaries for all tracked sessions."""
        with self._lock:
            return {sid: s.to_summary() for sid, s in self._sessions.items()}

    def reset_session(self, session_id: str) -> None:
        """Reset a single session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def reset_all(self) -> None:
        """Reset all tracked sessions."""
        with self._lock:
            self._sessions.clear()


# Global default session cost manager singleton
default_session_manager = SessionCostManager()
