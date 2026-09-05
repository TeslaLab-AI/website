"""
Purpose:
In-memory event bus / state store for agentic fix pipeline runs.

Each run is identified by a unique run_id and tracks:
- Current phase
- Number of attempts
- Log messages with timestamps
- Final result (on completion)
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

# run_state[run_id] = RunState dict
run_state: dict[str, dict[str, Any]] = {}


def init_run(run_id: str, finding_id: str, repository_id: str) -> None:
    """Initialize a new pipeline run."""
    run_state[run_id] = {
        "run_id": run_id,
        "finding_id": finding_id,
        "repository_id": repository_id,
        "status": "running",           # running | completed | failed
        "phase": "initializing",       # triage | normalize | plan | execute | test | verify | pr | done
        "attempts": 0,
        "logs": [],
        "result": None,                # populated on completion
        "error": None,                 # populated on failure
    }


def get_run(run_id: str) -> dict[str, Any] | None:
    return run_state.get(run_id)


def update_phase(run_id: str, phase: str, message: str) -> None:
    if run_id not in run_state:
        return
    state = run_state[run_id]
    state["phase"] = phase
    _log(run_id, f"[{phase.upper()}] {message}")


def increment_attempt(run_id: str) -> None:
    if run_id in run_state:
        run_state[run_id]["attempts"] += 1


def complete_run(run_id: str, result: dict[str, Any]) -> None:
    if run_id not in run_state:
        return
    state = run_state[run_id]
    state["status"] = "completed"
    state["phase"] = "done"
    state["result"] = result
    _log(run_id, "[DONE] Pipeline completed successfully.")


def fail_run(run_id: str, error: str) -> None:
    if run_id not in run_state:
        return
    state = run_state[run_id]
    state["status"] = "failed"
    state["error"] = error
    _log(run_id, f"[FAILED] {error}")


def _log(run_id: str, message: str) -> None:
    if run_id not in run_state:
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    run_state[run_id]["logs"].append({"timestamp": timestamp, "message": message})
    print(f"[AgenticRun {run_id[:8]}] {message}")
