"""
Purpose:
Planner Agent — given a NormalizedTask and file content, generates a FixPlan
using GPT-4o. On failure feedback, acts as Replanner with error context.

Max 3 total attempts (per design decision).
"""

from __future__ import annotations
import json
from dataclasses import dataclass

import openai

from app.agents.normalizer import NormalizedTask
from app.agents.executor import FixPlan, FixStep

client = openai.OpenAI()
MAX_ATTEMPTS = 3


@dataclass
class PlannerInput:
    task: NormalizedTask
    file_content: str
    previous_attempts: list[dict]   # [ { plan, test_result, verify_result } ] for replanning
    manifest_path: str | None = None
    manifest_content: str | None = None


def plan(input: PlannerInput) -> FixPlan:
    """
    Generate a FixPlan. If previous_attempts exist, acts as Replanner
    with context on what went wrong.
    """
    attempt_context = ""
    if input.previous_attempts:
        attempt_context = "\n\n--- PREVIOUS FAILED ATTEMPTS ---\n"
        for i, prev in enumerate(input.previous_attempts, 1):
            attempt_context += f"\nAttempt {i}:\n"
            attempt_context += f"  Plan: {prev.get('plan_explanation', '')}\n"
            attempt_context += f"  Test result: {prev.get('test_result', 'N/A')}\n"
            attempt_context += f"  Verify result: {prev.get('verify_result', 'N/A')}\n"
        attempt_context += "\nDo NOT repeat the same approach. Try a different fix strategy.\n"

    manifest_context = ""
    if input.manifest_path and input.manifest_content:
        manifest_context = f"""
Nearest Package Manifest: {input.manifest_path}
```
{input.manifest_content}
```
IMPORTANT: If your fix requires adding new external dependencies/packages, you MUST include a step updating '{input.manifest_path}' (use this exact relative path, NOT root package.json) to declare them, keeping all existing dependencies intact.
"""

    system_prompt = (
        "You are a Senior Software Architect and Planner Agent in an automated code fixing pipeline. "
        "Your job is to produce a precise, syntactically correct, executable plan to fix a code issue without breaking application runtime or client integration. "
        "Output a JSON object only."
    )

    user_prompt = f"""Fix this issue in the codebase.

Task:
  File: {input.task.file_path}
  Line: {input.task.line_number}
  Problem: {input.task.problem}
  Fix Strategy: {input.task.fix_strategy}
  Risk: {input.task.risk}
  Success Criteria: {input.task.success_criteria}
  Additional Context: {input.task.extra_context}

Current File Content ({input.task.file_path}):
{input.file_content}
{manifest_context}
{attempt_context}

Produce a JSON object with:
{{
  "explanation": "A markdown description of what this plan does and why",
  "risk_level": "Low|Medium|High",
  "steps": [
    {{
      "action": "MODIFY",
      "file_path": "relative/path/to/file.ext",
      "content": "COMPLETE new file content — do NOT truncate, do NOT use ...",
      "delete_confirmed": false
    }}
  ]
}}

CRITICAL ARCHITECTURAL RULES:
1. DEPENDENCY COMPLETENESS & PATH ACCURACY:
   - If your code introduces a new external library/import (e.g. cookie-parser, csurf, bcrypt, cors, etc.), you MUST include an additional step updating the package manifest.
   - Always update the NEAREST manifest for this file: '{input.manifest_path or "package.json / requirements.txt"}'. If the file is in a subfolder (e.g. 'backend/server.js'), update '{input.manifest_path or "backend/package.json"}', NEVER an unintended root manifest.
2. CLIENT INTEGRATION & TOKEN DISTRIBUTION:
   - If you introduce middleware that requires client-side tokens or credentials (such as CSRF protection or Auth guards), you MUST provide an endpoint for consumers to obtain the token (e.g. app.get('/api/csrf-token', ...)), or the frontend will be permanently locked out (HTTP 403).
3. MIDDLEWARE HYGIENE & ORDERING:
   - Never register the same middleware both globally (app.use(middleware)) AND on individual routes (app.post('/path', middleware, ...)). Use either route-level OR global, never both.
   - Always register prerequisite middleware in the correct order (e.g. cookie-parser before csurf, express.json() before route handlers).
4. MODERN SECURITY PREFERENCES:
   - Avoid deprecated libraries (e.g. 'csurf' is deprecated in Express; for stateless REST APIs without session cookies, prefer CORS + custom header verification).
5. CODE INTEGRITY:
   - For MODIFY/CREATE, always return the COMPLETE file content. Never truncate with '# rest of code...' or '// ...'.
   - Only modify files directly related to the fix and its dependencies.
"""

    res = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    data = json.loads(res.choices[0].message.content)

    steps = []
    for s in data.get("steps", []):
        steps.append(FixStep(
            action=s.get("action", "MODIFY"),
            file_path=s.get("file_path", input.task.file_path),
            content=s.get("content"),
            delete_confirmed=s.get("delete_confirmed", False),
        ))

    if not steps:
        raise ValueError("Planner returned no steps.")

    return FixPlan(
        steps=steps,
        explanation=data.get("explanation", "AI-generated fix."),
        risk_level=data.get("risk_level", input.task.risk),
    )
