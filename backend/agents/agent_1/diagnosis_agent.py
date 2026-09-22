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

    def execute_investigation(self, finding_id: str, session_id: str) -> Dict[str, Any]:
        """Runs the LangGraph session end-to-end for the given finding."""
        ingest_result = self.start_investigation(finding_id)
        
        finding_info = self.ingestion_service.get_seeded_findings()
        finding_dict = next((f for f in finding_info if f["id"] == finding_id), None)
        if not finding_dict:
            # Fallback for dynamic test findings
            finding_dict = {
                "id": finding_id,
                "category": "bugs",
                "severity": "medium",
                "title": f"Dynamic Test Finding {finding_id}",
                "description": "Auto-generated finding for testing",
                "file_path": "src/index.ts",
                "line_number": 1
            }
            
        from app.contracts.schemas import BugFinding
        from app.evidence.collector import build_evidence_pack
        
        _st = finding_dict.get("stack_trace")
        _fp = finding_dict.get("file_path")
        _env = finding_dict.get("environment", {})
        
        bug_finding = BugFinding(
            id=finding_id,
            title=str(finding_dict.get("title", "Unknown")),
            description=str(finding_dict.get("description", "Unknown")),
            stack_trace=str(_st) if _st else None,
            files_hint=[str(_fp)] if _fp else [],
            environment=_env if isinstance(_env, dict) else {}
        )
        
        pack = build_evidence_pack(bug_finding, workspace_path=None, log_file_path=None)
        
        initial_state = {
            "session_id": session_id,
            "task_id": ingest_result["task_id"],
            "workspace_id": self.workspace_id,
            "current_state": SessionState.CREATED.value,
            "history": [],
            "error": None,
            "bug_finding": bug_finding.model_dump(),
            "evidence_pack": pack.model_dump(),
            "triage_report": None,
            "root_cause_analysis": None,
            "hypotheses": None
        }
        
        if not self.graph:
            raise RuntimeError("Graph could not be compiled (LangGraph missing?)")
            
        final_state = self.graph.invoke(initial_state)
        return final_state
