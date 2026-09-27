"""
TeslaLab AI — Finding Ingestion Bridge for app.agents.agent_1.
"""

try:
    from backend.agents.agent_1.finding_ingestion import (
        FindingIngestionService,
        SEEDED_FINDINGS,
        _memory_tasks,
        _memory_sessions,
        _memory_events,
        _db_headers,
    )
except (ImportError, ModuleNotFoundError):
    from agents.agent_1.finding_ingestion import (
        FindingIngestionService,
        SEEDED_FINDINGS,
        _memory_tasks,
        _memory_sessions,
        _memory_events,
        _db_headers,
    )

__all__ = [
    "FindingIngestionService",
    "SEEDED_FINDINGS",
    "_memory_tasks",
    "_memory_sessions",
    "_memory_events",
    "_db_headers",
]
