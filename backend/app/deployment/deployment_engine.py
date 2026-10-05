"""Deployment engine: runs one deployment from start to finish.

    validation gate  ->  deploy lock  ->  secrets pre-flight  ->  provider deploy
        ->  status polling  ->  (on failure) read logs + classify  ->  record

Guarantees:
- A broken build never reaches the provider (gate fails closed).
- Missing environment variables are caught BEFORE a build is wasted on them.
- Only one deployment per project runs at a time; the lock is always released.
- Every attempt leaves a record (history) with the reason it failed.
- Secrets never appear in records, errors or events (masked).
- Everything is scoped by tenant_id.

on_event(record) is called on every status change (QUEUED, BUILDING, READY, FAILED)
so the Maintenance Engine can react.
"""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import replace
from typing import Callable, Iterable, Optional

from .adapters.base import (
    DeploymentAdapter,
    DeploymentError,
    DeploymentNotFound,
    DeployStatus,
)
from .deploy_lock import DeployInProgress, DeployLock
from .deployment_poller import TERMINAL_STATUSES, PollTimeout, poll_deployment
from .deployment_records import DeploymentRecord, DeploymentRepository, check_id
from .failure_classifier import missing_env_failure, primary_failure, timeout_failure
from .log_masking import mask_secrets
from .secret_service import MissingSecretsError, SecretService, deploy_with_secrets
from .validation_gate import CheckResult, evaluate_gate

MAX_LOG_LINES = 5000

__all__ = ["DeploymentEngine", "DeployInProgress"]


class DeploymentEngine:
    def __init__(
        self,
        adapter: DeploymentAdapter,
        secret_service: SecretService,
        records: DeploymentRepository,
        lock: DeployLock,
        *,
        poll_interval: float = 3.0,
        poll_timeout: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        poll_clock: Callable[[], float] = time.monotonic,
        on_event: Optional[Callable[[DeploymentRecord], None]] = None,
    ) -> None:
        self._adapter = adapter
        self._secrets = secret_service
        self._records = records
        self._lock = lock
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._sleep = sleep
        self._clock = clock
        self._poll_clock = poll_clock
        self._on_event = on_event

    # -- public ----------------------------------------------------------
    def deploy(
        self,
        tenant_id: str,
        project_id: str,
        version: str,
        repo_url: str,
        branch: str,
        checks: Iterable[CheckResult],
        required_env: Iterable[str] = (),
        trigger: str = "manual",
    ) -> DeploymentRecord:
        """Run one deployment. Raises DeployInProgress if the project is already deploying."""
        check_id(tenant_id, "tenant_id")
        check_id(project_id, "project_id")
        check_id(version, "version")
        now = self._clock()
        record = DeploymentRecord(
            deployment_id=uuid.uuid4().hex[:16],
            tenant_id=tenant_id,
            project_id=project_id,
            version=version,
            trigger=trigger,
            status=DeployStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )

        decision = evaluate_gate(checks)
        if not decision.allowed:
            return self._save(replace(
                record, status=DeployStatus.FAILED,
                error=f"Blocked by validation gate: {decision.summary}",
            ))

        owner = record.deployment_id
        if not self._lock.acquire(tenant_id, project_id, owner):
            raise DeployInProgress(f"A deployment of project {project_id} is already running")
        try:
            return self._run(record, repo_url, branch, tuple(required_env))
        finally:
            self._lock.release(tenant_id, project_id, owner)

    def history(self, tenant_id: str, project_id: str, limit: int = 20) -> list[DeploymentRecord]:
        return self._records.list_for_project(tenant_id, project_id, limit)

    def get(self, tenant_id: str, deployment_id: str) -> Optional[DeploymentRecord]:
        return self._records.get(tenant_id, deployment_id)

    # -- internals -------------------------------------------------------
    def _save(self, record: DeploymentRecord) -> DeploymentRecord:
        previous = self._records.get(record.tenant_id, record.deployment_id)
        record = replace(record, updated_at=self._clock())
        self._records.save(record)
        if self._on_event is not None and (previous is None or previous.status != record.status):
            self._on_event(record)
        return record

    def _fail(self, record: DeploymentRecord, error: str, failure=None) -> DeploymentRecord:
        return self._save(replace(
            record, status=DeployStatus.FAILED, error=mask_secrets(error)[:1000], failure=failure,
        ))

    def _collect_logs(self, tenant_id: str, provider_id: str) -> str:
        try:
            lines = itertools.islice(self._adapter.logs(tenant_id, provider_id), MAX_LOG_LINES)
            return "\n".join(entry.message for entry in lines)
        except Exception:
            return ""

    def _run(self, record: DeploymentRecord, repo_url: str, branch: str, required_env: tuple[str, ...]) -> DeploymentRecord:
        record = self._save(record)  # QUEUED event
        try:
            return self._run_steps(record, repo_url, branch, required_env)
        except Exception:
            # Never leave a record stuck in QUEUED/BUILDING if something unexpected breaks.
            latest = self._records.get(record.tenant_id, record.deployment_id) or record
            if latest.status not in TERMINAL_STATUSES:
                self._fail(latest, "Unexpected internal error during deployment")
            raise

    def _run_steps(self, record, repo_url, branch, required_env) -> DeploymentRecord:
        tenant_id, project_id = record.tenant_id, record.project_id

        try:
            started = deploy_with_secrets(
                self._adapter, self._secrets, tenant_id, project_id, repo_url, branch,
                required=required_env,
            )
        except MissingSecretsError as exc:
            failure = missing_env_failure(exc.names)
            return self._fail(record, failure.summary, failure)
        except DeploymentError as exc:
            return self._fail(record, f"Provider error: {exc}")

        record = self._save(replace(
            record, provider_deployment_id=started.deployment_id,
            status=started.status, url=started.url,
        ))
        current = {"record": record}

        def on_update(result) -> None:
            if result.status not in TERMINAL_STATUSES:
                current["record"] = self._save(replace(
                    current["record"], status=result.status, url=result.url or current["record"].url,
                ))

        try:
            final = poll_deployment(
                self._adapter, tenant_id, started.deployment_id,
                interval=self._poll_interval, timeout=self._poll_timeout,
                sleep=self._sleep, clock=self._poll_clock, on_update=on_update,
            )
        except PollTimeout as exc:
            failure = timeout_failure(exc.waited_seconds)
            return self._fail(current["record"], failure.summary, failure)
        except (DeploymentNotFound, DeploymentError) as exc:
            return self._fail(current["record"], f"Provider error: {exc}")

        record = current["record"]
        if final.status == DeployStatus.FAILED:
            logs = self._collect_logs(tenant_id, started.deployment_id)
            failure = primary_failure(f"{logs}\n{final.error or ''}")
            return self._fail(record, final.error or failure.summary, failure)

        return self._save(replace(record, status=final.status, url=final.url or record.url))