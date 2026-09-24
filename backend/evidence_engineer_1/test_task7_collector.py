import os
import sys
import time
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.evidence.collector import build_evidence_pack, sanitize_logs
from app.contracts.schemas import BugFinding

def test_evidence_collector():
    # 1. Setup mock data
    finding = BugFinding(
        id="FINDING-BUG-001",
        title="Null pointer dereference",
        description="Unchecked access token header leads to uncaught exception.",
        stack_trace="Traceback (most recent call last):\n  File 'src/auth/handler.ts', line 42",
        files_hint=["src/auth/handler.ts"],
        environment={"os": "mock-os"}
    )
    
    log_file_path = os.path.join(os.path.dirname(__file__), "dummy_app.log")
    workspace_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 2. Execute collector and measure time
    start_time = time.time()
    pack = build_evidence_pack(finding, workspace_path=workspace_path, log_file_path=log_file_path)
    duration = time.time() - start_time
    
    # 3. Assert Performance (< 3.0s)
    assert duration < 3.0, f"Evidence collector took {duration:.2f}s, expected < 3.0s"
    
    # 4. Assert Content completeness
    assert pack.stack_trace == finding.stack_trace
    assert pack.commit_hash != "unknown_commit", "Git commit hash should be resolved"
    assert "git_branch" in pack.environment
    assert "python_version" in pack.environment
    
    # Assert logs captured (at least some lines, dummy file has 17 lines)
    assert len(pack.logs) > 0
    assert len(pack.logs) >= 15 # Because context is +/-50 lines around the error
    
    # 5. Assert Log sanitization
    logs_str = "".join(pack.logs)
    assert "abcdef123456" not in logs_str, "Bearer token was not sanitized!"
    assert "supersecret_api_key_99" not in logs_str, "API key was not sanitized!"
    assert "Bearer ***" in logs_str or "Bearer***" in logs_str
    
    print(f"[SUCCESS] Task 7 Collector passed in {duration:.2f}s!")

if __name__ == "__main__":
    test_evidence_collector()
