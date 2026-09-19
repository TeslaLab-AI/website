"""
Agent 2 (Engineer 2) — Planning & Execution Package.

Provides:
- ExecutionPlan, PlanStep, StepOutcome
- Tool argument models (ReadFileArgs, SearchCodeArgs, ApplyPatchArgs, RunTestsArgs, RunCommandArgs, OpenPrArgs)
- ToolResolver, default_resolver, UnknownToolError
- PlanValidator, ValidationResult, default_validator
- PlannerAgent, RootCauseAnalysis, ContextPack, default_planner
- execution_plan_to_fix_plan, fix_plan_to_execution_plan
"""

from app.agents.agent_2.plan_schema import (
    ALLOWED_TOOLS,
    AllowedToolName,
    ReadFileArgs,
    SearchCodeArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
    PlanStep,
    ExecutionPlan,
    StepOutcome,
    TOOL_ARGUMENT_MODELS,
)
from app.agents.agent_2.tool_resolver import (
    ToolResolver,
    UnknownToolError,
    ToolArgumentValidationError,
    default_resolver,
)
from app.agents.agent_2.validator import (
    PlanValidator,
    ValidationResult,
    default_validator,
)
from app.agents.agent_2.planner import (
    PlannerAgent,
    RootCauseAnalysis,
    ContextPack,
    default_planner,
)
from app.agents.agent_2.adapter import (
    execution_plan_to_fix_plan,
    fix_plan_to_execution_plan,
)
from app.agents.agent_2.gateway import (
    LLMGateway,
    default_gateway,
    complete,
    LLMResponse,
    TokenUsage,
    LLMMessage,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    BaseLLMAdapter,
)
from app.agents.agent_2.router import (
    ModelRouter,
    default_router,
    get_model_for_task,
    ModelRoute,
    ModelTier,
    RouterConfig,
)

__all__ = [
    "ALLOWED_TOOLS",
    "AllowedToolName",
    "ReadFileArgs",
    "SearchCodeArgs",
    "ApplyPatchArgs",
    "RunTestsArgs",
    "RunCommandArgs",
    "OpenPrArgs",
    "PlanStep",
    "ExecutionPlan",
    "StepOutcome",
    "TOOL_ARGUMENT_MODELS",
    "ToolResolver",
    "UnknownToolError",
    "ToolArgumentValidationError",
    "default_resolver",
    "PlanValidator",
    "ValidationResult",
    "default_validator",
    "PlannerAgent",
    "RootCauseAnalysis",
    "ContextPack",
    "default_planner",
    "execution_plan_to_fix_plan",
    "fix_plan_to_execution_plan",
    "LLMGateway",
    "default_gateway",
    "complete",
    "LLMResponse",
    "TokenUsage",
    "LLMMessage",
    "LLMError",
    "LLMRateLimitError",
    "LLMServerError",
    "BaseLLMAdapter",
    "ModelRouter",
    "default_router",
    "get_model_for_task",
    "ModelRoute",
    "ModelTier",
    "RouterConfig",
]
