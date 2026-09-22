"""
Purpose:
Tests for Day 4 Shared Contracts and Data Models (Tasks 40–42).
Verifies serialization, enum validity, and constraints for:
- UnifiedFinding & FindingContext (Task 40)
- ManualControlCommand & ManualAction (Task 41)
- MemoryRecord & ContextPack (Task 42)
"""

import pytest
from agents.agent_3.day4_models import (
    FindingCategory,
    UnifiedFinding,
    FindingContext,
    ManualAction,
    ManualControlCommand,
    MemoryRecord,
    ContextPack,
)


def test_unified_finding_and_context_models():
    """Verifies UnifiedFinding canonical schema and FindingContext state tracking."""
    finding = UnifiedFinding(
        finding_id="BUG-PAGINATE-01",
        category=FindingCategory.BUG,
        title="Pagination slice boundary off-by-one",
        description="Fails when page_size=5",
        severity="HIGH",
        target_files=["src/catalog/paginate.py"],
        repo_id="repo_main",
        metadata={"defect": "OFF_BY_ONE"},
    )
    assert finding.category == FindingCategory.BUG
    assert finding.finding_id == "BUG-PAGINATE-01"
    assert finding.target_files == ["src/catalog/paginate.py"]

    context = FindingContext(
        session_id="session-find-01",
        finding=finding,
        stage="ANALYSIS",
    )
    assert context.session_id == "session-find-01"
    assert context.stage == "ANALYSIS"
    assert len(context.execution_trace) == 0

    payload = context.model_dump()
    assert payload["finding"]["category"] == "BUG"


def test_manual_control_command_model():
    """Verifies ManualControlCommand and all 7 explicit manual actions per Task 41."""
    # Test all 7 explicit enum values exist
    expected_actions = [
        "INVESTIGATE",
        "REVIEW_DIAGNOSIS",
        "EDIT_PLAN",
        "APPROVE_EXECUTION",
        "REVIEW_DIFF",
        "RETRY",
        "OPEN_PR",
    ]
    for act_name in expected_actions:
        assert hasattr(ManualAction, act_name)

    cmd = ManualControlCommand(
        session_id="session-ctrl-01",
        action=ManualAction.EDIT_PLAN,
        authorized=True,
        edited_plan='{"target": "src/catalog/paginate.py", "action": "fix_slice"}',
        notes="Operator adjusted upper slice bound",
    )
    assert cmd.action == ManualAction.EDIT_PLAN
    assert cmd.authorized is True
    assert "fix_slice" in cmd.edited_plan


def test_memory_models_and_context_pack():
    """Verifies MemoryRecord and ContextPack schemas per Task 42."""
    record = MemoryRecord(
        task_id="TASK-MEM-01",
        repo_id="repo_alpha",
        finding_type="BUG",
        root_cause_pattern="Database connection timeout",
        solution_pattern="Set pool_timeout=30.0",
        affected_files=["src/db/connection.py"],
        outcome="SUCCESS",
        embedding=[0.12, 0.45, -0.23, 0.88],
    )
    assert record.repo_id == "repo_alpha"
    assert record.outcome == "SUCCESS"
    assert len(record.embedding) == 4

    pack = ContextPack(
        finding_id="BUG-DB-02",
        repo_id="repo_alpha",
        retrieved_memories=[record],
        relevant_files=["src/db/client.py"],
        few_shot_context="Example 1: Resolved connection pool timeout with pool_timeout=30.0",
    )
    assert pack.finding_id == "BUG-DB-02"
    assert len(pack.retrieved_memories) == 1
    assert "pool_timeout=30.0" in pack.few_shot_context
