"""
Cost Persistence Service for Agent 2.
Persists granular LLM cost records, session financial summaries,
and NEEDS_HUMAN state transitions to agent_events and backend stores.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable
import urllib.request
import urllib.error

from app.agents.agent_2.cost.tracker import CostRecord, SessionCostSummary
from app.agents.agent_2.cost.budget import BudgetCutoffEvent

logger = logging.getLogger("cost_persistence")


class CostPersistenceService:
    """
    Formats and persists structured audit events to agent_events,
    session summaries, and pipeline state stores.
    """

    def __init__(
        self,
        supabase_client_fn: Callable[[], tuple[str, str]] | None = None,
        dry_run: bool = False,
    ) -> None:
        """
        Args:
            supabase_client_fn: Optional callable returning (supabase_url, service_role_key)
            dry_run: When True, payloads are generated and validated without HTTP dispatch
        """
        self.supabase_client_fn = supabase_client_fn
        self.dry_run = dry_run
        self.persisted_events: list[dict[str, Any]] = []
        self.persisted_summaries: list[dict[str, Any]] = []

    def format_call_event(
        self,
        record: CostRecord,
        from_state: str = "active",
        to_state: str = "active",
    ) -> dict[str, Any]:
        """
        Format an immutable agent_events transition payload for a single LLM invocation.
        Compatible with public.agent_events schema (session_id, from_state, to_state, event_type, payload, timestamp).
        """
        return {
            "session_id": record.session_id,
            "from_state": from_state,
            "to_state": to_state,
            "event_type": "LLM_CALL_COST",
            "payload": {
                "call_id": record.call_id,
                "model": record.model,
                "provider": record.provider,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "cached_tokens": record.cached_tokens,
                "total_tokens": record.total_tokens,
                "cost_usd": record.cost_usd,
                "prompt_cost_usd": record.prompt_cost_usd,
                "completion_cost_usd": record.completion_cost_usd,
                "cached_cost_usd": record.cached_cost_usd,
                "latency_ms": record.latency_ms,
            },
            "timestamp": record.timestamp,
        }

    def format_budget_cutoff_event(self, cutoff: BudgetCutoffEvent) -> dict[str, Any]:
        """
        Format a terminal NEEDS_HUMAN transition event when per-task budget ceiling is reached.
        """
        return {
            "session_id": cutoff.session_id,
            "from_state": cutoff.from_state,
            "to_state": "NEEDS_HUMAN",
            "event_type": cutoff.event_type,
            "payload": {
                "current_cost_usd": cutoff.current_cost_usd,
                "budget_limit_usd": cutoff.budget_limit_usd,
                "attempted_model": cutoff.attempted_model,
                "reason": cutoff.reason,
                "transition": "NEEDS_HUMAN",
            },
            "timestamp": cutoff.timestamp,
        }

    def format_session_summary_payload(self, summary: SessionCostSummary) -> dict[str, Any]:
        """
        Format cumulative financial summary for session record persistence.
        """
        return {
            "session_id": summary.session_id,
            "total_prompt_tokens": summary.total_prompt_tokens,
            "total_completion_tokens": summary.total_completion_tokens,
            "total_cached_tokens": summary.total_cached_tokens,
            "total_tokens": summary.total_tokens,
            "total_cost_usd": summary.total_cost_usd,
            "call_count": summary.call_count,
            "budget_limit_usd": summary.budget_limit_usd,
            "status": summary.status,
            "is_budget_exceeded": summary.is_budget_exceeded,
            "remaining_budget_usd": summary.remaining_budget_usd,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def persist_call_event(self, record: CostRecord, to_state: str = "active") -> dict[str, Any]:
        """Record a call cost event."""
        payload = self.format_call_event(record, to_state=to_state)
        self.persisted_events.append(payload)
        self._dispatch_to_supabase("agent_events", payload)
        return payload

    def persist_cutoff_event(self, cutoff: BudgetCutoffEvent) -> dict[str, Any]:
        """Record a budget cutoff event and transition state to NEEDS_HUMAN."""
        payload = self.format_budget_cutoff_event(cutoff)
        self.persisted_events.append(payload)
        self._dispatch_to_supabase("agent_events", payload)

        # Notify pipeline event_bus if active
        self._notify_event_bus(cutoff.session_id, "[NEEDS_HUMAN] Budget limit of $0.50 exceeded. Execution stopped.")
        return payload

    def persist_session_summary(self, summary: SessionCostSummary) -> dict[str, Any]:
        """Persist running cumulative summary."""
        payload = self.format_session_summary_payload(summary)
        self.persisted_summaries.append(payload)
        self._dispatch_to_supabase("session_costs", payload)
        return payload

    def _dispatch_to_supabase(self, table: str, payload: dict[str, Any]) -> bool:
        """Helper to post event to Supabase REST API if configured."""
        if self.dry_run or not self.supabase_client_fn:
            return True

        try:
            base_url, service_key = self.supabase_client_fn()
            if not base_url or not service_key or "dummy" in service_key:
                return True

            endpoint = f"{base_url.rstrip('/')}/rest/v1/{table}"
            headers = {
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status in (200, 201, 204)
        except Exception as exc:
            logger.debug("Supabase cost persistence non-fatal exception: %s", exc)
            return False

    def _notify_event_bus(self, run_id: str, message: str) -> None:
        """Best-effort log message into app.agents.event_bus if run_id exists."""
        try:
            from app.agents import event_bus
            run = event_bus.get_run(run_id)
            if run:
                event_bus.update_phase(run_id, "NEEDS_HUMAN", message)
                run["status"] = "NEEDS_HUMAN"
        except Exception:
            pass


# Global default cost persistence service
default_persistence_service = CostPersistenceService()
