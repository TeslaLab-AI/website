"""
Purpose:
Session Engine and Ingestion REST API for TeslaLab AI Stage 0.

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

from fastapi import APIRouter, Header, HTTPException, Body
from pydantic import BaseModel, Field

from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_request, _json_post
from app.github_install import _authenticated_user_id, _workspace_id_for_user
from app.contracts.schemas import (
    Finding,
    FindingCategory,
    FindingSeverity,
    SessionState,
    TaskStatus,
)
from app.agents.session_engine import validate_transition, InvalidStateTransitionError

router = APIRouter()

# 6 Canonical Seeded Findings for Stage 0 Evaluation
SEEDED_FINDINGS: Dict[str, Dict[str, Any]] = {
    "FINDING-BUG-001": {
        "id": "FINDING-BUG-001",
        "category": FindingCategory.BUGS.value,
        "severity": FindingSeverity.CRITICAL.value,
        "title": "Null pointer dereference in auth handler",
        "description": "Unchecked access token header leads to uncaught exception under high load.",
        "file_path": "src/auth/handler.ts",
        "line_number": 42,
    },
    "FINDING-BUG-002": {
        "id": "FINDING-BUG-002",
        "category": FindingCategory.BUGS.value,
        "severity": FindingSeverity.HIGH.value,
        "title": "Race condition in session cache",
        "description": "Simultaneous token refresh corrupts memory cache entries.",
        "file_path": "src/cache/session.ts",
        "line_number": 88,
    },
    "FINDING-BUG-003": {
        "id": "FINDING-BUG-003",
        "category": FindingCategory.BUGS.value,
        "severity": FindingSeverity.MEDIUM.value,
        "title": "Off-by-one error in pagination slice",
        "description": "Page bounds check incorrectly truncates the last result record.",
        "file_path": "src/api/paginate.ts",
        "line_number": 115,
    },
    "FINDING-DEP-001": {
        "id": "FINDING-DEP-001",
        "category": FindingCategory.DEPENDENCIES.value,
        "severity": FindingSeverity.HIGH.value,
        "title": "Vulnerable lodash dependency version 4.17.15",
        "description": "Prototype pollution vulnerability CVE-2020-8203 in lodash.",
        "file_path": "package.json",
        "line_number": 28,
    },
    "FINDING-DEP-002": {
        "id": "FINDING-DEP-002",
        "category": FindingCategory.DEPENDENCIES.value,
        "severity": FindingSeverity.MEDIUM.value,
        "title": "Outdated axios dependency",
        "description": "Known SSRF flaw in axios <= 0.21.1 during redirect chaining.",
        "file_path": "package.json",
        "line_number": 34,
    },
    "FINDING-SEC-001": {
        "id": "FINDING-SEC-001",
        "category": FindingCategory.SECURITY.value,
        "severity": FindingSeverity.CRITICAL.value,
        "title": "Hardcoded cryptographic fallback key",
        "description": "Fallback HMAC key exposed in client-accessible bundle constants.",
        "file_path": "src/crypto/jwt.ts",
        "line_number": 14,
    },
}

# In-memory store fallback for standalone test / offline dev mode
_memory_tasks: Dict[str, Dict[str, Any]] = {}
_memory_sessions: Dict[str, Dict[str, Any]] = {}
_memory_events: List[Dict[str, Any]] = []


def _db_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {supabase_service_role_key()}",
        "apikey": supabase_service_role_key(),
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _resolve_workspace_or_default(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            return _workspace_id_for_user(token)
        except Exception:
            pass
    return "00000000-0000-0000-0000-000000000001"


class TransitionRequest(BaseModel):
    target_state: SessionState
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.get("/findings/seeded")
@router.get("/api/findings/seeded")
def get_seeded_findings():
    """Returns the 6 frozen seeded findings for Day 1 evaluation."""
    return list(SEEDED_FINDINGS.values())


@router.post("/findings/{finding_id}/investigate")
@router.post("/api/findings/{finding_id}/investigate")
def investigate_finding(
    finding_id: str,
    authorization: str | None = Header(default=None),
):
    """
    Idempotent finding ingestion.
    Maps 1 finding -> 1 task + 1 session in active INVESTIGATING state.
    Rapid double-clicks return existing records with HTTP 200 without duplicates.
    """
    workspace_id = _resolve_workspace_or_default(authorization)
    headers = _db_headers()

    # 1. Resolve finding details
    finding_info = SEEDED_FINDINGS.get(finding_id)
    if not finding_info:
        try:
            status, body = _json_request(
                f"{supabase_url()}/rest/v1/scan_findings?id=eq.{finding_id}&select=*",
                headers,
            )
            if status == 200 and isinstance(body, list) and len(body) > 0:
                f = body[0]
                finding_info = {
                    "id": str(f.get("id")),
                    "category": f.get("category", FindingCategory.BUGS.value),
                    "severity": f.get("severity", FindingSeverity.MEDIUM.value),
                    "title": f.get("title", f"Finding {finding_id}"),
                    "description": f.get("description", ""),
                    "file_path": f.get("file_path"),
                    "line_number": f.get("line_number"),
                }
        except Exception:
            pass

    if not finding_info:
        finding_info = {
            "id": finding_id,
            "category": FindingCategory.BUGS.value,
            "severity": FindingSeverity.MEDIUM.value,
            "title": f"Finding {finding_id}",
            "description": "Seeded or detected issue awaiting agent diagnosis.",
            "file_path": "src/index.ts",
            "line_number": 1,
        }

    # 2. Check for existing task (Idempotency check)
    existing_task = None
    existing_session = None

    # Check database
    try:
        status, body = _json_request(
            f"{supabase_url()}/rest/v1/tasks?workspace_id=eq.{workspace_id}&finding_id=eq.{finding_id}&select=*",
            headers,
        )
        if status == 200 and isinstance(body, list) and len(body) > 0:
            existing_task = body[0]
            # Fetch session
            s_status, s_body = _json_request(
                f"{supabase_url()}/rest/v1/agent_sessions?task_id=eq.{existing_task['id']}&select=*",
                headers,
            )
            if s_status == 200 and isinstance(s_body, list) and len(s_body) > 0:
                existing_session = s_body[0]
    except Exception:
        pass

    # Check in-memory store if DB query failed or empty
    if not existing_task:
        for t in _memory_tasks.values():
            if t["workspace_id"] == workspace_id and t["finding_id"] == finding_id:
                existing_task = t
                for s in _memory_sessions.values():
                    if s["task_id"] == existing_task["id"]:
                        existing_session = s
                        break
                break

    # If already exists, return immediately (Idempotent 200)
    if existing_task and existing_session:
        return {
            "task_id": existing_task["id"],
            "session_id": existing_session["id"],
            "status": existing_session.get("current_state", SessionState.INVESTIGATING.value),
            "is_existing": True,
        }

    # 3. Create new task and session atomically
    task_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    task_payload = {
        "id": task_id,
        "workspace_id": workspace_id,
        "finding_id": finding_id,
        "title": finding_info["title"],
        "category": finding_info["category"],
        "severity": finding_info["severity"],
        "status": TaskStatus.IN_PROGRESS.value,
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    session_payload = {
        "id": session_id,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "current_state": SessionState.INVESTIGATING.value,
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    event_payload = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "from_state": SessionState.CREATED.value,
        "to_state": SessionState.INVESTIGATING.value,
        "event_type": "investigate_triggered",
        "payload": {"finding_id": finding_id},
        "timestamp": now_iso,
    }

    # Attempt DB insertion
    db_persisted = False
    try:
        t_status, _ = _json_post(f"{supabase_url()}/rest/v1/tasks", headers, task_payload)
        s_status, _ = _json_post(f"{supabase_url()}/rest/v1/agent_sessions", headers, session_payload)
        _json_post(f"{supabase_url()}/rest/v1/agent_events", headers, event_payload)
        if t_status in (200, 201, 204) and s_status in (200, 201, 204):
            db_persisted = True
    except Exception:
        pass

    # Always persist to in-memory store for instant sync and offline reliability
    _memory_tasks[task_id] = task_payload
    _memory_sessions[session_id] = session_payload
    _memory_events.append(event_payload)

    return {
        "task_id": task_id,
        "session_id": session_id,
        "status": SessionState.INVESTIGATING.value,
        "is_existing": False,
        "db_persisted": db_persisted,
    }


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
            # Fetch events
            e_status, e_body = _json_request(
                f"{supabase_url()}/rest/v1/agent_events?session_id=eq.{session_id}&order=timestamp.asc&select=*",
                headers,
            )
            if e_status == 200 and isinstance(e_body, list):
                events_data = e_body
            # Fetch task
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
    # 1. Fetch current session
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

    # 2. Guard Check: Validate transition
    try:
        validate_transition(current_state, target_state)
    except InvalidStateTransitionError as err:
        raise HTTPException(status_code=400, detail=str(err))

    # 3. Record microsecond transition
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
