"""
Tool Resolver for Engineer 2 (Agent 2).

Maintains the strict registry of the six allowed tools and maps them to their
typed Pydantic argument schemas. Unknown tools are strictly rejected.
Provides JSON schema generation for documentation and validation.
"""

from __future__ import annotations
import json
from typing import Any
from pydantic import BaseModel

from app.agents.agent_2.plan_schema import (
    ALLOWED_TOOLS,
    TOOL_ARGUMENT_MODELS,
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


class UnknownToolError(ValueError):
    """Raised when an unrecognized tool name is requested."""
    pass


class ToolArgumentValidationError(ValueError):
    """Raised when arguments provided for a tool fail schema validation."""
    pass


class ToolResolver:
    """
    Dynamic Tool Resolver and registry.
    Ensures only the six authorized tools can be resolved and invoked.
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseModel]] = dict(TOOL_ARGUMENT_MODELS)

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool name is registered."""
        return tool_name in self._registry

    def get_registered_tools(self) -> list[str]:
        """Return list of allowed tool names."""
        return sorted(list(self._registry.keys()))

    def resolve(self, tool_name: str) -> type[BaseModel]:
        """
        Map an allowed tool name to its registered Pydantic argument model.
        Raises UnknownToolError if the tool is not registered.
        """
        if tool_name not in self._registry:
            allowed = ", ".join(self.get_registered_tools())
            raise UnknownToolError(
                f"[UNKNOWN_TOOL] Tool '{tool_name}' is not recognized. Allowed tools are: {allowed}"
            )
        return self._registry[tool_name]

    def validate_tool_call(self, tool_name: str, arguments: dict[str, Any] | BaseModel) -> BaseModel:
        """
        Validate arguments against the registered tool's argument model.
        Returns the parsed/validated model instance.
        """
        model_cls = self.resolve(tool_name)
        if isinstance(arguments, model_cls):
            return arguments

        if not isinstance(arguments, dict):
            raise ToolArgumentValidationError(
                f"[INVALID_TOOL_ARGUMENTS] Arguments for tool '{tool_name}' must be a dictionary or {model_cls.__name__}"
            )

        try:
            return model_cls(**arguments)
        except Exception as err:
            raise ToolArgumentValidationError(
                f"[INVALID_TOOL_ARGUMENTS] Failed schema validation for tool '{tool_name}': {err}"
            ) from err

    def get_tool_schema(self, tool_name: str) -> dict[str, Any]:
        """Get the JSON schema dictionary for a specific tool's arguments."""
        model_cls = self.resolve(tool_name)
        return model_cls.model_json_schema()

    def export_all_schemas(self) -> dict[str, Any]:
        """Export JSON Schemas for all registered tools, PlanStep, and ExecutionPlan."""
        return {
            "ExecutionPlan": ExecutionPlan.model_json_schema(),
            "PlanStep": PlanStep.model_json_schema(),
            "StepOutcome": StepOutcome.model_json_schema(),
            "tools": {
                name: model_cls.model_json_schema()
                for name, model_cls in self._registry.items()
            },
        }

    def export_all_schemas_json(self, indent: int = 2) -> str:
        """Export all schemas as formatted JSON string."""
        return json.dumps(self.export_all_schemas(), indent=indent)


# Global default resolver singleton
default_resolver = ToolResolver()
