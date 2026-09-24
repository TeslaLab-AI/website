import pytest
import os
from agents.agent_1.git_history_agent import GitHistoryAgent

def test_git_history_agent_extraction():
    # Arrange
    agent = GitHistoryAgent()
    # Use backend/app/main.py line 1 which was the initial commit
    file_path = "backend/app/main.py"
    line_number = 1
    # Get backend path which is the git repo
    workspace_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace_path = os.path.dirname(workspace_path) # go up to website directory which has .git
    
    # Act
    context = agent.run(file_path=file_path, line_number=line_number, workspace_path=workspace_path)
    
    # Assert
    assert context is not None
    
    print("\n--- GIT HISTORY PAYLOAD ---")
    print(context.model_dump_json(indent=2))
    print("---------------------------\n")
    assert len(context.introducing_commit) >= 7
    assert context.author != "Unknown"
    assert context.date != "Unknown"
    assert len(context.commit_message) > 0
    assert len(context.original_intent_summary) > 0
