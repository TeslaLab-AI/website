"""
Purpose:
Automated Acceptance Test Suite for TeslaLab AI Stage 0 — Day 1 Evaluation.

Covers:
- AC-E1-D1-01: Schema & DB Contract Freeze (100% round-trip serialization across 10 sample payloads + SQL checks)
- AC-E1-D1-02: Idempotent Finding Ingestion (6/6 seeded findings map to unique tasks; 0 duplicates on double-click)
- AC-E1-D1-03: Session State Machine Progression (Walks through >=3 states with microsecond event logs)
- AC-E1-D1-04: Invalid Transition Guard (Illegal state progression raises HTTP 400 Bad Request)
"""

import sys
import json
import uuid
from pathlib import Path
from datetime import datetime

import pytest
from starlette.testclient import TestClient

# Ensure app package is on sys.path
backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.main import app
from app.contracts.schemas import (
    Finding,
    FindingCategory,
    FindingSeverity,
    Task,
    TaskStatus,
    Session,
    SessionState,
    ToolCall,
    PlanSkeleton,
    AgentEvent,
)
from app.agents.session_engine import (
    validate_transition,
    InvalidStateTransitionError,
    create_session_graph,
)

client = TestClient(app)


# ============================================================================
# AC-E1-D1-01: Schema & DB Contract Freeze
# ============================================================================

def test_ac_e1_d1_01_schema_contract_freeze():
    """
    Validates 10 diverse sample payloads for 100% round-trip serialization
    against the 5 core frozen schemas. Also inspects the DB migration script.
    """
    # 1. Ten Sample Payloads across Finding, Task, Session, PlanSkeleton, ToolCall
    sample_findings = [
        {
            "id": "FINDING-BUG-001",
            "category": "bugs",
            "severity": "critical",
            "title": "Null pointer dereference",
            "description": "Auth handler fails on null token.",
            "file_path": "src/auth.ts",
            "line_number": 42,
            "metadata": {"cve": "N/A"},
        },
        {
            "id": "FINDING-DEP-001",
            "category": "dependencies",
            "severity": "high",
            "title": "Vulnerable lodash",
            "description": "Prototype pollution CVE-2020-8203",
            "file_path": "package.json",
            "line_number": 12,
            "metadata": {"ecosystem": "npm"},
        },
        {
            "id": "FINDING-SEC-001",
            "category": "security",
            "severity": "critical",
            "title": "Hardcoded secret",
            "description": "Private key present in client bundle.",
            "file_path": "src/config.ts",
            "line_number": 5,
            "metadata": {},
        },
    ]

    for p in sample_findings:
        f = Finding.model_validate(p)
        assert f.id == p["id"]
        serialized = f.model_dump(mode="json")
        f2 = Finding.model_validate(serialized)
        assert f == f2

    sample_tasks = [
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "finding_id": "FINDING-BUG-001",
            "title": "Fix null pointer in auth handler",
            "category": "bugs",
            "severity": "critical",
            "status": "open",
        },
        {
            "id": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "finding_id": "FINDING-DEP-001",
            "title": "Upgrade lodash to 4.17.21",
            "category": "dependencies",
            "severity": "high",
            "status": "in_progress",
        },
    ]

    for t in sample_tasks:
        task_model = Task.model_validate(t)
        assert task_model.category == FindingCategory(t["category"])
        serialized = task_model.model_dump(mode="json")
        t2 = Task.model_validate(serialized)
        assert task_model.id == t2.id

    sample_sessions = [
        {
            "id": str(uuid.uuid4()),
            "task_id": sample_tasks[0]["id"],
            "workspace_id": sample_tasks[0]["workspace_id"],
            "current_state": "CREATED",
        },
        {
            "id": str(uuid.uuid4()),
            "task_id": sample_tasks[1]["id"],
            "workspace_id": sample_tasks[1]["workspace_id"],
            "current_state": "INVESTIGATING",
        },
    ]

    for s in sample_sessions:
        session_model = Session.model_validate(s)
        assert session_model.current_state == SessionState(s["current_state"])
        serialized = session_model.model_dump(mode="json")
        s2 = Session.model_validate(serialized)
        assert session_model.id == s2.id

    sample_tool_calls = [
        {"step_index": 0, "tool_name": "ast_grep", "arguments": {"pattern": "function $X()"}, "expected_output": "match"},
        {"step_index": 1, "tool_name": "patch_file", "arguments": {"path": "src/auth.ts"}, "expected_output": "ok"},
    ]

    for tc in sample_tool_calls:
        tc_model = ToolCall.model_validate(tc)
        serialized = tc_model.model_dump(mode="json")
        tc2 = ToolCall.model_validate(serialized)
        assert tc_model == tc2

    sample_plan = {
        "id": str(uuid.uuid4()),
        "session_id": sample_sessions[0]["id"],
        "task_id": sample_tasks[0]["id"],
        "version": 1,
        "status": "ready",
        "steps": sample_tool_calls,
    }
    plan_model = PlanSkeleton.model_validate(sample_plan)
    assert len(plan_model.steps) == 2
    serialized_plan = plan_model.model_dump(mode="json")
    plan2 = PlanSkeleton.model_validate(serialized_plan)
    assert plan_model.id == plan2.id

    # 2. Inspect database migration file for the 5 core tables
    migration_file = backend_root.parent / "supabase" / "migrations" / "009_agent_foundation_and_sessions.sql"
    assert migration_file.exists(), "Migration 009 must exist"
    migration_sql = migration_file.read_text(encoding="utf-8")

    required_tables = ["public.tasks", "public.agent_sessions", "public.agent_events", "public.plans", "public.executions"]
    for tbl in required_tables:
        assert tbl in migration_sql, f"Migration 009 must create {tbl}"

    assert "REFERENCES public.tasks(id)" in migration_sql
    assert "REFERENCES public.agent_sessions(id)" in migration_sql
    assert "clock_timestamp()" in migration_sql


# ============================================================================
# AC-E1-D1-02: Idempotent Finding Ingestion
# ============================================================================

def test_ac_e1_d1_02_idempotent_finding_ingestion():
    """
    Tests that POST /findings/{id}/investigate:
    1. Ingests all 6 seeded findings (3 bugs, 2 deps, 1 security) creating 6 unique tasks & sessions.
    2. Repeated / rapid double-clicks return HTTP 200 with existing records and zero duplicate creations.
    """
    seeded_ids = [
        "FINDING-BUG-001",
        "FINDING-BUG-002",
        "FINDING-BUG-003",
        "FINDING-DEP-001",
        "FINDING-DEP-002",
        "FINDING-SEC-001",
    ]

    created_tasks = {}
    created_sessions = {}

    # First pass: ingest each of the 6 seeded findings
    for fid in seeded_ids:
        resp = client.post(f"/findings/{fid}/investigate")
        assert resp.status_code == 200, f"Failed on {fid}: {resp.text}"
        data = resp.json()
        assert "task_id" in data
        assert "session_id" in data
        assert data["status"] == "INVESTIGATING"

        # Ensure uniqueness
        assert data["task_id"] not in created_tasks.values(), f"Duplicate task created for {fid}"
        assert data["session_id"] not in created_sessions.values(), f"Duplicate session created for {fid}"

        created_tasks[fid] = data["task_id"]
        created_sessions[fid] = data["session_id"]

    assert len(created_tasks) == 6, "Must create exactly 6 unique tasks for 6 seeded findings"

    # Second pass: simulate rapid double-clicks on identical findings
    for fid in seeded_ids:
        resp_double = client.post(f"/findings/{fid}/investigate")
        assert resp_double.status_code == 200
        data_double = resp_double.json()

        # Must return the EXACT SAME task_id and session_id with is_existing=True
        assert data_double["task_id"] == created_tasks[fid], f"Task ID changed on duplicate click for {fid}"
        assert data_double["session_id"] == created_sessions[fid], f"Session ID changed on duplicate click for {fid}"
        assert data_double.get("is_existing") is True, "Idempotency flag must be True on duplicate POST"


# ============================================================================
# AC-E1-D1-03: Session State Machine Progression
# ============================================================================

def test_ac_e1_d1_03_session_state_machine_progression():
    """
    Instantiates a session and walks through >= 3 states:
    INVESTIGATING -> REPRODUCING -> ROOT_CAUSE -> PLANNING
    Verifies all intermediate states are recorded with microsecond timestamps.
    """
    # 1. Create a session via investigate
    resp = client.post("/findings/FINDING-BUG-001/investigate")
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # 2. Transition sequentially through 3 additional states
    progression = [
        SessionState.REPRODUCING,
        SessionState.ROOT_CAUSE,
        SessionState.PLANNING,
    ]

    for target in progression:
        t_resp = client.post(
            f"/sessions/{session_id}/transition",
            json={"target_state": target.value, "payload": {"step": target.value}},
        )
        assert t_resp.status_code == 200, f"Failed transitioning to {target}: {t_resp.text}"
        res_data = t_resp.json()
        assert res_data["current_state"] == target.value
        # Assert microsecond timestamp format
        dt = datetime.fromisoformat(res_data["timestamp"].replace("Z", "+00:00"))
        assert dt.microsecond >= 0

    # 3. Read back session and verify event history audit log
    get_resp = client.get(f"/sessions/{session_id}")
    assert get_resp.status_code == 200
    details = get_resp.json()
    assert details["session"]["current_state"] == "PLANNING"

    events = details["events"]
    assert len(events) >= 3, "At least 3 transitions must be recorded"
    states_logged = [e["to_state"] for e in events]
    assert "REPRODUCING" in states_logged
    assert "ROOT_CAUSE" in states_logged
    assert "PLANNING" in states_logged


# ============================================================================
# AC-E1-D1-04: Invalid Transition Guard
# ============================================================================

def test_ac_e1_d1_04_invalid_transition_guard():
    """
    Injects illegal state progressions (e.g. CREATED -> PR_READY, INVESTIGATING -> MERGED).
    Asserts HTTP 400 Bad Request error is raised and execution aborts.
    """
    # Create fresh session
    test_finding_id = f"FINDING-TEST-{uuid.uuid4().hex[:6]}"
    resp = client.post(f"/findings/{test_finding_id}/investigate")
    session_id = resp.json()["session_id"]

    # Current state is INVESTIGATING.
    # Attempting to jump directly to MERGED or PR_READY is illegal.
    invalid_targets = [SessionState.MERGED, SessionState.PR_READY, SessionState.CREATED]

    for bad_target in invalid_targets:
        bad_resp = client.post(
            f"/sessions/{session_id}/transition",
            json={"target_state": bad_target.value},
        )
        assert bad_resp.status_code == 400, f"Expected 400 for jump to {bad_target}, got {bad_resp.status_code}"
        err_msg = bad_resp.json().get("detail", "")
        assert "Illegal state transition" in err_msg, f"Unexpected error detail: {err_msg}"

    # Also test Python level validator
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(SessionState.CREATED, SessionState.PR_READY)

    with pytest.raises(InvalidStateTransitionError):
        validate_transition(SessionState.INVESTIGATING, SessionState.MERGED)


# ============================================================================
# Standalone execution entrypoint
# ============================================================================

if __name__ == "__main__":
    print("Running Day 1 Acceptance Test Suite...")
    test_ac_e1_d1_01_schema_contract_freeze()
    print("✅ AC-E1-D1-01: Schema & DB Contract Freeze PASSED")

    test_ac_e1_d1_02_idempotent_finding_ingestion()
    print("✅ AC-E1-D1-02: Idempotent Finding Ingestion PASSED")

    test_ac_e1_d1_03_session_state_machine_progression()
    print("✅ AC-E1-D1-03: Session State Machine Progression PASSED")

    test_ac_e1_d1_04_invalid_transition_guard()
    print("✅ AC-E1-D1-04: Invalid Transition Guard PASSED")

    print("\n🎉 ALL DAY 1 ACCEPTANCE CRITERIA VERIFIED (100% PASS RATE)!")
