"""
Purpose:
Task Normalizer — merges outputs from all triage agents into a single
NormalizedTask that the Planner Agent will use.

Strategy:
- Pick the highest-confidence TriageResult as the primary source.
- Merge problem descriptions and approaches from all agents as context.
- Produce a structured NormalizedTask with clear success_criteria.
"""

from __future__ import annotations
from dataclasses import dataclass

from app.agents.agent_1.triage_agents import TriageResult


@dataclass
class NormalizedTask:
    file_path: str
    line_number: int
    problem: str            # Merged problem description (primary agent first)
    fix_strategy: str       # Merged approach from all agents
    risk: str               # Highest risk level across all agents
    success_criteria: str   # What "fixed" looks like
    primary_agent: str      # Which agent had highest confidence
    extra_context: str      # Additional notes from secondary agents


_RISK_ORDER = {"Low": 0, "Medium": 1, "High": 2}


def normalize(finding: dict, results: list[TriageResult]) -> NormalizedTask:
    """
    Merge triage agent outputs into a single NormalizedTask.
    """
    # Sort by confidence descending
    sorted_results = sorted(results, key=lambda r: r.confidence, reverse=True)
    primary = sorted_results[0]
    secondary = sorted_results[1:]

    # Highest risk across all agents
    highest_risk = max(results, key=lambda r: _RISK_ORDER.get(r.risk, 1)).risk

    # Merge approaches from all agents as additional context
    extra_notes = []
    for r in secondary:
        if r.problem and r.approach:
            notes = f"[{r.agent.upper()} agent] {r.problem} — {r.approach}"
            # Attach any extra fields
            for k, v in r.extra.items():
                if v:
                    notes += f" ({k}: {v})"
            extra_notes.append(notes)

    # Build success criteria from the primary agent's approach
    success_criteria = (
        f"The fix should resolve: {finding['title']}. "
        f"After the fix, re-running Semgrep on {finding['file_path']} "
        f"should NOT produce a finding at line {finding['line_number']}."
    )

    return NormalizedTask(
        file_path=finding["file_path"],
        line_number=finding.get("line_number", 0),
        problem=primary.problem,
        fix_strategy=primary.approach,
        risk=highest_risk,
        success_criteria=success_criteria,
        primary_agent=primary.agent,
        extra_context="\n".join(extra_notes),
    )
