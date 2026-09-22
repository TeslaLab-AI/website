import time
import logging
from typing import Optional
import json

import openai
from app.contracts.schemas import BugFinding, EvidencePack, TriageReport

logger = logging.getLogger(__name__)

class TriageAgent:
    """
    Agent 1 (Diagnosis) - Triage Node.
    Classifies bugs based on BugFinding and EvidencePack using a fast LLM.
    """
    
    def __init__(self, model_name: str = "gpt-4o-mini", temperature: float = 0.0):
        # The model_name is now resolved via the ModelRouter, but we accept it for backwards compatibility
        self.temperature = temperature

    def run_triage(self, finding: BugFinding, evidence: Optional[EvidencePack] = None) -> TriageReport:
        """Runs the triage classification."""
        start_time = time.time()
        
        # Serialize inputs
        finding_json = finding.model_dump_json(indent=2)
        evidence_json = evidence.model_dump_json(indent=2) if evidence else "None"
        
        logger.info(f"Starting Triage on Bug: {finding.id}")
        
        system_prompt = (
            "You are an expert software triage engineer. "
            "Your job is to quickly classify a reported bug and determine if it is suitable for automated remediation.\n\n"
            "Rules:\n"
            "1. If the bug lacks sufficient information or a stack trace/log snippet that proves it's real, mark is_reproducible=False.\n"
            "2. Assign a subsystem (e.g., 'frontend', 'backend', 'database', 'auth', 'infrastructure').\n"
            "3. Assign a severity (P0=Critical, P1=High, P2=Medium, P3=Low).\n"
            "4. Estimate complexity (Low, Medium, High).\n"
            "5. If the bug requires human context, requires significant architectural changes, or is not reproducible, mark auto_fix_feasible=False.\n"
            "6. Provide a concise reason for your decision."
        )
        
        user_prompt = f"Bug Finding:\n{finding_json}\n\nEvidence Pack:\n{evidence_json}"
        
        from app.agents.agent_2.router.router import default_router
        response = default_router.complete(
            task_type="triage",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=self.temperature,
            json_schema=TriageReport,
            session_id=finding.id,
        )
        
        result = response.parsed
        
        if result is None:
            raise ValueError("Failed to parse TriageReport from LLM output")
            
        result = TriageReport(**result)
        
        duration = time.time() - start_time
        logger.info(f"Triage completed in {duration:.2f}s for Bug: {finding.id}. Feasible: {result.auto_fix_feasible}")
        return result
