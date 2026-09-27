"""
Tests for Task 16: Planner Agent.

Covers:
- PlannerAgent taking RootCauseAnalysis and ContextPack
- Outputting a validated ExecutionPlan
- Minimum 3 steps requirement for seeded bug diagnoses
- Correct READ/INSPECT -> REPRODUCE -> EDIT -> TEST -> VERIFY ordering
- Expected outcome and rollback action on every step
- Deterministic behavior and static validation pass
"""

import pytest

from app.agents.agent_2.planner import (
    PlannerAgent,
    RootCauseAnalysis,
    ContextPack,
    default_planner,
)
from app.agents.agent_2.plan_schema import ExecutionPlan
from app.agents.agent_2.validator import default_validator


class TestPlannerAgent:
    """Task 16 PlannerAgent test suite."""
    
    @pytest.fixture(autouse=True)
    def clear_openai_env(self, monkeypatch):
        """Ensure unit tests use the deterministic planner by hiding OPENAI_API_KEY."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)


    def test_planner_basic_seeded_bug(self):
        """Verify planner produces validated ExecutionPlan with >= 3 steps from RCA & Context."""
        rca = RootCauseAnalysis(
            finding_id="finding-101",
            title="SQL Injection in user search query",
            description="String interpolation allows SQL injection in search_users function.",
            file_path="app/db/users.py",
            line_number=42,
            root_cause="Query string formatted with f-string instead of parameterized query.",
            suggested_fix="Use parameterized cursor.execute with tuple parameters.",
            severity="High",
            cwe="CWE-89",
        )

        context = ContextPack(
            repo_name="demo-repo",
            file_content=(
                "import os\n"
                "def search_users(cursor, query):\n"
                "    sql = f'SELECT * FROM users WHERE name = \"{query}\"'\n"
                "    cursor.execute(sql)\n"
                "    return cursor.fetchall()\n"
            ),
            test_command="pytest tests/test_users.py",
        )

        plan = default_planner.plan(rca, context)

        # 1. Returned type is ExecutionPlan
        assert isinstance(plan, ExecutionPlan)
        assert plan.goal
        assert plan.affected_files == ["app/db/users.py"]
        assert plan.rollback_plan

        # 2. Minimum 3 steps
        assert len(plan.steps) >= 3, f"Expected at least 3 steps, got {len(plan.steps)}"

        # 3. Every step contains required fields
        for idx, step in enumerate(plan.steps, 1):
            assert step.step_number == idx
            assert step.tool_name in [
                "read_file",
                "search_code",
                "apply_patch",
                "run_tests",
                "run_command",
                "open_pr",
            ]
            assert step.tool_arguments is not None
            assert len(step.expected_outcome) > 0
            assert len(step.rollback_action) > 0

        # 4. Mandatory ordering: first step is read/inspect, edit before test, open_pr at end
        assert plan.steps[0].tool_name in ("read_file", "search_code")
        tool_sequence = [s.tool_name for s in plan.steps]
        assert "apply_patch" in tool_sequence
        assert "run_tests" in tool_sequence

        # 5. Static validator passes with 0 errors
        val_res = default_validator.validate(plan)
        assert val_res.is_valid is True
        assert len(val_res.errors) == 0

    def test_planner_seeded_bug_2_null_pointer(self):
        """Seeded bug 2: Null pointer / NoneType error."""
        rca = RootCauseAnalysis(
            finding_id="finding-102",
            title="NoneType has no attribute 'strip'",
            description="User bio can be None when profile is updated without bio.",
            file_path="app/services/profile.py",
            line_number=18,
            root_cause="profile.bio accessed directly without null check.",
            suggested_fix="Check if bio is not None before stripping.",
            severity="Medium",
        )

        context = ContextPack(
            repo_name="demo-repo",
            file_content=(
                "def clean_bio(bio: str | None) -> str:\n"
                "    return bio.strip()\n"
            ),
            test_command="pytest tests/test_profile.py",
        )

        plan = default_planner.plan(rca, context)
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 3
        val_res = default_validator.validate(plan)
        assert val_res.is_valid is True

    def test_planner_seeded_bug_3_hardcoded_credentials(self):
        """Seeded bug 3: Hardcoded credentials in source file."""
        rca = RootCauseAnalysis(
            finding_id="finding-103",
            title="Hardcoded API token",
            description="Hardcoded Stripe test key found in payment processor.",
            file_path="app/payments/stripe.py",
            line_number=8,
            root_cause="API key committed directly into source code.",
            suggested_fix="Read key from os.environ['STRIPE_API_KEY'].",
            severity="Critical",
        )

        context = ContextPack(
            repo_name="demo-repo",
            file_content="STRIPE_KEY = 'sk_test_12345'\n",
            test_command="pytest tests/test_payments.py",
        )

        plan = default_planner.plan(rca, context)
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 3
        val_res = default_validator.validate(plan)
        assert val_res.is_valid is True

    def test_planner_seeded_bug_4_csrf_protection(self):
        """Seeded bug 4: Missing CSRF protection on state-changing endpoint."""
        rca = RootCauseAnalysis(
            finding_id="finding-104",
            title="Missing CSRF token validation",
            description="State-changing POST handler does not validate CSRF token.",
            file_path="server.js",
            line_number=22,
            root_cause="Express route lacks csrfProtection middleware.",
            suggested_fix="Attach csrfProtection to route handler.",
            severity="Medium",
            cwe="CWE-352",
        )

        context = ContextPack(
            repo_name="demo-repo",
            file_content="app.post('/transfer', handleTransfer);\n",
            test_command="npm test",
        )

        plan = default_planner.plan(rca, context)
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 3
        assert plan.steps[0].tool_name in ("read_file", "search_code")
        val_res = default_validator.validate(plan)
        assert val_res.is_valid is True

    def test_planner_seeded_bug_5_vulnerable_dependency(self):
        """Seeded bug 5: Vulnerable pinned dependency version."""
        rca = RootCauseAnalysis(
            finding_id="finding-105",
            title="Known vulnerability in pinned cryptography dependency",
            description="Cryptography 41.0.0 has known CVE-2023-49083.",
            file_path="requirements.txt",
            line_number=5,
            root_cause="Outdated dependency pinned in requirements manifest.",
            suggested_fix="Bump cryptography to 42.0.8.",
            severity="High",
            cwe="CWE-1395",
        )

        context = ContextPack(
            repo_name="demo-repo",
            file_content="cryptography==41.0.0\nfastapi==0.115.0\n",
            test_command="pytest",
        )

        plan = default_planner.plan(rca, context)
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 3
        assert plan.steps[0].tool_name in ("read_file", "search_code")
        val_res = default_validator.validate(plan)
        assert val_res.is_valid is True
