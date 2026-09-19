"""
Purpose:
Session Engine and Ingestion REST API for TeslaLab AI Stage 0.
Delegates core ingestion and state logic directly to canonical Agent 1 modules:
- agents.agent_1.finding_ingestion
- agents.agent_1.session_engine
- agents.agent_1.state_models

Responsibilities:
- POST /findings/{id}/investigate: Idempotent finding-to-task ingestion creating tasks & sessions.
- GET /sessions/{id}: Read session state, associated task, and chronological event audit log.
- POST /sessions/{id}/transition: Validates legal state transitions, logs microsecond event, and updates state.
- GET /findings/seeded: Supplies the 6 standard seeded findings (3 Bugs, 2 Deps, 1 Security).
"""

from __future__ import annotations
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from fastapi import APIRouter, Header, HTTPException

from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_request, _json_post
from app.github_install import _workspace_id_for_user
from app.contracts.schemas import SessionState
from agents.agent_1 import (
    FindingIngestionService,
    SEEDED_FINDINGS,
    validate_transition,
    InvalidStateTransitionError,
    TransitionRequest,
)
from agents.agent_1.finding_ingestion import (
    _memory_tasks,
    _memory_sessions,
    _memory_events,
    _db_headers,
)

router = APIRouter()


def _resolve_workspace_or_default(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            return _workspace_id_for_user(token)
        except Exception:
            pass
    return "00000000-0000-0000-0000-000000000001"


@router.get("/findings/seeded")
@router.get("/api/findings/seeded")
def get_seeded_findings():
    """Returns the 6 frozen seeded findings for Day 1 evaluation."""
    return FindingIngestionService.get_seeded_findings()


@router.post("/findings/{finding_id}/investigate")
@router.post("/api/findings/{finding_id}/investigate")
def investigate_finding(
    finding_id: str,
    authorization: str | None = Header(default=None),
):
    """
    Idempotent finding ingestion.
    Delegates to Agent 1 FindingIngestionService to map 1 finding -> 1 task + 1 session.
    """
    workspace_id = _resolve_workspace_or_default(authorization)
    return FindingIngestionService.ingest(finding_id, workspace_id)


@router.get("/sessions/{session_id}")
@router.get("/api/sessions/{session_id}")
def get_session(session_id: str, authorization: str | None = Header(default=None)):
    """Fetches single source of truth for session state and microsecond event logs."""
    headers = _db_headers()
    session_data = None
    events_data: List[Dict[str, Any]] = []
    task_data = None

    # Try DB lookup
    try:
        s_status, s_body = _json_request(
            f"{supabase_url()}/rest/v1/agent_sessions?id=eq.{session_id}&select=*",
            headers,
        )
        if s_status == 200 and isinstance(s_body, list) and len(s_body) > 0:
            session_data = s_body[0]
            e_status, e_body = _json_request(
                f"{supabase_url()}/rest/v1/agent_events?session_id=eq.{session_id}&order=timestamp.asc&select=*",
                headers,
            )
            if e_status == 200 and isinstance(e_body, list):
                events_data = e_body
            t_status, t_body = _json_request(
                f"{supabase_url()}/rest/v1/tasks?id=eq.{session_data['task_id']}&select=*",
                headers,
            )
            if t_status == 200 and isinstance(t_body, list) and len(t_body) > 0:
                task_data = t_body[0]
    except Exception:
        pass

    # Fallback to in-memory store
    if not session_data and session_id in _memory_sessions:
        session_data = _memory_sessions[session_id]
        task_id = session_data["task_id"]
        task_data = _memory_tasks.get(task_id)
        events_data = [e for e in _memory_events if e["session_id"] == session_id]

    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session": session_data,
        "task": task_data,
        "events": events_data,
    }


@router.post("/sessions/{session_id}/transition")
@router.post("/api/sessions/{session_id}/transition")
def transition_session(
    session_id: str,
    body: TransitionRequest,
    authorization: str | None = Header(default=None),
):
    """
    Executes a validated state transition in the 13-state machine.
    Illegal state jumps raise HTTP 400 Bad Request.
    """
    headers = _db_headers()
    session_data = None

    try:
        s_status, s_body = _json_request(
            f"{supabase_url()}/rest/v1/agent_sessions?id=eq.{session_id}&select=*",
            headers,
        )
        if s_status == 200 and isinstance(s_body, list) and len(s_body) > 0:
            session_data = s_body[0]
    except Exception:
        pass

    if not session_data and session_id in _memory_sessions:
        session_data = _memory_sessions[session_id]

    if not session_data:
        raise HTTPException(status_code=404, detail="Session not found")

    current_state_str = session_data.get("current_state", SessionState.CREATED.value)
    current_state = SessionState(current_state_str)
    target_state = body.target_state

    # Guard Check: Validate transition via Agent 1 engine
    try:
        validate_transition(current_state, target_state)
    except InvalidStateTransitionError as err:
        raise HTTPException(status_code=400, detail=str(err))

    # Record microsecond transition
    now_microsecond_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    event_id = str(uuid.uuid4())

    event_payload = {
        "id": event_id,
        "session_id": session_id,
        "from_state": current_state.value,
        "to_state": target_state.value,
        "event_type": "state_transition",
        "payload": body.payload,
        "timestamp": now_microsecond_iso,
    }

    # Update in DB
    try:
        patch_headers = {**headers, "Content-Type": "application/json"}
        _json_request(
            f"{supabase_url()}/rest/v1/agent_sessions?id=eq.{session_id}",
            patch_headers,
            method="PATCH",
            data=json.dumps({
                "current_state": target_state.value,
                "updated_at": now_microsecond_iso,
            }).encode("utf-8"),
        )
        _json_post(f"{supabase_url()}/rest/v1/agent_events", headers, event_payload)
    except Exception:
        pass

    # Update in-memory store
    if session_id in _memory_sessions:
        _memory_sessions[session_id]["current_state"] = target_state.value
        _memory_sessions[session_id]["updated_at"] = now_microsecond_iso
    _memory_events.append(event_payload)

    return {
        "session_id": session_id,
        "previous_state": current_state.value,
        "current_state": target_state.value,
        "timestamp": now_microsecond_iso,
    }
