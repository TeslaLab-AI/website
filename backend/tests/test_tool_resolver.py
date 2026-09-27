"""
Tests for Tool Resolver (Task 17).

Covers:
- Resolving all six authorized tool names to their typed Pydantic models.
- Rejecting unknown tools.
- Validation through validate_tool_call.
- Schema extraction.
"""

import pytest
from app.agents.agent_2.tool_resolver import (
    ToolResolver,
    UnknownToolError,
    ToolArgumentValidationError,
    default_resolver,
)
from app.agents.agent_2.plan_schema import (
    ALLOWED_TOOLS,
    ReadFileArgs,
    SearchCodeArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
)


class TestToolResolver:
    """Tool Resolver test suite."""

    def test_registered_tools_count_and_names(self):
        resolver = ToolResolver()
        tools = resolver.get_registered_tools()
        assert len(tools) == 6
        assert set(tools) == ALLOWED_TOOLS

    def test_resolve_each_allowed_tool(self):
        resolver = ToolResolver()
        assert resolver.resolve("read_file") == ReadFileArgs
        assert resolver.resolve("search_code") == SearchCodeArgs
        assert resolver.resolve("apply_patch") == ApplyPatchArgs
        assert resolver.resolve("run_tests") == RunTestsArgs
        assert resolver.resolve("run_command") == RunCommandArgs
        assert resolver.resolve("open_pr") == OpenPrArgs

    def test_unknown_tool_rejection(self):
        resolver = ToolResolver()
        invalid_tools = [
            "delete_file",
            "curl_sh",
            "git_push",
            "modify_file",
            "execute_bash",
            "readfile",
        ]
        for bad_tool in invalid_tools:
            with pytest.raises(UnknownToolError) as exc_info:
                resolver.resolve(bad_tool)
            assert f"Tool '{bad_tool}' is not recognized" in str(exc_info.value)

    def test_validate_tool_call_valid(self):
        resolver = default_resolver
        res = resolver.validate_tool_call(
            "apply_patch",
            {
                "path": "app/config.py",
                "original_chunk": "A = 1",
                "replacement_chunk": "A = 2",
                "line_number": 10,
            },
        )
        assert isinstance(res, ApplyPatchArgs)
        assert res.path == "app/config.py"
        assert res.line_number == 10

    def test_validate_tool_call_invalid_args(self):
        resolver = default_resolver
        with pytest.raises(ToolArgumentValidationError):
            resolver.validate_tool_call(
                "run_tests",
                {"test_command": "", "timeout_seconds": -1},
            )

    def test_get_tool_schema(self):
        resolver = default_resolver
        schema = resolver.get_tool_schema("read_file")
        assert schema["type"] == "object"
        assert "path" in schema["properties"]
