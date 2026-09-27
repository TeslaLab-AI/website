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
from agents.agent_1.root_cause_agent import RootCauseAgent, CitationValidationError

BUGS = [
    {
        "id": "FINDING-BUG-001",
        "title": "Null pointer dereference in auth handler",
        "description": "Unchecked access token header leads to uncaught exception under high load.",
        "file_path": "src/auth/handler.ts",
        "content": "function authenticate(req) {\n  const token = req.headers.authorization;\n  // Bug: no null check on token\n  const parts = token.split(' ');\n  return parts[1];\n}"
    },
    {
        "id": "FINDING-BUG-002",
        "title": "Race condition in session cache",
        "description": "Simultaneous token refresh corrupts memory cache entries.",
        "file_path": "src/cache/session.ts",
        "content": "let cache = {};\nasync function refresh(id) {\n  const val = await fetchToken(id);\n  // Bug: race condition assigning to global cache\n  cache[id] = val;\n}"
    },
    {
        "id": "FINDING-BUG-003",
        "title": "Off-by-one error in pagination slice",
        "description": "Page bounds check incorrectly truncates the last result record.",
        "file_path": "src/api/paginate.ts",
        "content": "function getPage(results, page, size) {\n  const start = page * size;\n  const end = start + size - 1; // Bug: should be start + size\n  return results.slice(start, end);\n}"
    },
    {
        "id": "FINDING-SEC-001",
        "title": "Hardcoded cryptographic fallback key",
        "description": "Fallback HMAC key exposed in client-accessible bundle constants.",
        "file_path": "src/crypto/jwt.ts",
        "content": "export const FALLBACK_KEY = 'super_secret_dev_key_123'; // Bug: hardcoded secret\nexport function sign(data) { return HMAC(data, FALLBACK_KEY); }"
    },
    {
        "id": "FINDING-BUG-005",
        "title": "Uncaught JSON parse error",
        "description": "Fails when external API returns invalid HTML instead of JSON.",
        "file_path": "src/api/external.ts",
        "content": "async function fetchUser() {\n  const res = await fetch('/api/user');\n  const data = JSON.parse(await res.text()); // Bug: can throw SyntaxError\n  return data;\n}"
    }
]

def test_root_cause_benchmark():
    # Setup a dummy workspace to satisfy the Evidence Citation Validator
    with tempfile.TemporaryDirectory() as temp_dir:
        agent = RootCauseAgent(workspace_path=temp_dir, model_name="gpt-4o-mini", temperature=0.0)
        
        reports = []
        correct_count = 0
        
        for bug_data in BUGS:
            # Write dummy file so validator passes
            abs_path = os.path.join(temp_dir, bug_data["file_path"])
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w") as f:
                f.write(bug_data["content"])
                
            finding = BugFinding(
                id=bug_data["id"],
                title=bug_data["title"],
                description=bug_data["description"],
                files_hint=[bug_data["file_path"]]
            )
            
            triage = TriageReport(
                is_reproducible=True,
                subsystem="backend",
                severity=TriageSeverity.P1,
                estimated_complexity="low",
                auto_fix_feasible=True,
                reason="Clear stack trace"
            )
            
            context = ContextPack(
                chunks=[CodeChunk(
                    file_path=bug_data["file_path"],
                    content=bug_data["content"],
                    start_line=1,
                    end_line=5
                )],
                total_tokens=50
            )
            
            start_time = time.time()
            rca = agent.analyze(finding=finding, context=context, triage=triage)
            duration = time.time() - start_time
            
            reports.append({
                "finding_id": finding.id,
                "duration": duration,
                "rca": rca.model_dump()
            })
            
            # Assertions for accuracy (Definition of Done)
            if rca.file_path == bug_data["file_path"] and len(rca.evidence_references) > 0:
                correct_count += 1
                
        # Save evidence
        os.makedirs("evidence", exist_ok=True)
        with open("evidence/task11_rca_reports.json", "w") as f:
            json.dump(reports, f, indent=2)
            
        assert correct_count >= 4, f"Only got {correct_count}/5 correct RCAs, expected >= 4"

def test_citation_validator_blocks_hallucinations():
    with tempfile.TemporaryDirectory() as temp_dir:
        agent = RootCauseAgent(workspace_path=temp_dir, model_name="gpt-4o-mini", temperature=0.0)
        
        # We purposely do NOT write the file to the workspace
        bug_data = BUGS[0]
        finding = BugFinding(
            id=bug_data["id"],
            title=bug_data["title"],
            description=bug_data["description"]
        )
        triage = TriageReport(
            is_reproducible=True, subsystem="backend", severity=TriageSeverity.P1,
            estimated_complexity="low", auto_fix_feasible=True, reason="valid"
        )
        context = ContextPack(chunks=[CodeChunk(file_path="fake/path.ts", content="code", start_line=1, end_line=5)])
        
        try:
            agent.analyze(finding=finding, context=context, triage=triage)
            assert False, "Should have raised CitationValidationError for missing file!"
        except CitationValidationError:
            pass # Expected behavior
