"""
Dedicated Test Suite for Task 23: Central Tool Registry.

Verifies:
1. Exactly 8 tools are registered in default_registry.
2. 10 valid tool dispatches execute successfully (100% success).
3. 5 invalid tool dispatches return structured ToolResult(success=False).
4. Invalid arguments are rejected BEFORE the handler executes (proven via spy handler).
5. Unknown tool names return structured ToolResult errors.
6. Handler exceptions return structured ToolResult errors without leaking uncaught exceptions.
7. execution_time_ms is populated and non-negative.
8. Permission metadata is present and correct across all 8 tools.
9. Registered Pydantic parameter schemas are actively enforced.
10. ToolResult is fully serializable to JSON and dict.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest
from pydantic import BaseModel, Field

from app.agents.agent_2.tool_registry import (
    ToolPermission,
    ToolResult,
    FindFilesArgs,
    GetSymbolDefinitionArgs,
    RegisteredTool,
    ToolRegistry,
    default_registry,
)
from app.agents.agent_2.plan_schema import (
    ReadFileArgs,
    SearchCodeArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
)


class TestToolRegistrySuite:
    """Acceptance test suite for Task 23 Tool Registry."""

    # 1. Exactly 8 tools registered
    def test_01_exactly_8_tools_registered(self):
        tools = default_registry.list_tools()
        assert len(tools) == 8, f"Expected exactly 8 registered tools, got {len(tools)}: {tools}"
        expected_tools = {
            "read_file",
            "search_code",
            "find_files",
            "get_symbol_definition",
            "apply_patch",
            "run_tests",
            "run_command",
            "open_pr",
        }
        assert set(tools) == expected_tools

    # 2. Permission metadata correctness
    def test_02_permission_metadata_correctness(self):
        expected_permissions = {
            "read_file": ToolPermission.READ,
            "search_code": ToolPermission.READ,
            "find_files": ToolPermission.READ,
            "get_symbol_definition": ToolPermission.READ,
            "apply_patch": ToolPermission.WRITE,
            "run_tests": ToolPermission.WRITE,
            "run_command": ToolPermission.DESTRUCTIVE,
            "open_pr": ToolPermission.WRITE,
        }

        for name, expected_perm in expected_permissions.items():
            tool = default_registry.get_tool(name)
            assert tool is not None
            assert tool.permission == expected_perm, (
                f"Tool '{name}' expected permission {expected_perm.value}, got {tool.permission.value}"
            )
            metadata = default_registry.get_tool_metadata(name)
            assert metadata["permission"] == expected_perm.value
            assert "parameters_schema" in metadata
            assert "json_schema" in metadata

    # 3. 10 Valid Tool Dispatches
    def test_03_ten_valid_tool_dispatches(self):
        valid_calls = [
            # 1. read_file with line range
            ("read_file", {"path": "app/main.py", "start_line": 1, "end_line": 15}),
            # 2. read_file path only
            ("read_file", {"path": "app/config.py"}),
            # 3. search_code simple pattern
            ("search_code", {"pattern": "FastAPI"}),
            # 4. search_code with regex and path
            ("search_code", {"pattern": r"^def\s+", "path": "app/", "regex": True}),
            # 5. find_files with pattern and path
            ("find_files", {"pattern": "*.py", "path": "app", "max_results": 50}),
            # 6. get_symbol_definition
            ("get_symbol_definition", {"symbol": "execute_plan", "path": "app/agents/executor.py"}),
            # 7. apply_patch valid args
            (
                "apply_patch",
                {
                    "path": "app/services.py",
                    "original_chunk": "count = 0",
                    "replacement_chunk": "count = 1",
                    "line_number": 42,
                },
            ),
            # 8. run_tests with command and timeout
            ("run_tests", {"test_command": "pytest tests/test_planner.py", "timeout_seconds": 120}),
            # 9. run_command with safe command
            ("run_command", {"command": "python --version", "timeout_seconds": 30, "cwd": "."}),
            # 10. open_pr with required fields
            ("open_pr", {"title": "fix: null check", "branch": "fix/null-check", "body": "Adds null check"}),
        ]

        assert len(valid_calls) == 10

        for idx, (tool_name, args) in enumerate(valid_calls, 1):
            res = default_registry.dispatch(tool_name, args)
            assert isinstance(res, ToolResult), f"Call {idx} ({tool_name}) did not return ToolResult"
            assert res.success is True, f"Call {idx} ({tool_name}) failed: {res.error}"
            assert res.data is not None, f"Call {idx} ({tool_name}) had None data"
            assert res.error is None, f"Call {idx} ({tool_name}) had error: {res.error}"
            assert res.execution_time_ms >= 0.0, f"Call {idx} execution_time_ms not recorded"

    # 4. 5 Invalid Tool Dispatches
    def test_04_five_invalid_tool_dispatches(self):
        invalid_calls = [
            # 1. Unknown tool
            ("delete_database", {"database": "prod"}),
            # 2. Missing required field (read_file missing path)
            ("read_file", {}),
            # 3. Schema constraint violation (end_line < start_line)
            ("read_file", {"path": "app/main.py", "start_line": 50, "end_line": 10}),
            # 4. Destructive command blocked by safety guard
            ("run_command", {"command": "rm -rf /var/log"}),
            # 5. Protected path blocked by safety guard
            ("read_file", {"path": ".env"}),
        ]

        assert len(invalid_calls) == 5

        for idx, (tool_name, args) in enumerate(invalid_calls, 1):
            res = default_registry.dispatch(tool_name, args)
            assert isinstance(res, ToolResult), f"Invalid call {idx} did not return ToolResult"
            assert res.success is False, f"Invalid call {idx} ({tool_name}) unexpectedly succeeded"
            assert res.error is not None, f"Invalid call {idx} ({tool_name}) had no error message"
            assert len(res.error) > 0
            assert res.execution_time_ms >= 0.0

    # 5. Prove handler is NOT invoked when schema validation fails
    def test_05_handler_not_invoked_on_validation_failure(self):
        spy_handler = MagicMock()

        registry = ToolRegistry()
        registry.register(
            name="guarded_tool",
            description="Tool with spy handler",
            parameters_schema=ReadFileArgs,
            permission=ToolPermission.READ,
            handler=spy_handler,
        )

        # Dispatch with invalid arguments (missing required 'path')
        res = registry.dispatch("guarded_tool", {})

        assert res.success is False
        assert "[INVALID_ARGUMENTS]" in res.error
        # Proof: handler was NEVER called
        assert spy_handler.call_count == 0, "Handler was invoked despite schema validation failure!"

    # 6. Unknown tool returns structured ToolResult error
    def test_06_unknown_tool_returns_structured_error(self):
        res = default_registry.dispatch("non_existent_tool_123", {"foo": "bar"})
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "[UNKNOWN_TOOL]" in res.error
        assert "non_existent_tool_123" in res.error
        assert res.execution_time_ms >= 0.0

    # 7. Handler exceptions return structured ToolResult without escaping
    def test_07_handler_exception_returns_structured_error(self):
        class SimpleArgs(BaseModel):
            input_val: int

        def crashing_handler(args: SimpleArgs):
            raise RuntimeError("Database connection suddenly dropped!")

        reg = ToolRegistry()
        reg.register(
            name="crashing_tool",
            description="Tool that raises an uncaught exception",
            parameters_schema=SimpleArgs,
            permission=ToolPermission.READ,
            handler=crashing_handler,
        )

        # Must not raise an exception; must catch and return ToolResult
        res = reg.dispatch("crashing_tool", {"input_val": 42})
        assert isinstance(res, ToolResult)
        assert res.success is False
        assert "[TOOL_EXECUTION_ERROR]" in res.error
        assert "Database connection suddenly dropped!" in res.error
        assert res.data is None
        assert res.execution_time_ms >= 0.0

    # 8. Registered schemas actively used for argument validation
    def test_08_schemas_actively_used_for_validation(self):
        # Passing extra fields when extra="forbid" raises validation error
        res = default_registry.dispatch(
            "run_tests",
            {"test_command": "pytest", "unexpected_field": "disallowed"},
        )
        assert res.success is False
        assert "[INVALID_ARGUMENTS]" in res.error
        assert "unexpected_field" in res.error or "Extra inputs are not permitted" in res.error

    # 9. ToolResult is fully serializable
    def test_09_tool_result_is_serializable(self):
        res = default_registry.dispatch("read_file", {"path": "app/main.py", "start_line": 1, "end_line": 5})
        assert res.success is True

        # Convert to dict
        d = res.model_dump()
        assert isinstance(d, dict)
        assert d["success"] is True
        assert "execution_time_ms" in d

        # Convert to JSON string
        j = res.model_dump_json()
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert parsed["success"] is True
        assert parsed["data"]["path"] == "app/main.py"

    # 10. Decorator registration API works seamlessly
    def test_10_decorator_registration_api(self):
        custom_reg = ToolRegistry()

        class EchoArgs(BaseModel):
            message: str

        @custom_reg.register_tool(
            name="echo",
            description="Echoes the message",
            parameters_schema=EchoArgs,
            permission=ToolPermission.READ,
        )
        def echo_handler(args: EchoArgs):
            return {"echo": args.message}

        assert custom_reg.has_tool("echo")
        assert custom_reg.get_tool("echo").permission == ToolPermission.READ

        res = custom_reg.dispatch("echo", {"message": "hello world"})
        assert res.success is True
        assert res.data == {"echo": "hello world"}
