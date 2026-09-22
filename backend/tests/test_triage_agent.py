import time
import json
import os
import pytest
from app.contracts.schemas import BugFinding
from agents.agent_1.triage_agent import TriageAgent

# Mock findings for benchmarking
BUGS = [
    {
        "id": "BUG-001",
        "title": "Database connection timeout in prod",
        "description": "Getting a psycopg2.OperationalError randomly in production when traffic spikes.",
        "stack_trace": "psycopg2.OperationalError: FATAL: remaining connection slots are reserved",
        "files_hint": ["backend/app/db.py"]
    },
    {
        "id": "BUG-002",
        "title": "Login button unresponsive",
        "description": "User clicks login button and nothing happens on the frontend. No errors in console.",
        "stack_trace": None,
        "files_hint": ["frontend/components/Login.tsx"]
    },
    {
        "id": "BUG-003",
        "title": "Cannot read property 'map' of undefined",
        "description": "Crash when rendering the dashboard page.",
        "stack_trace": "TypeError: Cannot read property 'map' of undefined at Dashboard (Dashboard.tsx:45)",
        "files_hint": ["frontend/pages/Dashboard.tsx"]
    },
    {
        "id": "BUG-004",
        "title": "Vague issue, something is broken",
        "description": "It doesn't work.",
        "stack_trace": None,
        "files_hint": []
    },
    {
        "id": "BUG-005",
        "title": "Migrate from Redis to Memcached",
        "description": "We need to rewrite our entire caching layer to use Memcached instead of Redis.",
        "stack_trace": None,
        "files_hint": []
    }
]

@pytest.fixture
def agent():
    return TriageAgent(model_name="gpt-4o-mini", temperature=0.0)

def test_triage_benchmark(agent):
    reports = []
    for bug_data in BUGS:
        finding = BugFinding(
            id=str(bug_data["id"]),
            title=str(bug_data["title"]),
            description=str(bug_data["description"]),
            stack_trace=str(bug_data["stack_trace"]) if bug_data["stack_trace"] else None,
            files_hint=list(bug_data["files_hint"]) if isinstance(bug_data["files_hint"], list) else []
        )
        
        start_time = time.time()
        report = agent.run_triage(finding)
        duration = time.time() - start_time
        
        assert duration < 10.0, f"Triage took {duration}s for {finding.id} (limit 10s)"
        
        # Verify schema is populated
        assert hasattr(report, "severity")
        assert hasattr(report, "subsystem")
        assert isinstance(report.auto_fix_feasible, bool)
        
        # Specific assertions for vague/architectural issues
        if bug_data["id"] == "BUG-004":
            assert not report.is_reproducible, "Vague bug should not be reproducible"
            assert not report.auto_fix_feasible, "Vague bug should not be auto-fixable"
        if bug_data["id"] == "BUG-005":
            assert not report.auto_fix_feasible, "Architectural migration should not be auto-fixable"
            
        reports.append({
            "finding_id": finding.id,
            "duration": duration,
            "triage_report": report.model_dump()
        })
        
    os.makedirs("evidence", exist_ok=True)
    with open("evidence/task10_triage_reports.json", "w") as f:
        json.dump(reports, f, indent=2)
