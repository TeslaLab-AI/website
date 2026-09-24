"""
Purpose:
Test fixtures for Engineer 3 Day 3 deliverables (Tasks 37, 38, 39).

Includes:
1. Closed-Loop Bug -> PR fixture environment (Task 37)
2. 2 Seeded Dependency Findings (Task 38 / AC-E3-D3-02):
   - Finding A: Python package (requests 2.25.1 -> 2.31.0 in pyproject.toml)
   - Finding B: JavaScript/Python package (pydantic 1.8.2 -> 2.4.2 with breaking API migration)
3. Seeded SQL Injection Security Finding for SAST Remediation (Task 39 / AC-E3-D3-03)
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import Dict, Any

from agents.agent_3.day3_models import DependencyFinding


# ─────────────────────────────────────────────────────────────────────────────
# 1. Closed-Loop PR Git Repository Setup (Task 37)
# ─────────────────────────────────────────────────────────────────────────────

def setup_git_repo_for_pr(tmp_dir: str) -> Dict[str, str]:
    """
    Initializes a real git repository with initial commit and bare remote
    to test automated task branch creation, push, and PR opening offline.
    """
    # Create bare remote repository
    remote_dir = os.path.join(tmp_dir, "remote.git")
    os.makedirs(remote_dir, exist_ok=True)
    subprocess.run(["git", "init", "--bare", remote_dir], check=True, capture_output=True)

    # Create local working clone / repository
    work_dir = os.path.join(tmp_dir, "worktree")
    os.makedirs(work_dir, exist_ok=True)
    subprocess.run(["git", "init", work_dir], check=True, capture_output=True)

    # Configure local git user
    subprocess.run(["git", "-C", work_dir, "config", "user.name", "TeslaLab Agent 3"], check=True)
    subprocess.run(["git", "-C", work_dir, "config", "user.email", "agent3@teslalab.ai"], check=True)

    # Create initial file and commit
    readme = os.path.join(work_dir, "README.md")
    with open(readme, "w", encoding="utf-8") as f:
        f.write("# TeslaLab AI — Autonomous Finding Workspace\n")

    subprocess.run(["git", "-C", work_dir, "add", "README.md"], check=True)
    subprocess.run(["git", "-C", work_dir, "commit", "-m", "chore: initial commit"], check=True)
    subprocess.run(["git", "-C", work_dir, "branch", "-M", "main"], check=True)

    # Attach remote
    subprocess.run(["git", "-C", work_dir, "remote", "add", "origin", remote_dir], check=True)
    subprocess.run(["git", "-C", work_dir, "push", "-u", "origin", "main"], check=True)

    return {
        "worktree": work_dir,
        "remote": remote_dir,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dependency Agent Seeded Repositories (Task 38)
# ─────────────────────────────────────────────────────────────────────────────

SEEDED_DEP_FINDING_REQUESTS = DependencyFinding(
    package="requests",
    current_version="2.25.1",
    target_version="2.31.0",
    advisory_id="CVE-2023-32681",
    severity="HIGH",
    description="Unintended leak of Proxy-Authorization header during cross-origin redirect",
    ecosystem="pip",
)

SEEDED_DEP_FINDING_PYDANTIC = DependencyFinding(
    package="pydantic",
    current_version="1.8.2",
    target_version="2.4.2",
    advisory_id="GHSA-pydantic-v2-upgrade",
    severity="MODERATE",
    description="Breaking change upgrade to Pydantic V2 (parse_obj -> model_validate)",
    ecosystem="pip",
)


def setup_dependency_repo_pyproject(tmp_dir: str) -> Dict[str, str]:
    """
    Sets up a repository using pyproject.toml with outdated 'requests = 2.25.1'
    and call sites in src/client/api.py.
    """
    src_dir = os.path.join(tmp_dir, "src", "client")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    pyproject_file = os.path.join(tmp_dir, "pyproject.toml")
    with open(pyproject_file, "w", encoding="utf-8") as f:
        f.write("""[project]
name = "teslalab-service"
version = "0.1.0"
dependencies = [
    "requests==2.25.1",
    "pytest>=7.0.0"
]
""")

    client_file = os.path.join(src_dir, "api.py")
    with open(client_file, "w", encoding="utf-8") as f:
        f.write("""try:
    import requests
except ImportError:
    requests = None

def fetch_telemetry(url: str) -> int:
    # Uses requests library
    return 200
""")

    test_file = os.path.join(test_dir, "test_api.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("""from src.client.api import fetch_telemetry

def test_fetch():
    assert fetch_telemetry("http://example.com") == 200
""")

    return {
        "manifest": pyproject_file,
        "source": client_file,
        "test": test_file,
    }


def setup_dependency_repo_breaking_api(tmp_dir: str) -> Dict[str, str]:
    """
    Sets up a repository using requirements.txt with 'pydantic==1.8.2'
    where call sites use deprecated 'parse_obj()'.
    """
    src_dir = os.path.join(tmp_dir, "src", "models")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    req_file = os.path.join(tmp_dir, "requirements.txt")
    with open(req_file, "w", encoding="utf-8") as f:
        f.write("pydantic==1.8.2\npytest>=7.0.0\n")

    user_model_file = os.path.join(src_dir, "user.py")
    with open(user_model_file, "w", encoding="utf-8") as f:
        f.write("""from pydantic import BaseModel

class UserModel(BaseModel):
    username: str
    role: str

def parse_user_payload(data: dict) -> UserModel:
    # Deprecated V1 API: parse_obj
    return UserModel.parse_obj(data)
""")

    test_file = os.path.join(test_dir, "test_user_model.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("""from src.models.user import parse_user_payload

def test_user_parsing():
    user = parse_user_payload({"username": "alice", "role": "admin"})
    assert user.username == "alice"
    assert user.role == "admin"
""")

    return {
        "manifest": req_file,
        "source": user_model_file,
        "test": test_file,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Security Remediation Seeded Repository (Task 39)
# ─────────────────────────────────────────────────────────────────────────────

def setup_security_remediation_repo(tmp_dir: str) -> Dict[str, str]:
    """
    Sets up a repository with a clear CWE-89 SQL Injection defect in src/db/repo.py.
    Pre-remediation SAST scanner detects 1 finding. Post-remediation SAST must detect 0.
    """
    src_dir = os.path.join(tmp_dir, "src", "db")
    test_dir = os.path.join(tmp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    repo_file = os.path.join(src_dir, "user_repo.py")
    with open(repo_file, "w", encoding="utf-8") as f:
        f.write("""def find_user_by_tier(cursor, tier_name: str) -> list:
    # VULNERABILITY: Raw string formatting leads to CWE-89 SQL Injection
    cursor.execute(f"SELECT * FROM users WHERE tier = '{tier_name}'")
    return cursor.fetchall()
""")

    test_file = os.path.join(test_dir, "test_user_repo.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("""class MockCursor:
    def __init__(self):
        self.last_query = None
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchall(self):
        return [{"id": 1, "tier": "gold"}]

from src.db.user_repo import find_user_by_tier

def test_query_execution():
    cur = MockCursor()
    res = find_user_by_tier(cur, "gold")
    assert len(res) == 1
    assert res[0]["tier"] == "gold"
""")

    return {
        "source": repo_file,
        "test": test_file,
    }
