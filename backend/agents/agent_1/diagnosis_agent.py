"""
TeslaLab AI — Agent 1: Diagnosis & Foundation Lead
Module: Diagnosis Agent & Triage Coordinator.

Responsibilities:
- Inspect code findings and triage by severity and category.
- Formulate reproduction hypotheses and root cause analyses.
- Interface with 13-state engine and finding ingestion.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from app.contracts.schemas import (
    Finding,
    FindingCategory,
    FindingSeverity,
    SessionState,
)
from agents.agent_1.session_engine import validate_transition, create_session_graph
from agents.agent_1.finding_ingestion import FindingIngestionService


class DiagnosisAgent:
    """Agent 1: Specialized diagnosis and root cause analysis agent."""

    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.ingestion_service = FindingIngestionService()
        self.graph = create_session_graph()

    def triage_finding(self, finding_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Triages an incoming finding and determines the diagnosis strategy.
        """
        category = finding_data.get("category", FindingCategory.BUGS.value)
        severity = finding_data.get("severity", FindingSeverity.MEDIUM.value)
        file_path = finding_data.get("file_path", "")

        strategy = {
            FindingCategory.BUGS.value: "static_flow_and_unit_reproduction",
            FindingCategory.DEPENDENCIES.value: "cve_dependency_graph_inspection",
            FindingCategory.SECURITY.value: "secret_and_taint_path_analysis",
            FindingCategory.TESTING.value: "test_suite_coverage_and_regression_harness",
        }.get(category, "general_investigation")

        return {
            "finding_id": finding_data.get("id"),
            "category": category,
            "severity": severity,
            "target_file": file_path,
            "strategy": strategy,
            "triaged_at": datetime.now(timezone.utc).isoformat(),
        }

    def start_investigation(self, finding_id: str) -> Dict[str, Any]:
        """Ingests the finding and initiates the 13-state session."""
        return self.ingestion_service.ingest(finding_id, self.workspace_id)
