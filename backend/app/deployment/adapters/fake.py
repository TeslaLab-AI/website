"""In-memory FakeAdapter so other engines and tests can integrate immediately.

Behaviour:
- deploy() returns QUEUED.
- Each status() call advances: QUEUED -> BUILDING -> READY.
- Pass fail_with="reason" to make deployments end in FAILED instead.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .base import (
    DeploymentAdapter,
    DeploymentNotFound,
    DeployResult,
    DeployStatus,
    LogEntry,
)


@dataclass
class _Record:
    tenant_id: str
    project_id: str
    status: DeployStatus = DeployStatus.QUEUED
    polls: int = 0
    url: Optional[str] = None
    error: Optional[str] = None
    logs: list[LogEntry] = field(default_factory=list)


class FakeAdapter(DeploymentAdapter):
    def __init__(self, fail_with: Optional[str] = None) -> None:
        self._fail_with = fail_with
        self._records: dict[str, _Record] = {}
        self._counter = itertools.count(1)

    # -- helpers ---------------------------------------------------------
    def _get(self, tenant_id: str, deployment_id: str) -> _Record:
        rec = self._records.get(deployment_id)
        # Same error for "missing" and "other tenant" so IDs can't be probed.
        if rec is None or rec.tenant_id != tenant_id:
            raise DeploymentNotFound(deployment_id)
        return rec

    def _result(self, deployment_id: str, rec: _Record) -> DeployResult:
        return DeployResult(deployment_id, rec.status, rec.url, rec.error)

    def _log(self, rec: _Record, level: str, message: str) -> None:
        rec.logs.append(LogEntry(rec.project_id, level, "deploy", message))

    # -- interface -------------------------------------------------------
    def deploy(self, tenant_id, project_id, repo_url, branch, env_vars) -> DeployResult:
        deployment_id = f"fake-dpl-{next(self._counter)}"
        rec = _Record(tenant_id=tenant_id, project_id=project_id)
        self._log(rec, "info", f"Queued deployment of {repo_url}@{branch}")
        # Log only the NAMES of env vars, never values.
        self._log(rec, "info", f"Env vars provided: {sorted(env_vars)}")
        self._records[deployment_id] = rec
        return self._result(deployment_id, rec)

    def status(self, tenant_id, deployment_id) -> DeployResult:
        rec = self._get(tenant_id, deployment_id)
        if rec.status == DeployStatus.QUEUED:
            rec.status = DeployStatus.BUILDING
            self._log(rec, "info", "Build started")
        elif rec.status == DeployStatus.BUILDING:
            if self._fail_with:
                rec.status = DeployStatus.FAILED
                rec.error = self._fail_with
                self._log(rec, "error", self._fail_with)
            else:
                rec.status = DeployStatus.READY
                rec.url = f"https://{rec.project_id}.fake.teslalab.dev"
                self._log(rec, "info", f"Deployment ready at {rec.url}")
        rec.polls += 1
        return self._result(deployment_id, rec)

    def logs(self, tenant_id, deployment_id) -> Iterator[LogEntry]:
        rec = self._get(tenant_id, deployment_id)
        yield from list(rec.logs)

    def rollback(self, tenant_id, project_id, to_deployment_id) -> DeployResult:
        target = self._get(tenant_id, to_deployment_id)
        if target.project_id != project_id:
            raise DeploymentNotFound(to_deployment_id)
        deployment_id = f"fake-dpl-{next(self._counter)}"
        rec = _Record(
            tenant_id=tenant_id,
            project_id=project_id,
            status=DeployStatus.ROLLED_BACK,
            url=target.url,
        )
        self._log(rec, "info", f"Rolled back to {to_deployment_id}")
        self._records[deployment_id] = rec
        return self._result(deployment_id, rec)