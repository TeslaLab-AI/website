"""
TeslaLab AI — Agent 1: Diagnosis & Foundation Lead
Module: Asynchronous Event Bus & Streaming Infrastructure (Day 2 · Task 4).

Responsibilities:
- Strongly-typed structured agent event emission:
  SESSION_STARTED, SEARCHING_REPOSITORY, READING_FILE, HYPOTHESIS_GENERATED,
  PLAN_CREATED, CODE_MODIFIED, TESTS_RUNNING, PR_OPENED, state_transition.
- Non-blocking pub/sub dispatch to WebSocket / SSE subscribers.
- Asynchronous database persistence to `public.agent_events` table (<20ms latency).
- Fault isolation: streaming and persistence failures never block agent execution.
"""

from __future__ import annotations
import sys
import uuid
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set, List, Tuple

# Synchronize namespaces
if __name__ == "agents.agent_1.event_bus":
    sys.modules["backend.agents.agent_1.event_bus"] = sys.modules[__name__]
elif __name__ == "backend.agents.agent_1.event_bus":
    sys.modules["agents.agent_1.event_bus"] = sys.modules[__name__]

import httpx

from app.contracts.schemas import AgentEventType, SessionState, AgentEvent
from app.config import supabase_url, supabase_service_role_key
from agents.agent_1.finding_ingestion import _memory_events, _db_headers


class AsyncEventBus:
    """
    High-throughput asynchronous EventBus providing transparent observability.
    Dispatches typed events to real-time subscribers and persists to database.
    """

    def __init__(self) -> None:
        # session_id -> Set[Tuple[asyncio.Queue, Optional[asyncio.AbstractEventLoop]]]
        self._subscribers: Dict[
            str, Set[Tuple[asyncio.Queue, Optional[asyncio.AbstractEventLoop]]]
        ] = defaultdict(set)

        # session_id -> list of historic events
        self._history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        # Persistent HTTP client for connection pooling
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=5.0)
        return self._client

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """Subscribes an async queue to receive live events for a session."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._subscribers[session_id].add((queue, loop))
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        """Removes subscriber queue cleanly to prevent resource leaks."""
        if session_id in self._subscribers:
            self._subscribers[session_id] = {
                item for item in self._subscribers[session_id] if item[0] != queue
            }
            if not self._subscribers[session_id]:
                del self._subscribers[session_id]

    def _dispatch_to_subscribers(self, session_id: str, event_record: Dict[str, Any]) -> None:
        """Thread-safe fan-out to all active subscribers."""
        subs: List[Tuple[asyncio.Queue, Optional[asyncio.AbstractEventLoop]]] = list(
            self._subscribers.get(session_id, set())
        )
        try:
            running_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        for q, loop in subs:

            try:
                if loop and not loop.is_closed():
                    if running_loop is loop:
                        try:
                            q.put_nowait(event_record)
                        except asyncio.QueueFull:
                            try:
                                q.get_nowait()
                                q.put_nowait(event_record)
                            except Exception:
                                pass
                    else:
                        loop.call_soon_threadsafe(q.put_nowait, event_record)
                else:
                    q.put_nowait(event_record)
            except Exception:
                pass

    async def _persist_to_db(self, event_record: Dict[str, Any]) -> None:
        """
        Asynchronously writes event to public.agent_events table.
        Gracefully isolated: DB timeouts or connection issues will never crash the caller.
        """
        try:
            url = f"{supabase_url()}/rest/v1/agent_events"
            headers = _db_headers()
            client = await self._get_client()
            response = await client.post(url, headers=headers, json=event_record)
            if response.status_code >= 400:
                pass
        except Exception:
            pass

    async def emit(
        self,
        session_id: str,
        event_type: AgentEventType | str,
        payload: Optional[Dict[str, Any]] = None,
        from_state: SessionState | str = SessionState.INVESTIGATING,
        to_state: SessionState | str = SessionState.INVESTIGATING,
    ) -> Dict[str, Any]:
        """
        Formats, dispatches, and persists a structured agent event.
        Guarantees non-blocking execution (<1ms dispatcher latency).
        """
        now_microsecond_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        event_id = str(uuid.uuid4())

        from_state_val = from_state.value if hasattr(from_state, "value") else str(from_state)
        to_state_val = to_state.value if hasattr(to_state, "value") else str(to_state)
        type_val = event_type.value if hasattr(event_type, "value") else str(event_type)

        event_record: Dict[str, Any] = {
            "id": event_id,
            "session_id": session_id,
            "from_state": from_state_val,
            "to_state": to_state_val,
            "event_type": type_val,
            "payload": payload or {},
            "timestamp": now_microsecond_iso,
        }

        # 1. Update in-memory stores immediately
        self._history[session_id].append(event_record)
        _memory_events.append(event_record)

        # 2. Non-blocking fan-out to all active subscribers
        self._dispatch_to_subscribers(session_id, event_record)

        # 3. Non-blocking background DB persistence
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_to_db(event_record))
        except RuntimeError:
            pass

        return event_record

    def emit_sync(
        self,
        session_id: str,
        event_type: AgentEventType | str,
        payload: Optional[Dict[str, Any]] = None,
        from_state: SessionState | str = SessionState.INVESTIGATING,
        to_state: SessionState | str = SessionState.INVESTIGATING,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for emitting events from non-async contexts."""
        now_microsecond_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        event_id = str(uuid.uuid4())

        from_state_val = from_state.value if hasattr(from_state, "value") else str(from_state)
        to_state_val = to_state.value if hasattr(to_state, "value") else str(to_state)
        type_val = event_type.value if hasattr(event_type, "value") else str(event_type)

        event_record: Dict[str, Any] = {
            "id": event_id,
            "session_id": session_id,
            "from_state": from_state_val,
            "to_state": to_state_val,
            "event_type": type_val,
            "payload": payload or {},
            "timestamp": now_microsecond_iso,
        }

        self._history[session_id].append(event_record)
        _memory_events.append(event_record)

        # Non-blocking fan-out to active subscribers
        self._dispatch_to_subscribers(session_id, event_record)

        # Schedule background persistence if loop is available
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_to_db(event_record))
        except RuntimeError:
            pass

        return event_record


    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Returns ordered event history for a given session."""
        if session_id in self._history:
            return list(self._history[session_id])
        return [e for e in _memory_events if e.get("session_id") == session_id]


# Canonical Global Singleton Event Bus Instance
event_bus = AsyncEventBus()
