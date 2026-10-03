"""Provider-agnostic deployment adapter interface.

Every deployment provider (Vercel today, others later) implements
DeploymentAdapter. The Deployment Engine only talks to this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterator, Optional


class DeployStatus(str, Enum):
    QUEUED = "QUEUED"
    BUILDING = "BUILDING"
    READY = "READY"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class DeploymentNotFound(Exception):
    """Raised when a deployment_id is unknown to the adapter."""


class DeploymentError(Exception):
    """Raised for provider-side errors the engine should handle or retry."""


@dataclass
class DeployResult:
    deployment_id: str
    status: DeployStatus
    url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class LogEntry:
    """Matches the shared log schema: project_id, level, source, message, timestamp."""

    project_id: str
    level: str  # "info" | "warning" | "error"
    source: str  # e.g. "deploy", "build"
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DeploymentAdapter(ABC):
    """Contract every provider adapter must follow.

    Rules:
    - Never log env_vars values or tokens.
    - Every call is scoped by tenant_id; adapters must not mix tenants.
    """

    @abstractmethod
    def deploy(
        self,
        tenant_id: str,
        project_id: str,
        repo_url: str,
        branch: str,
        env_vars: dict[str, str],
    ) -> DeployResult:
        """Trigger a deployment. Returns immediately, usually with status QUEUED."""

    @abstractmethod
    def status(self, tenant_id: str, deployment_id: str) -> DeployResult:
        """Return the current state of a deployment (poll until READY or FAILED)."""

    @abstractmethod
    def logs(self, tenant_id: str, deployment_id: str) -> Iterator[LogEntry]:
        """Yield build/deploy log entries for a deployment."""

    @abstractmethod
    def rollback(
        self, tenant_id: str, project_id: str, to_deployment_id: str
    ) -> DeployResult:
        """Make an earlier deployment live again."""