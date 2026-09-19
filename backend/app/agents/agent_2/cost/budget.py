"""
Hard Budget Enforcement for Agent 2 LLM Invocations.
Enforces hard $0.50 ceiling per task run, intercepting pre-call requests,
stopping runaway sequences, generating structured cutoff events,
and transitioning session lifecycle state to NEEDS_HUMAN.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Sequence
from pydantic import BaseModel, ConfigDict, Field

from app.agents.agent_2.gateway.errors import LLMError
from app.agents.agent_2.cost.calculator import default_calculator
from app.agents.agent_2.cost.tracker import CostTracker, default_cost_tracker

logger = logging.getLogger("budget_enforcer")

DEFAULT_TASK_BUDGET_USD: float = 0.50


class BudgetCutoffEvent(BaseModel):
    """Structured audit event logged when a task session reaches budget cutoff."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    session_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_type: str = "BUDGET_EXCEEDED_CUTOFF"
    from_state: str = "active"
    to_state: str = "NEEDS_HUMAN"
    current_cost_usd: float
    budget_limit_usd: float
    attempted_model: str
    reason: str


class BudgetExceededError(LLMError):
    """
    Non-retryable terminal exception raised when an LLM call would exceed
    or has reached the per-task budget ceiling ($0.50).
    """

    def __init__(
        self,
        session_id: str,
        current_cost_usd: float,
        budget_limit_usd: float = DEFAULT_TASK_BUDGET_USD,
        estimated_cost_usd: float = 0.0,
        model: str = "unknown",
        message: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.current_cost_usd = round(current_cost_usd, 8)
        self.budget_limit_usd = round(budget_limit_usd, 8)
        self.estimated_cost_usd = round(estimated_cost_usd, 8)
        self.model = model

        msg = message or (
            f"[BUDGET EXCEEDED] Task session '{session_id}' hit budget limit ${budget_limit_usd:.4f}. "
            f"Current expenditure: ${current_cost_usd:.4f}, estimated call: ${estimated_cost_usd:.4f}. "
            f"Execution halted immediately; session transitioned to NEEDS_HUMAN."
        )
        super().__init__(
            message=msg,
            provider="gateway_budget_enforcer",
            retryable=False,
            status_code=402,
            model=model,
        )


class BudgetEnforcer:
    """
    Pre-call interceptor that deterministically checks session balance
    and prevents LLM invocations that would breach the hard $0.50 budget.
    """

    def __init__(
        self,
        budget_limit_usd: float = DEFAULT_TASK_BUDGET_USD,
        calculator=None,
    ) -> None:
        self.budget_limit_usd = budget_limit_usd
        self.calculator = calculator or default_calculator
        self.cutoff_events: list[BudgetCutoffEvent] = []

    def estimate_prompt_tokens(self, messages: Sequence[Any]) -> int:
        """Heuristic estimation of prompt tokens (approx 1 token per 4 chars)."""
        char_count = 0
        for m in messages:
            if isinstance(m, dict):
                char_count += len(str(m.get("content", "")))
            elif hasattr(m, "content"):
                char_count += len(str(getattr(m, "content", "")))
        return max(1, char_count // 4)

    def check_budget(
        self,
        session_id: str,
        model: str,
        messages: Sequence[Any] | None = None,
        max_tokens: int = 1024,
        tracker: CostTracker | None = None,
        estimated_call_cost: float | None = None,
    ) -> None:
        """
        Evaluate current session spend and forecast next call cost.
        Raises BudgetExceededError and transitions state to NEEDS_HUMAN if ceiling is breached.
        """
        active_tracker = tracker or default_cost_tracker
        summary = active_tracker.get_session_summary(session_id)
        current_cost = summary.total_cost_usd
        budget_limit = summary.budget_limit_usd or self.budget_limit_usd

        # 1. Condition: Session has already reached or exceeded ceiling
        if current_cost >= budget_limit:
            self._trigger_cutoff(
                session_id=session_id,
                current_cost=current_cost,
                budget_limit=budget_limit,
                model=model,
                tracker=active_tracker,
                reason="Cumulative spend already reached or exceeded budget limit",
            )

        # 2. Condition: Forecast next call cost and determine if it exceeds remaining budget
        if estimated_call_cost is None and messages is not None:
            try:
                est_prompt = self.estimate_prompt_tokens(messages)
                est_breakdown = self.calculator.calculate_cost(
                    model=model,
                    prompt_tokens=est_prompt,
                    completion_tokens=min(max_tokens, 512),
                )
                estimated_call_cost = est_breakdown.total_cost_usd
            except Exception:
                estimated_call_cost = 0.0

        projected_cost = round(current_cost + (estimated_call_cost or 0.0), 8)
        if projected_cost > budget_limit:
            self._trigger_cutoff(
                session_id=session_id,
                current_cost=current_cost,
                budget_limit=budget_limit,
                model=model,
                tracker=active_tracker,
                estimated_call_cost=estimated_call_cost or 0.0,
                reason=f"Next call projected cost (+${estimated_call_cost:.4f}) would exceed budget limit ${budget_limit:.4f}",
            )

    def _trigger_cutoff(
        self,
        session_id: str,
        current_cost: float,
        budget_limit: float,
        model: str,
        tracker: CostTracker,
        estimated_call_cost: float = 0.0,
        reason: str = "Budget ceiling breached",
    ) -> None:
        """Record audit cutoff event, update tracker session status, and raise terminal error."""
        cutoff_event = BudgetCutoffEvent(
            session_id=session_id,
            current_cost_usd=current_cost,
            budget_limit_usd=budget_limit,
            attempted_model=model,
            reason=reason,
        )
        self.cutoff_events.append(cutoff_event)

        # Transition session to NEEDS_HUMAN
        tracker.set_session_status(session_id, "NEEDS_HUMAN")

        logger.critical(
            "BUDGET ENFORCER HALT: session '%s' cutoff triggered (spent: $%.4f / limit: $%.4f). Transitioned to NEEDS_HUMAN.",
            session_id,
            current_cost,
            budget_limit,
        )

        raise BudgetExceededError(
            session_id=session_id,
            current_cost_usd=current_cost,
            budget_limit_usd=budget_limit,
            estimated_cost_usd=estimated_call_cost,
            model=model,
            message=(
                f"[BUDGET EXCEEDED] Task session '{session_id}' reached hard budget limit of ${budget_limit:.2f}. "
                f"Current spend: ${current_cost:.4f}. Call blocked; session transitioned to NEEDS_HUMAN."
            ),
        )


# Global default budget enforcer singleton
default_budget_enforcer = BudgetEnforcer()
