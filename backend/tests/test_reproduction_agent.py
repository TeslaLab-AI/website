import pytest
import os
from app.contracts.schemas import BugFinding, RootCauseAnalysis
from agents.agent_1.reproduction_agent import ReproductionAgent

def test_reproduction_agent():
    # Arrange
    workspace_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace_path = os.path.dirname(workspace_path) # go up to website directory which has .git
    
    agent = ReproductionAgent(workspace_path=workspace_path, temperature=0.0)
    
    # Let's create a real bug in the workspace so the LLM test can actually import it and fail
    buggy_code_path = os.path.join(workspace_path, "dummy_math.py")
    with open(buggy_code_path, "w") as f:
        f.write("def divide(a, b):\n    return a / b\n")
        
    finding = BugFinding(
        id="bug-123",
        title="Division by zero in dummy_math",
        description="Calling divide(10, 0) crashes.",
        files_hint=["dummy_math.py"],
        environment={}
    )
    
    rca = RootCauseAnalysis(
        finding_id="bug-123",
        title="Division by zero in dummy_math",
        description="Calling divide(10, 0) crashes.",
        file_path="dummy_math.py",
        line_number=2,
        root_cause="No check for b == 0",
        suggested_fix="Add if b == 0: raise ValueError()",
        mechanism="ZeroDivisionError occurs",
        confidence_score=1.0,
    )
    
    try:
        # Act
        result = agent.run(finding=finding, rca=rca)
        
        # Assert
        assert result is not None
        assert "def test_" in result.script_code or "import" in result.script_code
        # It should fail cleanly because the bug exists in dummy_math.py
        assert result.exit_code == 1
        assert result.is_verified_failure is True
        assert "ZeroDivisionError" in result.execution_log or "failed" in result.execution_log.lower()
    finally:
        if os.path.exists(buggy_code_path):
            os.remove(buggy_code_path)
