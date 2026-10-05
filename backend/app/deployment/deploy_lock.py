"""Per-project deploy lock: only one deployment per project at a time.

- Scoped by (tenant_id, project_id).
- Locks expire after ttl_seconds, so a crashed worker cannot block a project forever.
- Only the owner can release a lock (a stale worker cannot free someone else's lock).

In-memory, so it works inside ONE process. If deploys run in several workers
(Day 5 queue), replace it with a Redis lock or a database row lock using the
same interface.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator

from .deployment_records import check_id

DEFAULT_TTL_SECONDS = 20 * 60


class DeployInProgress(Exception):
    """Another deployment of this project is already running."""


class DeployLock:
    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._locks: dict[tuple[str, str], tuple[str, float]] = {}  # key -> (owner, expires_at)
        self._guard = threading.Lock()

    @staticmethod
    def _key(tenant_id: str, project_id: str) -> tuple[str, str]:
        check_id(tenant_id, "tenant_id")
        check_id(project_id, "project_id")
        return tenant_id, project_id

    def acquire(self, tenant_id: str, project_id: str, owner: str) -> bool:
        """True if the lock is now held by owner (also refreshes the owner's own lock)."""
        key = self._key(tenant_id, project_id)
        check_id(owner, "owner")
        now = self._clock()
        with self._guard:
            current = self._locks.get(key)
            if current is not None:
                current_owner, expires_at = current
                if now < expires_at and current_owner != owner:
                    return False
            self._locks[key] = (owner, now + self._ttl)
            return True

    def release(self, tenant_id: str, project_id: str, owner: str) -> bool:
        """Release only if owner holds it. Returns whether a lock was released."""
        key = self._key(tenant_id, project_id)
        with self._guard:
            current = self._locks.get(key)
            if current is None or current[0] != owner:
                return False
            del self._locks[key]
            return True

    def is_locked(self, tenant_id: str, project_id: str) -> bool:
        key = self._key(tenant_id, project_id)
        with self._guard:
            current = self._locks.get(key)
            return current is not None and self._clock() < current[1]

    @contextmanager
    def hold(self, tenant_id: str, project_id: str, owner: str) -> Iterator[None]:
        if not self.acquire(tenant_id, project_id, owner):
            raise DeployInProgress(f"A deployment of project {project_id} is already running")
        try:
            yield
        finally:
            self.release(tenant_id, project_id, owner)