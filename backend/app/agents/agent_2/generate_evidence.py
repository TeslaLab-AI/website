"""
Generates and preserves evidence artifacts for Engineer 2 Tasks 16, 17, and 18.
"""

import os
import json

from app.agents.agent_2 import (
    default_resolver,
    default_planner,
    default_validator,
    RootCauseAnalysis,
    ContextPack,
    ExecutionPlan,
    PlanStep,
    ReadFileArgs,
    ApplyPatchArgs,
    RunTestsArgs,
    RunCommandArgs,
    OpenPrArgs,
)

ev_dir = os.path.join(os.path.dirname(__file__), "evidence")
plans_dir = os.path.join(ev_dir, "sample_plans")
schemas_dir = os.path.join(ev_dir, "schemas")
rejections_dir = os.path.join(ev_dir, "rejection_examples")

for d in [plans_dir, schemas_dir, rejections_dir]:
    os.makedirs(d, exist_ok=True)

# 1. Export Schemas
schemas = default_resolver.export_all_schemas()
with open(os.path.join(schemas_dir, "ExecutionPlan.json"), "w", encoding="utf-8") as f:
    json.dump(schemas["ExecutionPlan"], f, indent=2)
with open(os.path.join(schemas_dir, "PlanStep.json"), "w", encoding="utf-8") as f:
    json.dump(schemas["PlanStep"], f, indent=2)
with open(os.path.join(schemas_dir, "StepOutcome.json"), "w", encoding="utf-8") as f:
    json.dump(schemas["StepOutcome"], f, indent=2)
with open(os.path.join(schemas_dir, "tools_schema.json"), "w", encoding="utf-8") as f:
    json.dump(schemas["tools"], f, indent=2)

# 2. Export 5 Sample Execution Plans
# Plan 1: SQL Injection fix
p1 = default_planner.plan(
    RootCauseAnalysis(
        finding_id="sql-inj-001",
        title="SQL Injection in search endpoint",
        description="Unsanitized input in query",
        file_path="app/db/search.py",
        line_number=25,
        root_cause="F-string used in cursor.execute",
        suggested_fix="Use parameterized query arguments",
        severity="High",
        cwe="CWE-89",
    ),
    ContextPack(
        repo_name="web-backend",
        file_content='def search(q):\n    cursor.execute(f"SELECT * FROM items WHERE name={q}")\n',
        test_command="pytest tests/test_search.py",
    ),
)
with open(os.path.join(plans_dir, "plan_1_sql_injection_fix.json"), "w", encoding="utf-8") as f:
    f.write(p1.model_dump_json(indent=2))

# Plan 2: CSRF protection
p2 = ExecutionPlan(
    goal="Add CSRF token validation to sensitive POST endpoint",
    steps=[
        PlanStep(
            step_number=1,
            tool_name="read_file",
            tool_arguments={"path": "server.js", "start_line": 1, "end_line": 50},
            expected_outcome="Inspect Express middleware configuration",
            rollback_action="No rollback",
        ),
        PlanStep(
            step_number=2,
            tool_name="run_tests",
            tool_arguments={"test_command": "npm test"},
            expected_outcome="Observe pre-fix test state",
            rollback_action="No rollback",
        ),
        PlanStep(
            step_number=3,
            tool_name="apply_patch",
            tool_arguments={
                "path": "server.js",
                "original_chunk": "app.use(express.json());",
                "replacement_chunk": "app.use(express.json());\napp.use(csrfProtection);",
                "line_number": 20,
            },
            expected_outcome="Register CSRF protection middleware",
            rollback_action="Revert server.js patch",
        ),
        PlanStep(
            step_number=4,
            tool_name="run_tests",
            tool_arguments={"test_command": "npm test"},
            expected_outcome="Verify CSRF integration tests pass",
            rollback_action="Revert server.js patch",
        ),
        PlanStep(
            step_number=5,
            tool_name="open_pr",
            tool_arguments={
                "title": "security: add CSRF middleware protection",
                "branch": "fix/csrf-middleware",
                "body": "Implements CSRF protection.",
            },
            expected_outcome="Submit pull request",
            rollback_action="Close pull request",
        ),
    ],
    affected_files=["server.js"],
    estimated_complexity="Medium",
    rollback_plan="Revert server.js and restart",
)
with open(os.path.join(plans_dir, "plan_2_csrf_middleware_fix.json"), "w", encoding="utf-8") as f:
    f.write(p2.model_dump_json(indent=2))

# Plan 3: Null pointer check
p3 = default_planner.plan(
    RootCauseAnalysis(
        finding_id="null-ptr-003",
        title="Null pointer exception when profile avatar is None",
        description="Accessing avatar url directly causes AttributeError",
        file_path="app/views/avatar.py",
        line_number=15,
        root_cause="avatar.url dereferenced without None check",
        suggested_fix="Add None check and fallback default avatar url",
        severity="Medium",
    ),
    ContextPack(
        repo_name="web-backend",
        file_content="def get_avatar(user):\n    return user.avatar.url\n",
        test_command="pytest tests/test_avatar.py",
    ),
)
with open(os.path.join(plans_dir, "plan_3_null_pointer_fix.json"), "w", encoding="utf-8") as f:
    f.write(p3.model_dump_json(indent=2))

# Plan 4: Dependency upgrade
p4 = ExecutionPlan(
    goal="Safely upgrade vulnerable dependency in requirements.txt",
    steps=[
        PlanStep(
            step_number=1,
            tool_name="read_file",
            tool_arguments={"path": "requirements.txt"},
            expected_outcome="Read pinned dependencies",
            rollback_action="No rollback",
        ),
        PlanStep(
            step_number=2,
            tool_name="run_tests",
            tool_arguments={"test_command": "pytest"},
            expected_outcome="Ensure suite passes before bump",
            rollback_action="No rollback",
        ),
        PlanStep(
            step_number=3,
            tool_name="apply_patch",
            tool_arguments={
                "path": "requirements.txt",
                "original_chunk": "cryptography==41.0.0",
                "replacement_chunk": "cryptography==42.0.8",
                "line_number": 5,
            },
            expected_outcome="Bump cryptography to patch CVE",
            rollback_action="Revert requirements.txt",
        ),
        PlanStep(
            step_number=4,
            tool_name="run_tests",
            tool_arguments={"test_command": "pytest"},
            expected_outcome="Verify test suite passes with bumped library",
            rollback_action="Revert requirements.txt",
        ),
        PlanStep(
            step_number=5,
            tool_name="open_pr",
            tool_arguments={
                "title": "chore(deps): bump cryptography to 42.0.8",
                "branch": "deps/crypto-bump",
                "body": "Bumps cryptography to remediate vulnerability.",
            },
            expected_outcome="Submit dependency bump PR",
            rollback_action="Close pull request",
        ),
    ],
    affected_files=["requirements.txt"],
    estimated_complexity="Low",
    rollback_plan="Revert requirements.txt and reinstall",
)
with open(os.path.join(plans_dir, "plan_4_dependency_upgrade.json"), "w", encoding="utf-8") as f:
    f.write(p4.model_dump_json(indent=2))

# Plan 5: Hardcoded credentials
p5 = default_planner.plan(
    RootCauseAnalysis(
        finding_id="cred-005",
        title="Hardcoded JWT secret key in auth handler",
        description="Secret key string exposed in repository source",
        file_path="app/auth/jwt.py",
        line_number=10,
        root_cause="Hardcoded string literal used as JWT secret",
        suggested_fix="Read secret from JWT_SECRET environment variable",
        severity="High",
        cwe="CWE-798",
    ),
    ContextPack(
        repo_name="web-backend",
        file_content='SECRET = "my_super_secret_12345"\ndef encode_jwt(p):\n    return jwt.encode(p, SECRET)\n',
        test_command="pytest tests/test_jwt.py",
    ),
)
with open(os.path.join(plans_dir, "plan_5_hardcoded_secret_fix.json"), "w", encoding="utf-8") as f:
    f.write(p5.model_dump_json(indent=2))

# 3. Export Rejection Examples with Validator Results
rej_cases = [
    (
        "malicious_destructive_rm_rf.json",
        {
            "goal": "Malicious destruction",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "read_file",
                    "tool_arguments": {"path": "app.py"},
                    "expected_outcome": "read",
                    "rollback_action": "none",
                },
                {
                    "step_number": 2,
                    "tool_name": "run_command",
                    "tool_arguments": {"command": "rm -rf /var/log/*"},
                    "expected_outcome": "delete",
                    "rollback_action": "none",
                },
            ],
            "affected_files": ["app.py"],
            "estimated_complexity": "High",
            "rollback_plan": "none",
        },
    ),
    (
        "malicious_protected_env.json",
        {
            "goal": "Steal credentials",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "read_file",
                    "tool_arguments": {"path": ".env"},
                    "expected_outcome": "read env",
                    "rollback_action": "none",
                },
                {
                    "step_number": 2,
                    "tool_name": "open_pr",
                    "tool_arguments": {"title": "exfiltrate", "branch": "leak", "body": "exfil"},
                    "expected_outcome": "leak",
                    "rollback_action": "none",
                },
            ],
            "affected_files": [".env"],
            "estimated_complexity": "High",
            "rollback_plan": "none",
        },
    ),
    (
        "malicious_git_force_push.json",
        {
            "goal": "Force overwrite remote master",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "read_file",
                    "tool_arguments": {"path": "README.md"},
                    "expected_outcome": "read",
                    "rollback_action": "none",
                },
                {
                    "step_number": 2,
                    "tool_name": "run_command",
                    "tool_arguments": {"command": "git push origin master --force"},
                    "expected_outcome": "overwrite",
                    "rollback_action": "none",
                },
            ],
            "affected_files": ["README.md"],
            "estimated_complexity": "High",
            "rollback_plan": "none",
        },
    ),
    (
        "invalid_ordering_edit_before_read.json",
        {
            "goal": "Premature patch without inspection",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "apply_patch",
                    "tool_arguments": {
                        "path": "app.py",
                        "original_chunk": "a",
                        "replacement_chunk": "b",
                        "line_number": 1,
                    },
                    "expected_outcome": "patch",
                    "rollback_action": "none",
                },
                {
                    "step_number": 2,
                    "tool_name": "read_file",
                    "tool_arguments": {"path": "app.py"},
                    "expected_outcome": "read too late",
                    "rollback_action": "none",
                },
            ],
            "affected_files": ["app.py"],
            "estimated_complexity": "Medium",
            "rollback_plan": "none",
        },
    ),
    (
        "invalid_step_numbering_gap.json",
        {
            "goal": "Step numbering gap",
            "steps": [
                {
                    "step_number": 1,
                    "tool_name": "read_file",
                    "tool_arguments": {"path": "app.py"},
                    "expected_outcome": "read",
                    "rollback_action": "none",
                },
                {
                    "step_number": 4,
                    "tool_name": "apply_patch",
                    "tool_arguments": {
                        "path": "app.py",
                        "original_chunk": "a",
                        "replacement_chunk": "b",
                        "line_number": 1,
                    },
                    "expected_outcome": "patch",
                    "rollback_action": "none",
                },
            ],
            "affected_files": ["app.py"],
            "estimated_complexity": "Medium",
            "rollback_plan": "none",
        },
    ),
]

for filename, payload in rej_cases:
    res = default_validator.validate(payload)
    with open(os.path.join(rejections_dir, filename), "w", encoding="utf-8") as f:
        json.dump(
            {
                "plan_payload": payload,
                "validator_result": res.model_dump(),
            },
            f,
            indent=2,
        )

print("Evidence successfully generated in", ev_dir)

if __name__ == "__main__":
    pass
