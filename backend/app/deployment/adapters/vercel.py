"""Vercel adapter (stub). Real implementation is planned for Day 3.

Vercel REST API notes (verify against current docs before implementing):
- Create deployment:   POST https://api.vercel.com/v13/deployments
- Get deployment:      GET  https://api.vercel.com/v13/deployments/{id}
- Build events/logs:   GET  https://api.vercel.com/v3/deployments/{id}/events
- Set env vars:        POST https://api.vercel.com/v10/projects/{id}/env
- Rollback/promote:    promote an earlier deployment via the project promote endpoint
Auth: Bearer token. Load it from the Secret Store; never log it.

Vercel states map to ours:
  QUEUED/INITIALIZING -> QUEUED, BUILDING -> BUILDING, READY -> READY,
  ERROR/CANCELED -> FAILED
"""

from __future__ import annotations

from typing import Iterator

from .base import DeploymentAdapter, DeployResult, LogEntry


class VercelAdapter(DeploymentAdapter):
    def __init__(self, token: str, team_id: str | None = None) -> None:
        self._token = token  # never log this
        self._team_id = team_id

    def __repr__(self) -> str:  # keep the token out of reprs and logs
        return "VercelAdapter(token=***)"

    def deploy(self, tenant_id, project_id, repo_url, branch, env_vars) -> DeployResult:
        raise NotImplementedError("VercelAdapter.deploy: planned for Day 3")

    def status(self, tenant_id, deployment_id) -> DeployResult:
        raise NotImplementedError("VercelAdapter.status: planned for Day 3")

    def logs(self, tenant_id, deployment_id) -> Iterator[LogEntry]:
        raise NotImplementedError("VercelAdapter.logs: planned for Day 3")

    def rollback(self, tenant_id, project_id, to_deployment_id) -> DeployResult:
        raise NotImplementedError("VercelAdapter.rollback: planned for Day 3")