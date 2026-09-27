import os
import time
import json
import tempfile
from app.contracts.schemas import (
    BugFinding,
    TriageReport,
    ContextPack,
    CodeChunk,
    TriageSeverity
)
from agents.agent_1.root_cause_agent import RootCauseAgent

BUG_002 = {
    "id": "FINDING-BUG-002",
    "title": "Race condition in session cache",
    "description": "Simultaneous token refresh corrupts memory cache entries.",
    "file_path": "src/cache/session.ts",
    "content": "let cache = {};\nasync function refresh(id) {\n  const val = await fetchToken(id);\n  // Bug: race condition assigning to global cache\n  cache[id] = val;\n}"
}

def test_hypothesis_generation():
    with tempfile.TemporaryDirectory() as temp_dir:
        agent = RootCauseAgent(workspace_path=temp_dir, model_name="gpt-4o", temperature=0.3)
        
        abs_path = os.path.join(temp_dir, BUG_002["file_path"])
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w") as f:
            f.write(BUG_002["content"])
            
        finding = BugFinding(
            id=BUG_002["id"],
            title=BUG_002["title"],
            description=BUG_002["description"],
            files_hint=[BUG_002["file_path"]]
        )
        
        triage = TriageReport(
            is_reproducible=True,
            subsystem="backend",
            severity=TriageSeverity.P1,
            estimated_complexity="medium",
            auto_fix_feasible=True,
            reason="Race condition suspected."
        )
        
        context = ContextPack(
            chunks=[CodeChunk(
                file_path=BUG_002["file_path"],
                content=BUG_002["content"],
                start_line=1,
                end_line=5
            )],
            total_tokens=50
        )
        
        start_time = time.time()
        rca = agent.analyze(finding=finding, context=context, triage=triage)
        duration = time.time() - start_time
        
        # Save output for review
        os.makedirs("evidence", exist_ok=True)
        with open("evidence/task12_hypothesis_matrix.json", "w") as f:
            json.dump({
                "duration": duration,
                "rca": rca.model_dump()
            }, f, indent=2)
            
        # Assertions
        assert len(rca.hypothesis_tree) >= 2, f"Expected >= 2 hypotheses, got {len(rca.hypothesis_tree)}"
        
        for hyp in rca.hypothesis_tree:
            assert hasattr(hyp, "contradicting_evidence")
            
        # Check that the winning hypothesis is a race condition
        assert "race" in rca.mechanism.lower() or "concurrency" in rca.mechanism.lower(), f"Winner mechanism '{rca.mechanism}' doesn't mention race condition."
