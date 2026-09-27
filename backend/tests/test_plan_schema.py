"""
Tests for Task 17: Formal Plan Schema and Dynamic Tool Selection.

Covers:
- Strict Pydantic models for the 6 allowed tools:
    1. read_file
    2. search_code
    3. apply_patch
    4. run_tests
    5. run_command
    6. open_pr
- 20 valid payloads (100% acceptance)
- 10 malformed/invalid payloads (100% rejection with descriptive errors)
- ExecutionPlan, PlanStep, StepOutcome serialization/deserialization
- JSON Schema exports
"""

import json
import pytest
from pydantic import BaseModel, ValidationError

from app.agents.agent_2.plan_schema import (
    ALLOWED_TOOLS,
    ReadFileArgs,
    SearchCodeArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
    PlanStep,
    ExecutionPlan,
    StepOutcome,
)
from app.agents.agent_2.tool_resolver import (
    ToolResolver,
    UnknownToolError,
    ToolArgumentValidationError,
    default_resolver,
)


# ─────────────────────────────────────────────────────────────
# 20 VALID PAYLOADS
# ─────────────────────────────────────────────────────────────

VALID_PAYLOADS = [
    # 1. Minimal read_file
    {"tool_name": "read_file", "tool_arguments": {"path": "src/index.js"}},
    # 2. read_file with line range
    {"tool_name": "read_file", "tool_arguments": {"path": "app/main.py", "start_line": 10, "end_line": 25}},
    # 3. read_file start_line only
    {"tool_name": "read_file", "tool_arguments": {"path": "README.md", "start_line": 1}},
    # 4. read_file single line
    {"tool_name": "read_file", "tool_arguments": {"path": "config.py", "start_line": 5, "end_line": 5}},
    # 5. Minimal search_code
    {"tool_name": "search_code", "tool_arguments": {"pattern": "TODO"}},
    # 6. search_code scoped to path
    {"tool_name": "search_code", "tool_arguments": {"pattern": "def authenticate", "path": "app/auth.py"}},
    # 7. search_code with regex
    {"tool_name": "search_code", "tool_arguments": {"pattern": r"class\s+[A-Z]\w+:", "regex": True}},
    # 8. search_code with regex and path
    {"tool_name": "search_code", "tool_arguments": {"pattern": r"^import\s+os", "path": "backend/", "regex": True}},
    # 9. Minimal apply_patch
    {
        "tool_name": "apply_patch",
        "tool_arguments": {
            "path": "app/utils.py",
            "original_chunk": "x = 1",
            "replacement_chunk": "x = 2",
            "line_number": 12,
        },
    },
    # 10. apply_patch multi-line
    {
        "tool_name": "apply_patch",
        "tool_arguments": {
            "path": "backend/server.py",
            "original_chunk": "def foo():\n    return False",
            "replacement_chunk": "def foo():\n    return True",
            "line_number": 45,
        },
    },
    # 11. apply_patch empty original_chunk (new insertion)
    {
        "tool_name": "apply_patch",
        "tool_arguments": {
            "path": "app/new_feature.py",
            "original_chunk": "",
            "replacement_chunk": "# newly added module",
            "line_number": 1,
        },
    },
    # 12. Minimal run_tests
    {"tool_name": "run_tests", "tool_arguments": {"test_command": "pytest"}},
    # 13. run_tests with specific file and timeout
    {"tool_name": "run_tests", "tool_arguments": {"test_command": "pytest tests/test_auth.py", "timeout_seconds": 120}},
    # 14. run_tests with npm
    {"tool_name": "run_tests", "tool_arguments": {"test_command": "npm test", "timeout_seconds": 90}},
    # 15. Minimal run_command
    {"tool_name": "run_command", "tool_arguments": {"command": "python -m py_compile app/main.py"}},
    # 16. run_command with cwd and timeout
    {"tool_name": "run_command", "tool_arguments": {"command": "npm run build", "cwd": "frontend", "timeout_seconds": 180}},
    # 17. run_command listing or checking syntax
    {"tool_name": "run_command", "tool_arguments": {"command": "flake8 app/"}},
    # 18. Minimal open_pr
    {
        "tool_name": "open_pr",
        "tool_arguments": {
            "title": "fix: resolve memory leak in worker",
            "branch": "fix/worker-leak",
            "body": "Fixes memory leak by properly closing connection pool.",
        },
    },
    # 19. open_pr with markdown description
    {
        "tool_name": "open_pr",
        "tool_arguments": {
            "title": "refactor: simplify database queries",
            "branch": "refactor/db-queries",
            "body": "### Changes\n- Removed redundant joins\n- Added index",
        },
    },
    # 20. read_file with nested subpath
    {"tool_name": "read_file", "tool_arguments": {"path": "backend/app/agents/pipeline.py", "start_line": 50, "end_line": 100}},
]


# ─────────────────────────────────────────────────────────────
# 10 MALFORMED / INVALID PAYLOADS
# ─────────────────────────────────────────────────────────────

INVALID_PAYLOADS = [
    # 1. Unknown tool name
    (
        {"tool_name": "delete_all_files", "tool_arguments": {"path": "all"}},
        "read_file",
    ),
    # 2. Unknown tool name (typo)
    (
        {"tool_name": "readfile", "tool_arguments": {"path": "app.py"}},
        "read_file",
    ),
    # 3. read_file missing required 'path'
    (
        {"tool_name": "read_file", "tool_arguments": {"start_line": 10}},
        "path",
    ),
    # 4. read_file with end_line < start_line
    (
        {"tool_name": "read_file", "tool_arguments": {"path": "main.py", "start_line": 20, "end_line": 10}},
        "end_line",
    ),
    # 5. apply_patch missing 'original_chunk'
    (
        {
            "tool_name": "apply_patch",
            "tool_arguments": {"path": "app.py", "replacement_chunk": "new", "line_number": 5},
        },
        "original_chunk",
    ),
    # 6. apply_patch with non-positive line number
    (
        {
            "tool_name": "apply_patch",
            "tool_arguments": {
                "path": "app.py",
                "original_chunk": "a",
                "replacement_chunk": "b",
                "line_number": 0,
            },
        },
        "greater than or equal to 1",
    ),
    # 7. run_tests with non-positive timeout
    (
        {"tool_name": "run_tests", "tool_arguments": {"test_command": "pytest", "timeout_seconds": -5}},
        "greater than 0",
    ),
    # 8. run_tests missing test_command
    (
        {"tool_name": "run_tests", "tool_arguments": {"timeout_seconds": 60}},
        "test_command",
    ),
    # 9. open_pr missing body
    (
        {"tool_name": "open_pr", "tool_arguments": {"title": "Fix bug", "branch": "fix/test"}},
        "body",
    ),
    # 10. Extra forbidden field in tool arguments (ConfigDict extra="forbid")
    (
        {"tool_name": "search_code", "tool_arguments": {"pattern": "abc", "unexpected_field": 123}},
        "extra",
    ),
]


class TestTask17PlanSchema:
    """Test suite for Task 17."""

    def test_twenty_valid_payloads(self):
        """Verify all 20 valid payloads parse cleanly into PlanStep models."""
        for idx, payload in enumerate(VALID_PAYLOADS, 1):
            step = PlanStep(
                step_number=idx,
                tool_name=payload["tool_name"],
                tool_arguments=payload["tool_arguments"],
                expected_outcome=f"Expected outcome for test payload {idx}",
                rollback_action=f"Rollback action for test payload {idx}",
            )
            assert step.step_number == idx
            assert step.tool_name == payload["tool_name"]
            assert isinstance(step.tool_arguments, (BaseModel, dict))
            assert hasattr(step.tool_arguments, "model_dump")

    def test_ten_malformed_payloads_rejected(self):
        """Verify all 10 malformed payloads are strictly rejected with descriptive errors."""
        for idx, (payload, expected_err) in enumerate(INVALID_PAYLOADS, 1):
            with pytest.raises((ValidationError, ValueError)) as exc_info:
                PlanStep(
                    step_number=idx,
                    tool_name=payload["tool_name"],
                    tool_arguments=payload["tool_arguments"],
                    expected_outcome="outcome",
                    rollback_action="rollback",
                )
            err_text = str(exc_info.value).lower()
            assert expected_err.lower() in err_text, (
                f"Payload {idx} ({payload['tool_name']}) did not mention expected error keyword '{expected_err}'. Got: {err_text}"
            )

    def test_execution_plan_roundtrip_serialization(self):
        """Test full ExecutionPlan model serialization to JSON and round-trip deserialization."""
        steps = [
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"path": "backend/app/main.py", "start_line": 1, "end_line": 50},
                expected_outcome="Inspect main application entrypoint",
                rollback_action="No rollback needed for read_file",
            ),
            PlanStep(
                step_number=2,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest tests/", "timeout_seconds": 30},
                expected_outcome="Reproduce pre-fix test state",
                rollback_action="No rollback needed for tests",
            ),
            PlanStep(
                step_number=3,
                tool_name="apply_patch",
                tool_arguments={
                    "path": "backend/app/main.py",
                    "original_chunk": "return False",
                    "replacement_chunk": "return True",
                    "line_number": 42,
                },
                expected_outcome="Patch main.py to return True",
                rollback_action="Revert main.py patch to return False",
            ),
            PlanStep(
                step_number=4,
                tool_name="run_tests",
                tool_arguments={"test_command": "pytest tests/", "timeout_seconds": 30},
                expected_outcome="Verify tests pass post-patch",
                rollback_action="Revert main.py patch if tests fail",
            ),
            PlanStep(
                step_number=5,
                tool_name="open_pr",
                tool_arguments={
                    "title": "fix: correct return value in main",
                    "branch": "fix/main-return",
                    "body": "Resolves issue with incorrect return value.",
                },
                expected_outcome="Submit pull request for review",
                rollback_action="Close pull request",
            ),
        ]

        plan = ExecutionPlan(
            goal="Fix return value in backend main entrypoint",
            steps=steps,
            affected_files=["backend/app/main.py"],
            estimated_complexity="Low",
            rollback_plan="Revert patch on backend/app/main.py",
        )

        json_str = plan.model_dump_json()
        assert "backend/app/main.py" in json_str

        # Deserialization
        loaded = ExecutionPlan.model_validate_json(json_str)
        assert loaded.goal == plan.goal
        assert len(loaded.steps) == 5
        assert loaded.steps[0].tool_name == "read_file"
        assert loaded.steps[2].tool_name == "apply_patch"
        assert loaded.steps[2].tool_arguments["line_number"] == 42
        assert loaded.affected_files == ["backend/app/main.py"]

    def test_step_outcome_model(self):
        """Test StepOutcome serialization."""
        outcome = StepOutcome(
            step_number=1,
            tool_name="run_tests",
            success=True,
            output="3 passed in 0.2s",
            error=None,
            artifacts={"passed_count": 3},
        )
        data = outcome.model_dump()
        assert data["success"] is True
        assert data["output"] == "3 passed in 0.2s"

    def test_json_schema_exports(self):
        """Verify that JSON Schema export generates valid schemas for all components."""
        resolver = default_resolver
        schemas = resolver.export_all_schemas()

        assert "ExecutionPlan" in schemas
        assert "PlanStep" in schemas
        assert "StepOutcome" in schemas
        assert "tools" in schemas

        tool_schemas = schemas["tools"]
        assert len(tool_schemas) == 6
        for tool in ALLOWED_TOOLS:
            assert tool in tool_schemas
            assert "properties" in tool_schemas[tool]
            assert "type" in tool_schemas[tool]

        # Verify JSON export is valid JSON string
        json_output = resolver.export_all_schemas_json()
        parsed = json.loads(json_output)
        assert "ExecutionPlan" in parsed

    def test_audit_1_arbitrary_fake_fields_rejected(self):
        """Regression Audit #1: Ensure arbitrary dictionaries with fake fields are strictly rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PlanStep(
                step_number=1,
                tool_name="read_file",
                tool_arguments={"completely_fake_field": "anything"},
                expected_outcome="outcome",
                rollback_action="rollback",
            )
        err = str(exc_info.value)
        assert "path" in err.lower() or "extra" in err.lower()

    def test_audit_1_mismatched_tool_arguments_rejected(self):
        """Regression Audit #1: Ensure tool arguments belonging to another tool are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            PlanStep(
                step_number=1,
                tool_name="run_tests",
                tool_arguments={"path": "app/main.py"},  # read_file arguments passed to run_tests
                expected_outcome="outcome",
                rollback_action="rollback",
            )
        err = str(exc_info.value)
        assert "test_command" in err.lower() or "extra" in err.lower() or "invalid argument model" in err.lower()

    def test_audit_1_mismatched_model_instance_rejected(self):
        """Regression Audit #1: Ensure passing wrong BaseModel instance raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            PlanStep(
                step_number=1,
                tool_name="run_tests",
                tool_arguments=ReadFileArgs(path="app/main.py"),
                expected_outcome="outcome",
                rollback_action="rollback",
            )
        err = str(exc_info.value)
        assert "mismatched tool arguments" in err.lower() or "invalid argument model" in err.lower()

    def test_audit_1_execution_plan_rejects_invalid_step(self):
        """Regression Audit #1: Ensure ExecutionPlan validation catches invalid tool arguments at top-level."""
        invalid_plan_dict = {
            "goal": "Test invalid plan",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "read_file",
                    "tool_arguments": {"bogus": 123},
                    "expected_outcome": "outcome",
                    "rollback_action": "rollback",
                }
            ],
            "affected_files": ["app.py"],
            "estimated_complexity": "Low",
            "rollback_plan": "revert",
        }
        with pytest.raises(ValidationError):
            ExecutionPlan(**invalid_plan_dict)
