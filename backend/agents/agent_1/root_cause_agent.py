import os
import time
import logging
from typing import Any, Dict, Optional

import openai
from app.contracts.schemas import (
    BugFinding, 
    EvidencePack, 
    ContextPack, 
    TriageReport, 
    RootCauseAnalysis
)

logger = logging.getLogger(__name__)

class CitationValidationError(ValueError):
    """Raised when the LLM hallucinates a file path that does not exist."""
    pass

class RootCauseAgent:
    """
    Agent 1 (Diagnosis) - Root Cause Node (Task 11).
    Diagnoses the exact mechanism of a bug and validates evidence citations.
    """
    def __init__(self, workspace_path: str, model_name: str = "gpt-4o", temperature: float = 0.0):
        self.workspace_path = workspace_path
        self.model_name = model_name
        self.temperature = temperature
        self.client = openai.OpenAI()
        
    def _validate_citations(self, rca: RootCauseAnalysis) -> None:
        """Validates that the culprit file path actually exists in the workspace."""
        abs_path = os.path.join(self.workspace_path, rca.file_path)
        if not os.path.isfile(abs_path):
            raise CitationValidationError(
                f"LLM Hallucination Blocked: The cited file '{rca.file_path}' does not exist in the repository."
            )

    def analyze(self, 
                finding: BugFinding, 
                context: ContextPack,
                triage: TriageReport,
                evidence: Optional[EvidencePack] = None) -> RootCauseAnalysis:
        start_time = time.time()
        
        system_prompt = (
            "You are an elite autonomous debugging agent. "
            "Your objective is to perform a rigorous Root Cause Analysis on the provided bug finding.\n\n"
            "RULES:\n"
            "1. MULTI-HYPOTHESIS GENERATION: You MUST generate at least 2 distinct hypotheses for why the bug occurred (e.g., race condition vs logical error vs missing validation).\n"
            "2. CROSS-EXAMINATION: For each hypothesis, you must actively search for both supporting evidence and contradicting evidence. List specific line numbers and snippets.\n"
            "3. RANKING & SELECTION: Rank the hypotheses by confidence score (0.0 to 1.0) based on the net evidence. The winning hypothesis becomes the primary diagnosis.\n"
            "4. ZERO UNGROUNDED HALLUCINATIONS: You must only cite files and logic that actually exist in the provided ContextPack.\n"
            "5. FILL THE SCHEMA: Output the full `hypothesis_tree` array, and set the top-level fields (like 'mechanism', 'file_path', 'root_cause') based on the winning hypothesis.\n"
            "6. Make sure 'file_path' precisely matches the path of the culprit file as provided in the context."
        )
        
        user_prompt = (
            f"Bug Finding:\n{finding.model_dump_json(indent=2)}\n\n"
            f"Triage Report:\n{triage.model_dump_json(indent=2)}\n\n"
        )
        if evidence:
            user_prompt += f"Evidence Pack:\n{evidence.model_dump_json(indent=2)}\n\n"
            
        user_prompt += f"Context Pack:\n{context.model_dump_json(indent=2)}"
        
        logger.info(f"Starting Root Cause Analysis for Bug: {finding.id}")
        
        response = self.client.beta.chat.completions.parse(
            model=self.model_name,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=RootCauseAnalysis,
        )
        
        rca = response.choices[0].message.parsed
        if rca is None:
            raise ValueError("Failed to parse RootCauseAnalysis from LLM output")
            
        # Step 3: Run the Citation Validator
        self._validate_citations(rca)
        
        duration = time.time() - start_time
        logger.info(f"Root Cause Analysis completed in {duration:.2f}s for Bug: {finding.id}")
        
        return rca
