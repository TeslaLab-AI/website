"""
Purpose:
Three specialized triage agents run in parallel to analyze a finding.
Each produces a structured task description from a different lens.

Agents:
- BugFixAgent: understands root cause and fix approach for logic/code bugs
- SecurityAgent: maps CWE, attack surface, and security-specific fix strategy
- DependencyAgent: identifies safe versions and CVE details for dependency issues
"""

from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import openai

client = openai.OpenAI()


@dataclass
class TriageResult:
    agent: str           # "bug" | "security" | "dependency"
    problem: str         # What is wrong
    approach: str        # How to fix it
    risk: str            # Low | Medium | High
    confidence: float    # 0.0 - 1.0 (self-reported by the LLM)
    extra: dict[str, Any]   # Agent-specific fields


def _call_bug_agent(finding: dict, file_content: str) -> TriageResult:
    prompt = f"""You are a Bug Fix Agent. Analyze the following code finding and produce a JSON response.

Finding:
  title: {finding['title']}
  description: {finding['description']}
  file: {finding['file_path']}
  line: {finding['line_number']}
  severity: {finding['severity']}

File Content:
{file_content[:4000]}

Respond with a JSON object with exactly these fields:
{{
  "problem": "one sentence describing the root cause",
  "approach": "one paragraph describing how to fix it precisely",
  "risk": "Low|Medium|High",
  "confidence": 0.0-1.0,
  "affects_other_files": true|false
}}"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    data = json.loads(res.choices[0].message.content or "{}")
    return TriageResult(
        agent="bug",
        problem=data.get("problem", ""),
        approach=data.get("approach", ""),
        risk=data.get("risk", "Medium"),
        confidence=float(data.get("confidence", 0.5)),
        extra={"affects_other_files": data.get("affects_other_files", False)},
    )


def _call_security_agent(finding: dict, file_content: str) -> TriageResult:
    prompt = f"""You are a Senior Security Engineer Agent. Analyze the following security finding.

Finding:
  title: {finding['title']}
  description: {finding['description']}
  file: {finding['file_path']}
  line: {finding['line_number']}
  severity: {finding['severity']}

File Content:
{file_content[:4000]}

Analyze the security context thoroughly:
1. Application Architecture: Determine if this is a stateless REST API (using Authorization headers / API keys) or a stateful web app (using browser session cookies).
2. Modern Security Practices:
   - For CSRF on stateless APIs without session cookies, avoid deprecated packages (e.g., 'csurf' is deprecated in Express); explain that CORS origin restrictions and custom headers (e.g. Authorization or X-Requested-With) provide robust protection.
   - If cookie-based CSRF protection is strictly required, state all prerequisite middleware (e.g. cookie-parser must precede csurf) and the necessity of a token endpoint (e.g. GET /api/csrf-token) so client requests are not broken.
   - Never recommend applying middleware both globally (app.use) and redundantly on individual route handlers.
3. Prerequisite Dependencies: Identify any new packages that must be declared in package.json or requirements.txt.

Respond with a JSON object:
{{
  "problem": "what vulnerability exists and how it could be exploited in this specific context",
  "approach": "precise security fix including any input validation, sanitization, prerequisite middleware, and dependency manifest updates",
  "risk": "Low|Medium|High",
  "confidence": 0.0-1.0,
  "cwe": "CWE-XXX or empty string if unknown",
  "attack_surface": "brief description of attack surface"
}}"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    data = json.loads(res.choices[0].message.content or "{}")
    return TriageResult(
        agent="security",
        problem=data.get("problem", ""),
        approach=data.get("approach", ""),
        risk=data.get("risk", "High"),
        confidence=float(data.get("confidence", 0.5)),
        extra={"cwe": data.get("cwe", ""), "attack_surface": data.get("attack_surface", "")},
    )


def _call_dependency_agent(finding: dict, file_content: str) -> TriageResult:
    prompt = f"""You are a Dependency Security Agent. Analyze this dependency finding.

Finding:
  title: {finding['title']}
  description: {finding['description']}
  file: {finding['file_path']}
  severity: {finding['severity']}

File Content (dependency manifest):
{file_content[:3000]}

Respond with a JSON object:
{{
  "problem": "which package is vulnerable and why",
  "approach": "which version to upgrade to and how (e.g. change package.json line X to version Y)",
  "risk": "Low|Medium|High",
  "confidence": 0.0-1.0,
  "safe_version": "the recommended safe version string or empty if unknown",
  "cve": "CVE-XXXX-XXXXX or empty string if unknown"
}}"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    data = json.loads(res.choices[0].message.content or "{}")
    return TriageResult(
        agent="dependency",
        problem=data.get("problem", ""),
        approach=data.get("approach", ""),
        risk=data.get("risk", "Medium"),
        confidence=float(data.get("confidence", 0.5)),
        extra={"safe_version": data.get("safe_version", ""), "cve": data.get("cve", "")},
    )


def run_triage_agents(finding: dict, file_content: str) -> list[TriageResult]:
    """
    Runs all three triage agents in parallel and returns their results.
    Failed agents are silently dropped — at least one must succeed.
    """
    results: list[TriageResult] = []
    fns = [_call_bug_agent, _call_security_agent, _call_dependency_agent]

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn, finding, file_content): fn.__name__ for fn in fns}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                print(f"Triage agent {futures[future]} failed: {e}")

    if not results:
        raise RuntimeError("All triage agents failed — cannot proceed with fix.")

    return results
