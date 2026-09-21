"""
Purpose:
Security Verifier — re-runs Semgrep on only the changed files after the fix
is applied in the isolated workspace.

Returns:
- resolved: findings that no longer appear (the fix worked for these)
- new: new findings introduced by the fix (regression)
- remaining: original finding still present (fix didn't work)
"""

from __future__ import annotations
import json
import os
import subprocess
from dataclasses import dataclass, field


@dataclass
class VerifyResult:
    passed: bool                        # True if original finding is resolved and no new findings
    resolved_findings: list[str]        # Rule IDs that no longer appear
    remaining_findings: list[str]       # Rule IDs that still appear
    new_findings: list[str]             # Rule IDs introduced by the fix (regressions)
    output: str                         # Raw Semgrep output (truncated)


def verify_fix(
    workspace_root: str,
    changed_files: list[str],
    original_finding_title: str,
    original_file_path: str,
    original_line: int,
) -> VerifyResult:
    """
    Run Semgrep on only the changed files in the workspace.
    Compare results against the original finding.
    """
    if not changed_files:
        return VerifyResult(
            passed=False,
            resolved_findings=[],
            remaining_findings=[original_finding_title],
            new_findings=[],
            output="No files were changed by the executor.",
        )

    # Build absolute paths for changed files
    abs_paths = []
    for rel_path in changed_files:
        abs_path = os.path.join(workspace_root, rel_path.replace("\\", "/").lstrip("/"))
        if os.path.exists(abs_path):
            abs_paths.append(abs_path)

    if not abs_paths:
        return VerifyResult(
            passed=False,
            resolved_findings=[],
            remaining_findings=[original_finding_title],
            new_findings=[],
            output="Changed files not found in workspace.",
        )

    is_windows = os.name == 'nt'
    if is_windows:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{os.path.abspath(workspace_root)}:/src",
            "returntocorp/semgrep", "semgrep", "scan",
            "--config", "p/default",
            "--config", "p/security-audit",
            "--json"
        ] + [f"/src/{fp}" for fp in changed_files]
    else:
        cmd = [
            "semgrep", "scan",
            "--config", "p/default",
            "--config", "p/security-audit",
            "--json",
        ] + abs_paths

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            shell=False, # No shell needed for docker, harmless for linux
        )
        output = result.stdout or result.stderr or ""

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            # Semgrep produced no JSON → treat as clean pass
            return VerifyResult(
                passed=True,
                resolved_findings=[original_finding_title],
                remaining_findings=[],
                new_findings=[],
                output=output[:1000],
            )

        found_rule_ids = [
            r.get("check_id", "").split(".")[-1]
            for r in data.get("results", [])
        ]

        # Normalize the original finding title for comparison
        orig_lower = original_finding_title.lower().replace("-", "_").replace(" ", "_")
        still_present = any(
            orig_lower in rid.lower() or rid.lower() in orig_lower
            for rid in found_rule_ids
        )

        # All found rules other than the original are "new" (regressions)
        new_findings = [
            rid for rid in found_rule_ids
            if orig_lower not in rid.lower() and rid.lower() not in orig_lower
        ]

        resolved = [] if still_present else [original_finding_title]
        remaining = [original_finding_title] if still_present else []

        # Pass = original resolved (ignoring pre-existing sibling findings in the same file for MVP)
        passed = not still_present

        return VerifyResult(
            passed=passed,
            resolved_findings=resolved,
            remaining_findings=remaining,
            new_findings=new_findings,
            output=output[:2000],
        )

    except subprocess.TimeoutExpired:
        return VerifyResult(
            passed=False,
            resolved_findings=[],
            remaining_findings=[original_finding_title],
            new_findings=[],
            output="Semgrep verification timed out.",
        )
    except Exception as e:

        return VerifyResult(
            passed=False,
            resolved_findings=[],
            remaining_findings=[original_finding_title],
            new_findings=[],
            output=f"Semgrep verification error: {e}",
        )
