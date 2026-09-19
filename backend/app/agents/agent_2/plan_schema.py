"""
Formal Plan Schema and Typed Tool Specifications for Engineer 2 (Agent 2).

Provides strictly typed Pydantic models for:
- ExecutionPlan
- PlanStep
- StepOutcome
- Tool-specific argument models for the 6 allowed tools:
    1. read_file
    2. search_code
    3. apply_patch
    4. run_tests
    5. run_command
    6. open_pr
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_TOOLS = {
    "read_file",
    "search_code",
    "apply_patch",
    "run_tests",
    "run_command",
    "open_pr",
}

AllowedToolName = Literal[
    "read_file",
    "search_code",
    "apply_patch",
    "run_tests",
    "run_command",
    "open_pr",
]


# ─────────────────────────────────────────────────────────────
# Tool Argument Models
# ─────────────────────────────────────────────────────────────

class ToolArgsBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class ReadFileArgs(ToolArgsBase):
    path: str = Field(..., min_length=1, description="Repository-relative file path to read")
    start_line: int | None = Field(default=None, ge=1, description="Optional starting line (1-indexed)")
    end_line: int | None = Field(default=None, ge=1, description="Optional ending line (1-indexed)")

    @model_validator(mode="after")
    def check_line_bounds(self) -> ReadFileArgs:
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError(f"end_line ({self.end_line}) cannot be less than start_line ({self.start_line})")
        return self


class SearchCodeArgs(ToolArgsBase):
    pattern: str = Field(..., min_length=1, description="Search term or regex pattern")
    path: str | None = Field(default=None, description="Optional directory or file sub-path to scope search")
    regex: bool = Field(default=False, description="Whether pattern should be treated as regex")


class ApplyPatchArgs(ToolArgsBase):
    path: str = Field(..., min_length=1, description="Repository-relative file path to patch")
    original_chunk: str = Field(..., description="Exact snippet of original content to replace")
    replacement_chunk: str = Field(..., description="Replacement snippet")
    line_number: int = Field(..., ge=1, description="Approximate or exact starting line number of original chunk")


class RunTestsArgs(ToolArgsBase):
    test_command: str = Field(..., min_length=1, description="Test command to execute")
    timeout_seconds: int = Field(default=60, gt=0, le=600, description="Execution timeout in seconds")


class RunCommandArgs(ToolArgsBase):
    command: str = Field(..., min_length=1, description="Shell command to run")
    timeout_seconds: int = Field(default=60, gt=0, le=600, description="Execution timeout in seconds")
    cwd: str | None = Field(default=None, description="Optional working directory relative to workspace root")


class OpenPrArgs(ToolArgsBase):
    title: str = Field(..., min_length=1, description="Title of the pull request")
    branch: str = Field(..., min_length=1, description="Name of the head branch")
    body: str = Field(..., min_length=1, description="Pull request body/description")


TOOL_ARGUMENT_MODELS: dict[str, type[ToolArgsBase]] = {
    "read_file": ReadFileArgs,
    "search_code": SearchCodeArgs,
    "apply_patch": ApplyPatchArgs,
    "run_tests": RunTestsArgs,
    "run_command": RunCommandArgs,
    "open_pr": OpenPrArgs,
}

AnyToolArgs = (
    ReadFileArgs
    | SearchCodeArgs
    | ApplyPatchArgs
    | RunTestsArgs
    | RunCommandArgs
    | OpenPrArgs
)


# ─────────────────────────────────────────────────────────────
# Plan Models
# ─────────────────────────────────────────────────────────────

class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(..., ge=1, description="1-indexed sequence number of the step")
    tool_name: AllowedToolName = Field(..., description="Name of the tool to execute")
    tool_arguments: AnyToolArgs | dict[str, Any] = Field(
        ...,
        description="Strictly validated tool arguments matching the tool schema",
    )
    expected_outcome: str = Field(..., min_length=1, description="Expected result or condition after execution")
    rollback_action: str = Field(..., min_length=1, description="Action or command to revert this step on failure")

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        if v not in ALLOWED_TOOLS:
            allowed_str = ", ".join(sorted(ALLOWED_TOOLS))
            raise ValueError(f"Unknown tool '{v}'. Allowed tools are: {allowed_str}")
        return v

    @model_validator(mode="after")
    def validate_and_cast_tool_arguments(self) -> PlanStep:
        tool_name = self.tool_name
        args = self.tool_arguments
        model_cls = TOOL_ARGUMENT_MODELS.get(tool_name)
        if not model_cls:
            raise ValueError(f"No argument schema registered for tool '{tool_name}'")

        if isinstance(args, dict):
            # Strictly validate dictionary arguments through the registered Pydantic schema
            validated = model_cls(**args)
            self.tool_arguments = validated
        elif isinstance(args, model_cls):
            self.tool_arguments = args
        elif isinstance(args, BaseModel):
            # Cross-model assignment (invalid schema passed)
            raise ValueError(f"Invalid argument model '{type(args).__name__}' for tool '{tool_name}'")
        else:
            raise ValueError(f"tool_arguments for '{tool_name}' must be a dictionary or {model_cls.__name__}")
        return self


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(..., min_length=1, description="Primary goal and description of what the plan accomplishes")
    steps: list[PlanStep] = Field(..., min_length=1, description="Ordered list of execution steps")
    affected_files: list[str] = Field(default_factory=list, description="List of file paths targeted by the plan")
    estimated_complexity: str = Field(..., min_length=1, description="Complexity assessment (e.g. Low, Medium, High)")
    rollback_plan: str = Field(..., min_length=1, description="Overall rollback instructions if execution aborts")

    @field_validator("affected_files")
    @classmethod
    def normalize_affected_files(cls, files: list[str]) -> list[str]:
        cleaned: list[str] = []
        for f in files:
            norm = f.strip().replace("\\", "/")
            if norm and norm not in cleaned:
                cleaned.append(norm)
        return cleaned


class StepOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_number: int = Field(..., ge=1, description="Step sequence number")
    tool_name: AllowedToolName = Field(..., description="Tool that was executed")
    success: bool = Field(..., description="Whether the step completed successfully")
    output: str | None = Field(default=None, description="Standard output or result payload")
    error: str | None = Field(default=None, description="Error message if step failed")
    artifacts: dict[str, Any] = Field(default_factory=dict, description="Artifacts or outputs generated by the step")
