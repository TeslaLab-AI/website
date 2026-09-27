"""
GitWorkspaceManager for Engineer 2 (Agent 2) — Task 25.

Provides strictly isolated Git workspaces using Git worktrees:
- One isolated workspace and task branch per task run (branch pattern: task/<name>)
- Hard protection against performing changes or operations on main/master
- Support for checkout, apply_changes, get_diff, commit, rollback_to_clean, cleanup
- True multi-workspace concurrency with zero cross-contamination
- Structured result models: WorkspaceSession, DiffResult, CommitResult
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("git_workspace_manager")

PROTECTED_BRANCHES = {"main", "master", "origin/main", "origin/master"}


class ProtectedBranchError(ValueError):
    """Raised when an operation attempts to target or modify protected branches (main/master)."""
    pass


class WorkspaceError(RuntimeError):
    """Base exception for workspace operations."""
    pass


class WorkspaceNotFoundError(WorkspaceError):
    """Raised when an operation references a workspace that does not exist."""
    pass


class WorkspaceState(str, Enum):
    INITIALIZED = "INITIALIZED"
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    ROLLED_BACK = "ROLLED_BACK"
    CLEANED_UP = "CLEANED_UP"


class CommitResult(BaseModel):
    """Structured information about a successful workspace commit."""
    model_config = ConfigDict(extra="ignore")

    commit_hash: str = Field(..., description="Git commit hash (SHA-1)")
    branch: str = Field(..., description="Task branch name committed to")
    message: str = Field(..., description="Commit message")
    files_changed: List[str] = Field(default_factory=list, description="List of files touched in commit")


class DiffResult(BaseModel):
    """Structured unified diff information for a workspace."""
    model_config = ConfigDict(extra="ignore")

    diff: str = Field(default="", description="Unified git diff output")
    has_changes: bool = Field(default=False, description="Whether differences exist")
    files_changed: List[str] = Field(default_factory=list, description="List of files with modifications")


class WorkspaceSession(BaseModel):
    """Tracks state and metadata for an active or managed task workspace."""
    model_config = ConfigDict(extra="ignore")

    task_name: str = Field(..., description="Identifier of the task run")
    branch_name: str = Field(..., description="Isolated task branch name (e.g. task/<name>)")
    worktree_path: str = Field(..., description="Absolute filesystem path to the worktree directory")
    base_ref: str = Field(..., description="Base Git commit or branch branched from")
    state: WorkspaceState = Field(default=WorkspaceState.INITIALIZED, description="Current workspace state")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata tags")


class GitWorkspaceManager:
    """
    Manages isolated Git worktrees and task branches.
    Guarantees that task modifications never occur directly on main or master branches.
    """

    def __init__(
        self,
        repo_path: Optional[str | Path] = None,
        worktrees_dir: Optional[str | Path] = None,
    ) -> None:
        if repo_path:
            self.repo_path = Path(repo_path).resolve()
        else:
            self.repo_path = self._detect_repo_root()

        if worktrees_dir:
            self.worktrees_dir = Path(worktrees_dir).resolve()
        else:
            self.worktrees_dir = (self.repo_path / ".worktrees").resolve()

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, WorkspaceSession] = {}

    def _detect_repo_root(self) -> Path:
        """Detect the git root directory using git rev-parse."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            )
            return Path(res.stdout.strip()).resolve()
        except Exception:
            return Path.cwd().resolve()

    def _run_git(
        self,
        args: List[str],
        cwd: Optional[Path] = None,
        check: bool = True,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a git command safely."""
        working_dir = cwd or self.repo_path
        try:
            return subprocess.run(
                ["git"] + args,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                check=check,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as e:
            cmd_str = "git " + " ".join(args)
            logger.error("Git command failed: %s\nStderr: %s", cmd_str, e.stderr)
            raise WorkspaceError(f"Command '{cmd_str}' failed with exit code {e.returncode}: {e.stderr.strip()}")

    def _normalize_branch_and_task(self, task_name: str) -> tuple[str, str]:
        """
        Validates and formats task_name and branch_name.
        Guarantees task/<name> format and rejects main/master.
        """
        clean_task = task_name.strip()
        if not clean_task:
            raise ValueError("task_name cannot be empty.")

        lower_task = clean_task.lower()
        if lower_task in PROTECTED_BRANCHES or lower_task.replace("task/", "") in PROTECTED_BRANCHES:
            raise ProtectedBranchError(
                f"Direct operations targeting protected branch '{task_name}' are forbidden. Task changes must be on task/* branches."
            )

        if clean_task.startswith("task/"):
            branch_name = clean_task
            slug = clean_task[5:]
        else:
            slug = clean_task
            branch_name = f"task/{clean_task}"

        sanitized_slug = re.sub(r"[^\w\-.]", "_", slug)
        return sanitized_slug, branch_name

    def checkout(
        self,
        task_name: str,
        base_ref: str = "HEAD",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkspaceSession:
        """
        Create and check out an isolated worktree on an isolated task branch.
        Never runs task changes directly on main or master.
        """
        sanitized_slug, branch_name = self._normalize_branch_and_task(task_name)
        worktree_path = (self.worktrees_dir / f"wt_{sanitized_slug}").resolve()

        # If already tracked and active, return existing
        if sanitized_slug in self._sessions:
            session = self._sessions[sanitized_slug]
            if session.state == WorkspaceState.ACTIVE and worktree_path.exists():
                return session

        # If worktree dir already exists on disk (e.g. from previous run), clean it up first
        if worktree_path.exists():
            self._cleanup_worktree_path(worktree_path, branch_name)

        # Check if branch exists
        branch_check = self._run_git(["branch", "--list", branch_name], check=False)
        branch_exists = bool(branch_check.stdout.strip())

        if branch_exists:
            self._run_git(["branch", "-D", branch_name], check=False)

        # Create new branch from base_ref into the dedicated worktree
        self._run_git(["worktree", "add", "-b", branch_name, str(worktree_path), base_ref])

        session = WorkspaceSession(
            task_name=sanitized_slug,
            branch_name=branch_name,
            worktree_path=str(worktree_path),
            base_ref=base_ref,
            state=WorkspaceState.ACTIVE,
            metadata=metadata or {},
        )
        self._sessions[sanitized_slug] = session
        logger.info("Created isolated workspace for task '%s' at %s (branch: %s)", sanitized_slug, worktree_path, branch_name)
        return session

    def get_session(self, task_name: str) -> WorkspaceSession:
        """Retrieve the WorkspaceSession for a task."""
        sanitized_slug, _ = self._normalize_branch_and_task(task_name)
        if sanitized_slug not in self._sessions:
            raise WorkspaceNotFoundError(f"No active workspace session found for task '{task_name}'.")
        return self._sessions[sanitized_slug]

    def has_session(self, task_name: str) -> bool:
        """Check whether a session exists for a task."""
        sanitized_slug, _ = self._normalize_branch_and_task(task_name)
        return sanitized_slug in self._sessions

    def apply_changes(
        self,
        task_name: str,
        relative_path: str,
        content: str | bytes,
    ) -> str:
        """
        Write or update a file strictly within the isolated workspace.
        Prevents directory traversal outside the worktree.
        """
        session = self.get_session(task_name)
        wt_path = Path(session.worktree_path)

        norm_rel = os.path.normpath(relative_path.strip().lstrip("/\\"))
        target_file = (wt_path / norm_rel).resolve()

        if not str(target_file).startswith(str(wt_path)):
            raise WorkspaceError(f"Path traversal detected: '{relative_path}' resolves outside workspace root.")

        target_file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target_file.write_bytes(content)
        else:
            target_file.write_text(content, encoding="utf-8")

        return str(target_file)

    def get_diff(self, task_name: str, staged: bool = False) -> str:
        """
        Generate a clean unified git diff inside the isolated workspace.
        Uses git add -N to ensure newly added untracked files are captured in the unified diff.
        """
        session = self.get_session(task_name)
        wt_path = Path(session.worktree_path)

        # Mark untracked files with intent-to-add so they appear in diff
        self._run_git(["add", "-N", "."], cwd=wt_path, check=False)

        args = ["diff"]
        if staged:
            args.append("--cached")
        else:
            # Compare working tree against HEAD
            args.append("HEAD")

        res = self._run_git(args, cwd=wt_path, check=False)
        return res.stdout

    def get_diff_result(self, task_name: str, staged: bool = False) -> DiffResult:
        """Return structured DiffResult including list of changed files."""
        diff_text = self.get_diff(task_name, staged=staged)
        changed_files: List[str] = []

        session = self.get_session(task_name)
        wt_path = Path(session.worktree_path)
        status_res = self._run_git(["status", "--porcelain", "-uall"], cwd=wt_path, check=False)
        for line in status_res.stdout.splitlines():
            if len(line) >= 4:
                file_rel = line[3:].strip()
                if file_rel and file_rel not in changed_files:
                    # Normalize slashes
                    changed_files.append(file_rel.replace("\\", "/"))

        return DiffResult(
            diff=diff_text,
            has_changes=bool(diff_text.strip() or changed_files),
            files_changed=changed_files,
        )

    def commit(self, task_name: str, message: str) -> CommitResult:
        """
        Stage and commit changes inside the isolated task workspace.
        Never commits to main or master.
        """
        session = self.get_session(task_name)
        wt_path = Path(session.worktree_path)

        if not message.strip():
            raise ValueError("Commit message cannot be empty.")

        self._run_git(["add", "-A"], cwd=wt_path)

        status_res = self._run_git(["diff", "--cached", "--name-only"], cwd=wt_path)
        files_changed = [f.strip().replace("\\", "/") for f in status_res.stdout.splitlines() if f.strip()]

        if not files_changed:
            raise WorkspaceError("No changes to commit inside workspace.")

        self._run_git(["commit", "-m", message.strip()], cwd=wt_path)

        hash_res = self._run_git(["rev-parse", "HEAD"], cwd=wt_path)
        commit_hash = hash_res.stdout.strip()

        session.state = WorkspaceState.COMMITTED
        return CommitResult(
            commit_hash=commit_hash,
            branch=session.branch_name,
            message=message.strip(),
            files_changed=files_changed,
        )

    def rollback_to_clean(self, task_name: str) -> bool:
        """
        Discard all unstaged and uncommitted changes inside the workspace,
        restoring it to a pristine clean state.
        """
        session = self.get_session(task_name)
        wt_path = Path(session.worktree_path)

        self._run_git(["reset", "--hard", "HEAD"], cwd=wt_path, check=False)
        self._run_git(["clean", "-fd"], cwd=wt_path, check=False)

        status_res = self._run_git(["status", "--porcelain", "-uall"], cwd=wt_path, check=False)
        is_clean = len(status_res.stdout.strip()) == 0

        if is_clean:
            session.state = WorkspaceState.ROLLED_BACK
        return is_clean

    def _cleanup_worktree_path(self, worktree_path: Path, branch_name: str) -> None:
        """Helper to force-remove a worktree path and prune."""
        try:
            self._run_git(["worktree", "remove", "--force", str(worktree_path)], check=False)
        except Exception:
            pass
        try:
            self._run_git(["worktree", "prune"], check=False)
        except Exception:
            pass

        if worktree_path.exists():
            for attempt in range(3):
                try:
                    shutil.rmtree(worktree_path, ignore_errors=False)
                    break
                except Exception:
                    time.sleep(0.2)
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

    def cleanup(self, task_name: str, delete_branch: bool = True) -> bool:
        """
        Safely remove worktree, prune git references, and optionally delete task branch.
        """
        sanitized_slug, branch_name = self._normalize_branch_and_task(task_name)
        session = self._sessions.get(sanitized_slug)
        worktree_path = Path(session.worktree_path) if session else (self.worktrees_dir / f"wt_{sanitized_slug}").resolve()

        self._cleanup_worktree_path(worktree_path, branch_name)

        if delete_branch:
            self._run_git(["branch", "-D", branch_name], check=False)

        if session:
            session.state = WorkspaceState.CLEANED_UP
            self._sessions.pop(sanitized_slug, None)

        return not worktree_path.exists()

    def cleanup_all(self, delete_branches: bool = True) -> int:
        """Clean up all managed workspace sessions."""
        cleaned = 0
        tasks = list(self._sessions.keys())
        for task in tasks:
            try:
                if self.cleanup(task, delete_branch=delete_branches):
                    cleaned += 1
            except Exception as e:
                logger.warning("Error cleaning up task %s: %s", task, e)
        return cleaned

    def list_workspaces(self) -> List[WorkspaceSession]:
        """Return all active or tracked workspace sessions."""
        return list(self._sessions.values())


default_workspace_manager = GitWorkspaceManager()
