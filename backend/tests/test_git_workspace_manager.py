"""
Unit and Integration Tests for GitWorkspaceManager (Engineer 2 — Task 25).

Covers:
- Workspace creation and checkout
- Branch naming compliance (task/<name>)
- Applying changes within isolated worktree
- Generating clean unified git diffs
- Committing changes inside isolated worktree
- Rollback to clean state
- Worktree and branch cleanup
- Protection against accidental operations on main/master
- Path traversal protection
- Concurrency test with 3 concurrent workspaces:
  - distinct task branches
  - different file modifications
  - zero cross-contamination
  - independent rollbacks
  - complete cleanup
"""

import os
from pathlib import Path
import pytest
import shutil
import subprocess
import tempfile

from app.agents.agent_2.git_workspace import (
    GitWorkspaceManager,
    WorkspaceSession,
    WorkspaceState,
    ProtectedBranchError,
    WorkspaceError,
    WorkspaceNotFoundError,
    DiffResult,
    CommitResult,
)


@pytest.fixture
def temp_repo():
    """Create a temporary initialized Git repository with an initial commit."""
    temp_dir = tempfile.mkdtemp(prefix="test_git_repo_")
    repo_path = Path(temp_dir).resolve()

    # Initialize git repository
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@teslalab.ai"], cwd=str(repo_path), check=True, capture_output=True)

    # Create initial seed file and commit on main
    seed_file = repo_path / "README.md"
    seed_file.write_text("# Seed Repository\nInitial commit on main.\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit on main"], cwd=str(repo_path), check=True, capture_output=True)

    yield repo_path

    # Teardown
    for attempt in range(3):
        try:
            shutil.rmtree(repo_path, ignore_errors=False)
            break
        except Exception:
            import time
            time.sleep(0.2)
    if repo_path.exists():
        shutil.rmtree(repo_path, ignore_errors=True)


class TestGitWorkspaceManagerBasic:
    """Basic lifecycle tests for GitWorkspaceManager."""

    def test_01_workspace_creation_and_checkout(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)
        session = mgr.checkout("fix-issue-101")

        assert isinstance(session, WorkspaceSession)
        assert session.task_name == "fix-issue-101"
        assert session.branch_name == "task/fix-issue-101"
        assert session.state == WorkspaceState.ACTIVE
        assert Path(session.worktree_path).exists()
        assert (Path(session.worktree_path) / "README.md").exists()

        # Check git branch inside worktree
        res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=session.worktree_path, capture_output=True, text=True)
        assert res.stdout.strip() == "task/fix-issue-101"

    def test_02_protection_against_main_master(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)

        with pytest.raises(ProtectedBranchError):
            mgr.checkout("main")

        with pytest.raises(ProtectedBranchError):
            mgr.checkout("master")

        with pytest.raises(ProtectedBranchError):
            mgr.checkout("task/main")

        with pytest.raises(ProtectedBranchError):
            mgr.checkout("origin/main")

    def test_03_apply_changes_and_diff(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)
        session = mgr.checkout("apply-patch-test")

        # Apply a modification to a new file and an existing file
        mgr.apply_changes("apply-patch-test", "src/hello.py", "print('Hello world!')\n")
        mgr.apply_changes("apply-patch-test", "README.md", "# Seed Repository\nModified for test.\n")

        # Verify files exist in worktree
        assert (Path(session.worktree_path) / "src" / "hello.py").exists()

        diff_res = mgr.get_diff_result("apply-patch-test")
        assert isinstance(diff_res, DiffResult)
        assert diff_res.has_changes is True
        assert "README.md" in diff_res.files_changed
        assert "src/hello.py" in diff_res.files_changed
        assert "Modified for test." in diff_res.diff

    def test_04_commit_operation(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)
        session = mgr.checkout("commit-test")

        mgr.apply_changes("commit-test", "file_a.txt", "Some content\n")
        commit_res = mgr.commit("commit-test", "feat: add file_a.txt")

        assert isinstance(commit_res, CommitResult)
        assert commit_res.branch == "task/commit-test"
        assert commit_res.message == "feat: add file_a.txt"
        assert "file_a.txt" in commit_res.files_changed
        assert len(commit_res.commit_hash) == 40

        # Diff after commit should be clean
        diff_res = mgr.get_diff_result("commit-test")
        assert diff_res.has_changes is False

    def test_05_rollback_to_clean(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)
        session = mgr.checkout("rollback-test")

        # Modify tracked file and add untracked file
        mgr.apply_changes("rollback-test", "README.md", "Corrupted content\n")
        mgr.apply_changes("rollback-test", "dirty_untracked.txt", "garbage\n")

        diff_res = mgr.get_diff_result("rollback-test")
        assert diff_res.has_changes is True

        # Perform rollback
        is_clean = mgr.rollback_to_clean("rollback-test")
        assert is_clean is True

        # Verify working directory is pristine
        diff_after = mgr.get_diff_result("rollback-test")
        assert diff_after.has_changes is False
        assert not (Path(session.worktree_path) / "dirty_untracked.txt").exists()
        assert (Path(session.worktree_path) / "README.md").read_text() == "# Seed Repository\nInitial commit on main.\n"

    def test_06_cleanup_removes_worktree_and_branch(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)
        session = mgr.checkout("cleanup-test")
        wt_path = Path(session.worktree_path)
        assert wt_path.exists()

        success = mgr.cleanup("cleanup-test", delete_branch=True)
        assert success is True
        assert not wt_path.exists()
        assert not mgr.has_session("cleanup-test")

        # Verify branch is deleted from repo
        res = subprocess.run(["git", "branch", "--list", "task/cleanup-test"], cwd=str(temp_repo), capture_output=True, text=True)
        assert res.stdout.strip() == ""

    def test_07_path_traversal_blocked(self, temp_repo):
        mgr = GitWorkspaceManager(repo_path=temp_repo)
        mgr.checkout("traversal-test")

        with pytest.raises(WorkspaceError, match="Path traversal"):
            mgr.apply_changes("traversal-test", "../../escaped.txt", "Dangerous content")


class TestGitWorkspaceConcurrency:
    """Tests for multi-workspace concurrency and isolation."""

    def test_concurrent_3_workspaces_complete_isolation(self, temp_repo):
        """
        Launches 3 concurrent task workspaces:
        - Workspace A, B, C with own task branches
        - Modifying different test files
        - Generates own clean diffs
        - Verifies zero cross-contamination
        - Independent rollback
        - Complete cleanup
        """
        mgr = GitWorkspaceManager(repo_path=temp_repo)

        # 1. Initialize 3 isolated workspaces
        ws_a = mgr.checkout("task-worker-alpha")
        ws_b = mgr.checkout("task-worker-beta")
        ws_c = mgr.checkout("task-worker-gamma")

        assert ws_a.branch_name == "task/task-worker-alpha"
        assert ws_b.branch_name == "task/task-worker-beta"
        assert ws_c.branch_name == "task/task-worker-gamma"

        path_a = Path(ws_a.worktree_path)
        path_b = Path(ws_b.worktree_path)
        path_c = Path(ws_c.worktree_path)

        assert path_a != path_b and path_b != path_c

        # 2. Modify different files with distinct content
        mgr.apply_changes("task-worker-alpha", "module_a.py", "# Worker Alpha Code\ndef alpha(): return 'A'\n")
        mgr.apply_changes("task-worker-beta", "module_b.py", "# Worker Beta Code\ndef beta(): return 'B'\n")
        mgr.apply_changes("task-worker-gamma", "module_c.py", "# Worker Gamma Code\ndef gamma(): return 'C'\n")

        # 3. Verify Isolation & Zero Cross-Contamination
        # Workspace A must NOT see B or C
        assert (path_a / "module_a.py").exists()
        assert not (path_a / "module_b.py").exists()
        assert not (path_a / "module_c.py").exists()

        # Workspace B must NOT see A or C
        assert (path_b / "module_b.py").exists()
        assert not (path_b / "module_a.py").exists()
        assert not (path_b / "module_c.py").exists()

        # Workspace C must NOT see A or B
        assert (path_c / "module_c.py").exists()
        assert not (path_c / "module_a.py").exists()
        assert not (path_c / "module_b.py").exists()

        # 4. Check Diff Isolation
        diff_a = mgr.get_diff("task-worker-alpha")
        diff_b = mgr.get_diff("task-worker-beta")
        diff_c = mgr.get_diff("task-worker-gamma")

        assert "module_a.py" in diff_a and "module_b.py" not in diff_a and "module_c.py" not in diff_a
        assert "module_b.py" in diff_b and "module_a.py" not in diff_b and "module_c.py" not in diff_b
        assert "module_c.py" in diff_c and "module_a.py" not in diff_c and "module_b.py" not in diff_c

        # 5. Independent Rollback: Roll back B, while A and C remain modified
        mgr.rollback_to_clean("task-worker-beta")

        diff_b_after = mgr.get_diff_result("task-worker-beta")
        assert diff_b_after.has_changes is False
        assert not (path_b / "module_b.py").exists()

        # A and C must remain modified and unaffected
        assert mgr.get_diff_result("task-worker-alpha").has_changes is True
        assert mgr.get_diff_result("task-worker-gamma").has_changes is True
        assert (path_a / "module_a.py").exists()
        assert (path_c / "module_c.py").exists()

        # 6. Commit A, Rollback C
        mgr.commit("task-worker-alpha", "feat: implement worker alpha")
        assert mgr.get_diff_result("task-worker-alpha").has_changes is False

        mgr.rollback_to_clean("task-worker-gamma")
        assert mgr.get_diff_result("task-worker-gamma").has_changes is False

        # 7. Complete Cleanup
        cleaned = mgr.cleanup_all(delete_branches=True)
        assert cleaned == 3
        assert not path_a.exists()
        assert not path_b.exists()
        assert not path_c.exists()
