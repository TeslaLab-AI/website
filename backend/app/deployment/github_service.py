"""GitHub integration: create private repos and push project code.

Day 1 uses a fine-grained Personal Access Token (Administration + Contents
read/write). A GitHub App is the better long-term option.

Security rules enforced here:
- The token is never logged, never put in a URL, and never in an exception.
- git gets the token through environment variables (not command-line args).
- A push is refused if .env files or private keys are tracked.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

from .log_masking import mask_secrets

GITHUB_API = "https://api.github.com"
RETRY_STATUS = {429, 500, 502, 503, 504}
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_GITIGNORE_DEFAULT = ".env\n.env.*\n!.env.example\nnode_modules/\n.next/\n__pycache__/\n"


class GitHubError(Exception):
    pass


class GitHubAuthError(GitHubError):
    pass


class RepoAlreadyExists(GitHubError):
    pass


class PushError(GitHubError):
    pass


@dataclass(frozen=True)
class RepoInfo:
    name: str
    full_name: str
    clone_url: str
    html_url: str


def repo_name_for_project(project_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", project_id).strip("-.")[:80]
    if not safe:
        raise ValueError("project_id produces an empty repository name")
    return f"tl-{safe}"


def _is_forbidden_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    return name.endswith((".pem", ".key")) or name in {"id_rsa", "id_ed25519"}


class GitHubService:
    def __init__(
        self,
        token: str,
        org: Optional[str] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 3,
    ) -> None:
        if not token:
            raise ValueError("A GitHub token is required")
        self._token = token
        self._org = org
        self._sleep = sleep
        self._max_retries = max_retries
        self._client = httpx.Client(
            base_url=GITHUB_API,
            transport=transport,
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def __repr__(self) -> str:  # keep the token out of reprs and logs
        return f"GitHubService(org={self._org!r}, token=***)"

    # -- repo creation ---------------------------------------------------
    def create_private_repo(self, name: str, description: str = "") -> RepoInfo:
        path = f"/orgs/{self._org}/repos" if self._org else "/user/repos"
        payload = {
            "name": name,
            "private": True,
            "auto_init": False,
            "description": description,
        }
        response = self._post_with_retry(path, payload)

        if response.status_code == 201:
            data = response.json()
            return RepoInfo(
                name=data["name"],
                full_name=data["full_name"],
                clone_url=data["clone_url"],
                html_url=data["html_url"],
            )
        if response.status_code in (401, 403):
            raise GitHubAuthError(
                f"GitHub rejected the token or its permissions (HTTP {response.status_code})"
            )
        body = response.text[:300]
        if response.status_code == 422 and "already exists" in body.lower():
            raise RepoAlreadyExists(name)
        raise GitHubError(
            f"Repository creation failed (HTTP {response.status_code}): {mask_secrets(body)}"
        )

    def create_private_repo_unique(self, project_id: str, attempts: int = 5) -> RepoInfo:
        """Create tl-{project_id}; on a name collision try -2, -3, ..."""
        base = repo_name_for_project(project_id)
        for i in range(1, attempts + 1):
            name = base if i == 1 else f"{base}-{i}"
            try:
                return self.create_private_repo(name)
            except RepoAlreadyExists:
                continue
        raise GitHubError(f"Could not find a free repository name for {base}")

    def _post_with_retry(self, path: str, payload: dict) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            last = attempt == self._max_retries
            try:
                response = self._client.post(path, json=payload)
            except httpx.TransportError:
                if last:
                    raise GitHubError("Could not reach GitHub (network error)") from None
                self._sleep(2**attempt)
                continue
            if response.status_code in RETRY_STATUS and not last:
                self._sleep(2**attempt)
                continue
            return response
        raise GitHubError("Unreachable")  # pragma: no cover

    # -- pushing code ----------------------------------------------------
    def push_directory(
        self,
        local_dir: str,
        remote_url: str,
        branch: str = "main",
        message: str = "chore: initial commit",
    ) -> str:
        """Commit everything in local_dir and push it. Returns the commit SHA."""
        if re.search(r"://[^/]*@", remote_url):
            raise ValueError("Do not embed credentials in the remote URL")
        if not _BRANCH_RE.match(branch) or ".." in branch:
            raise ValueError("Invalid branch name")
        directory = Path(local_dir)
        if not directory.is_dir():
            raise PushError(f"Directory not found: {local_dir}")

        self._ensure_gitignore(directory)
        if not (directory / ".git").exists():
            self._git(["init"], directory)
        self._git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], directory)
        self._git(["add", "-A"], directory)

        tracked = self._git(["ls-files"], directory).stdout.splitlines()
        forbidden = [p for p in tracked if _is_forbidden_path(p)]
        if forbidden:
            raise PushError(f"Refusing to push secret-like files: {', '.join(forbidden)}")

        has_changes = self._git(["diff", "--cached", "--quiet"], directory, check=False).returncode == 1
        has_head = self._git(["rev-parse", "--verify", "HEAD"], directory, check=False).returncode == 0
        if has_changes:
            self._git(
                ["-c", "user.name=TeslaLab", "-c", "user.email=bot@teslalab.dev",
                 "commit", "-m", message],
                directory,
            )
        elif not has_head:
            raise PushError("Nothing to commit: the directory has no files")

        self._git(["push", remote_url, f"HEAD:refs/heads/{branch}"], directory, auth=True)
        return self._git(["rev-parse", "HEAD"], directory).stdout.strip()

    @staticmethod
    def _ensure_gitignore(directory: Path) -> None:
        gitignore = directory / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(_GITIGNORE_DEFAULT)
            return
        lines = gitignore.read_text().splitlines()
        if ".env" not in lines:
            with gitignore.open("a") as f:
                f.write("\n.env\n.env.*\n!.env.example\n")

    def _scrub(self, text: str) -> str:
        basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
        return mask_secrets(text.replace(self._token, "***").replace(basic, "***"))

    def _git(
        self,
        args: list[str],
        cwd: Path,
        *,
        auth: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        if auth:
            # Token travels via environment variables, never via argv or the URL.
            basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
            env.update(
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="http.extraHeader",
                GIT_CONFIG_VALUE_0=f"Authorization: Basic {basic}",
            )
        try:
            proc = subprocess.run(
                ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300
            )
        except subprocess.TimeoutExpired:
            raise PushError(f"git {args[0]} timed out") from None
        if check and proc.returncode != 0:
            raise PushError(f"git {args[0]} failed: {self._scrub(proc.stderr.strip())}")
        return proc