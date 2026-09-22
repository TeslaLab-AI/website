import os
import sys
import time
import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.security import SecurityException
from app.tools.repo_tools import (
    find_files_by_name,
    search_code,
    read_file_chunk,
    get_symbol_definition,
    find_references,
)

def test_repo_sandbox():
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Path traversal attack
    with pytest.raises(SecurityException):
        read_file_chunk("../../etc/passwd", 1, 10, workspace_path=workspace)
        
    with pytest.raises(SecurityException):
        read_file_chunk("../outside_repo.txt", 1, 10, workspace_path=workspace)

def test_tools_execution_time():
    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 1. find_files_by_name
    t0 = time.time()
    files = find_files_by_name("*.py", workspace_path=workspace)
    assert time.time() - t0 < 0.2, "find_files_by_name exceeded 200ms"
    assert len(files) > 0

    # 2. search_code
    t0 = time.time()
    res = search_code("def get_symbol_definition", workspace_path=workspace)
    assert time.time() - t0 < 0.2, "search_code exceeded 200ms"
    assert "repo_tools.py" in res or res != "No matches found."

    # 3. read_file_chunk
    t0 = time.time()
    chunk = read_file_chunk("requirements.txt", 1, 5, workspace_path=workspace)
    assert time.time() - t0 < 0.2, "read_file_chunk exceeded 200ms"
    assert len(chunk) > 0

    # 4. get_symbol_definition
    t0 = time.time()
    # Looking up definition of search_code in repo_tools.py
    definition = get_symbol_definition("app/tools/repo_tools.py", "search_code", "python", workspace_path=workspace)
    assert time.time() - t0 < 0.2, "get_symbol_definition exceeded 200ms"
    assert "def search_code" in definition

    # 5. find_references
    t0 = time.time()
    refs = find_references("app/tools/repo_tools.py", "workspace_path", "python", workspace_path=workspace)
    assert time.time() - t0 < 0.2, "find_references exceeded 200ms"
    assert "workspace_path" in refs

    print("[SUCCESS] All tools executed under 200ms and passed security sandbox!")

if __name__ == "__main__":
    test_repo_sandbox()
    test_tools_execution_time()
