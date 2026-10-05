"""Poll a provider until a deployment reaches a final state.

QUEUED -> BUILDING -> READY | FAILED   (ROLLED_BACK is also final)

- Waits longer between polls (backoff) up to max_interval.
- Gives up with PollTimeout after `timeout` seconds.
- Retries transient provider errors (DeploymentError) a few times in a row.
- DeploymentNotFound is never retried (the deployment does not exist for this tenant).
- on_update is called whenever the status changes, so events reach the Maintenance Engine.

sleep and clock are injectable so tests run instantly.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from .adapters.base import (
    DeploymentAdapter,
    DeploymentError,
    DeploymentNotFound,
    DeployResult,
    DeployStatus,
)

TERMINAL_STATUSES = frozenset({DeployStatus.READY, DeployStatus.FAILED, DeployStatus.ROLLED_BACK})


class PollTimeout(Exception):
    def __init__(self, waited_seconds: float) -> None:
        self.waited_seconds = waited_seconds
        super().__init__(f"Deployment did not finish within {int(waited_seconds)} seconds")


def poll_deployment(
    adapter: DeploymentAdapter,
    tenant_id: str,
    deployment_id: str,
    *,
    interval: float = 2.0,
    max_interval: float = 15.0,
    backoff: float = 1.5,
    timeout: float = 900.0,
    max_consecutive_errors: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_update: Optional[Callable[[DeployResult], None]] = None,
) -> DeployResult:
    started = clock()
    delay = interval
    errors = 0
    last_status: Optional[DeployStatus] = None

    while True:
        try:
            result = adapter.status(tenant_id, deployment_id)
            errors = 0
        except DeploymentNotFound:
            raise
        except DeploymentError:
            errors += 1
            if errors > max_consecutive_errors:
                raise
            result = None

        if result is not None:
            if result.status != last_status:
                last_status = result.status
                if on_update is not None:
                    on_update(result)
            if result.status in TERMINAL_STATUSES:
                return result

        waited = clock() - started
        if waited >= timeout:
            raise PollTimeout(waited)
        sleep(delay)
        delay = min(delay * backoff, max_interval)