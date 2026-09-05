"""
Purpose:
Workspace Isolation — copies repository files to a temp directory for
safe modification. This is our MVP "sandbox" (not Docker-level isolation).

Naming: "workspace isolation" not "sandbox" per design decision.
"""

from __future__ import annotations
import os
import shutil
import tempfile
from dataclasses import dataclass


@dataclass
class IsolatedWorkspace:
    root: str           # Path to the isolated workspace root
    repo_name: str      # Original repo name (for logging)

    def resolve(self, relative_path: str) -> str:
        """Return absolute path within the workspace for a repo-relative path."""
        # Normalize separators
        clean = relative_path.replace("\\", "/").lstrip("/")
        return os.path.join(self.root, clean)

    def cleanup(self) -> None:
        """Remove the isolated workspace."""
        try:
            shutil.rmtree(self.root, ignore_errors=True)
        except Exception:
            pass


def create_workspace(repo_root: str, repo_name: str) -> IsolatedWorkspace:
    """
    Copy the downloaded repo snapshot to a new temp directory.
    This gives us an isolated working copy we can freely modify.
    """
    workspace_dir = tempfile.mkdtemp(prefix=f"teslalab_ws_{repo_name}_")
    
    # Copy entire repo into workspace
    dest = os.path.join(workspace_dir, "repo")
    shutil.copytree(repo_root, dest)

    print(f"[Workspace] Isolated workspace created at {workspace_dir}")
    return IsolatedWorkspace(root=dest, repo_name=repo_name)
