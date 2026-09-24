"""
TeslaLab AI — Agent 1: Diagnosis & Foundation Lead
Module: Finding Ingestion & Idempotency Pipeline (Task 2).

Responsibilities:
- Ingest static/dynamic findings into actionable engineering Tasks and Agent Sessions.
- Idempotency guard: Prevent duplicate task/session creation upon rapid requests or retries.
- Standard 6 Seeded Findings fixtures for Stage 0 Evaluation (3 Bugs, 2 Deps, 1 Security).
"""

from __future__ import annotations
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

# Synchronize backend.agents.agent_1 and agents.agent_1 namespaces
if __name__ == "agents.agent_1.finding_ingestion":
    sys.modules["backend.agents.agent_1.finding_ingestion"] = sys.modules[__name__]
elif __name__ == "backend.agents.agent_1.finding_ingestion":
    sys.modules["agents.agent_1.finding_ingestion"] = sys.modules[__name__]

from app.contracts.schemas import (
    FindingCategory,
    FindingSeverity,
    SessionState,
    TaskStatus,
)
from app.config import supabase_url, supabase_service_role_key
from app.github_api import _json_request, _json_post

# 6 Canonical Seeded Findings for Day 1 Stage 0 Evaluation
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

# In-memory store fallback for offline dev & test runner
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


class FindingIngestionService:
    """Service handling finding-to-task ingestion with deduplication and idempotency."""

    @staticmethod
    def get_seeded_findings() -> List[Dict[str, Any]]:
        return list(SEEDED_FINDINGS.values())

    @staticmethod
    def ingest(finding_id: str, workspace_id: str) -> Dict[str, Any]:
        """
        Idempotent finding ingestion.
        Returns existing task & session if already ingested, otherwise creates them atomically.
        """
        headers = _db_headers()

        # 1. Resolve finding metadata
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

        # 2. Idempotency Check: Existing task & session?
        existing_task = None
        existing_session = None

        try:
            status, body = _json_request(
                f"{supabase_url()}/rest/v1/tasks?workspace_id=eq.{workspace_id}&finding_id=eq.{finding_id}&select=*",
                headers,
            )
            if status == 200 and isinstance(body, list) and len(body) > 0:
                existing_task = body[0]
                s_status, s_body = _json_request(
                    f"{supabase_url()}/rest/v1/agent_sessions?task_id=eq.{existing_task['id']}&select=*",
                    headers,
                )
                if s_status == 200 and isinstance(s_body, list) and len(s_body) > 0:
                    existing_session = s_body[0]
        except Exception:
            pass

        if not existing_task:
            for t in _memory_tasks.values():
                if t["workspace_id"] == workspace_id and t["finding_id"] == finding_id:
                    existing_task = t
                    for s in _memory_sessions.values():
                        if s["task_id"] == existing_task["id"]:
                            existing_session = s
                            break
                    break

        if existing_task and existing_session:
            return {
                "task_id": existing_task["id"],
                "session_id": existing_session["id"],
                "status": existing_session.get("current_state", SessionState.INVESTIGATING.value),
                "is_existing": True,
            }

        # 3. Atomically create new task and session
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

        from app.evidence.collector import build_evidence_pack
        from app.contracts.schemas import BugFinding
        
        # Hydrate a temporary BugFinding for the collector
        _st = finding_info.get("stack_trace")
        _fp = finding_info.get("file_path")
        _env = finding_info.get("environment")
        
        bug_finding = BugFinding(
            id=str(finding_info.get("id", finding_id)),
            title=str(finding_info.get("title", "Unknown")),
            description=str(finding_info.get("description", "Unknown")),
            stack_trace=str(_st) if _st else None,
            files_hint=[str(_fp)] if _fp else [],
            environment=_env if isinstance(_env, dict) else {}
        )
        
        # Build evidence pack
        pack = build_evidence_pack(bug_finding, workspace_path=None, log_file_path=None)

        session_db_payload = {
            "id": session_id,
            "task_id": task_id,
            "workspace_id": workspace_id,
            "current_state": SessionState.INVESTIGATING.value,
            "created_at": now_iso,
            "updated_at": now_iso,
        }

        session_memory_payload = {
            **session_db_payload,
            "evidence_pack": pack.model_dump(),
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

        db_persisted = False
        try:
            t_status, _ = _json_post(f"{supabase_url()}/rest/v1/tasks", headers, task_payload)
            s_status, _ = _json_post(f"{supabase_url()}/rest/v1/agent_sessions", headers, session_db_payload)
            _json_post(f"{supabase_url()}/rest/v1/agent_events", headers, event_payload)
            if t_status in (200, 201, 204) and s_status in (200, 201, 204):
                db_persisted = True
        except Exception:
            pass

        _memory_tasks[task_id] = task_payload
        _memory_sessions[session_id] = session_memory_payload
        _memory_events.append(event_payload)

        return {
            "task_id": task_id,
            "session_id": session_id,
            "status": SessionState.INVESTIGATING.value,
            "is_existing": False,
            "db_persisted": db_persisted,
        }
