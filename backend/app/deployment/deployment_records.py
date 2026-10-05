"""Deployment history: one record per deploy attempt, scoped by tenant.

DeploymentRecord is what the dashboard shows (history, status, URL, why it failed)
and what the Maintenance Engine reads. Every lookup requires tenant_id, so one
tenant can never read another tenant's deployments.

InMemoryDeploymentRepository is for tests and single-process use. A database
version needs a table with tenant_id + project_id columns and an index on
(tenant_id, project_id, created_at).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Optional, Protocol

from .adapters.base import DeployStatus
from .failure_classifier import Failure

_ID_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def check_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID_PART.match(value):
        raise ValueError(f"Invalid {label}")


@dataclass(frozen=True)
class DeploymentRecord:
    deployment_id: str
    tenant_id: str
    project_id: str
    version: str
    trigger: str  # "manual" | "push" | "redeploy" | "rollback"
    status: DeployStatus
    created_at: float
    updated_at: float
    provider_deployment_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    failure: Optional[Failure] = None


class DeploymentRepository(Protocol):
    def save(self, record: DeploymentRecord) -> None: ...
    def get(self, tenant_id: str, deployment_id: str) -> Optional[DeploymentRecord]: ...
    def list_for_project(self, tenant_id: str, project_id: str, limit: int = 20) -> list[DeploymentRecord]: ...


class InMemoryDeploymentRepository:
    def __init__(self) -> None:
        self._records: dict[str, DeploymentRecord] = {}
        self._lock = threading.Lock()

    def save(self, record: DeploymentRecord) -> None:
        with self._lock:
            self._records[record.deployment_id] = record

    def get(self, tenant_id: str, deployment_id: str) -> Optional[DeploymentRecord]:
        with self._lock:
            record = self._records.get(deployment_id)
        # Same answer for "missing" and "belongs to another tenant".
        if record is None or record.tenant_id != tenant_id:
            return None
        return record

    def list_for_project(self, tenant_id: str, project_id: str, limit: int = 20) -> list[DeploymentRecord]:
        with self._lock:
            # dicts keep insertion order, so the index breaks created_at ties:
            # the record created later is listed first.
            indexed = [
                (r.created_at, index, r)
                for index, r in enumerate(self._records.values())
                if r.tenant_id == tenant_id and r.project_id == project_id
            ]
        indexed.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in indexed][: max(0, limit)]