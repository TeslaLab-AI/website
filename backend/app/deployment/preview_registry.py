"""Preview routes: which preview subdomain points at which sandbox, and for how long.

Flow:
  Build Engine starts a sandbox dev server  ->  PreviewService.register_preview(...)
  -> returns https://preview-<16 hex>.<base_domain>  (valid for 30 minutes)
  The router (preview_router.py) looks routes up by subdomain and forwards traffic.
  A reaper (service.reap(), called on a schedule) stops expired sandboxes.

Security rules:
- The upstream address is validated against an allowlist, so a preview can never
  be pointed at an internal service (SSRF), e.g. cloud metadata or the database.
- Preview IDs are random (64 bits). Previews are public by URL, so they must not
  be guessable or sequential.
- Everything is scoped by tenant_id. Another tenant cannot see, stop or probe a
  preview; they get the same answer as for a preview that does not exist.
- Per-tenant limit on active previews.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional, Protocol
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

PREVIEW_PREFIX = "preview-"
ID_BYTES = 8  # 8 bytes -> 16 hex characters
DEFAULT_TTL_SECONDS = 30 * 60
DEFAULT_GRACE_SECONDS = 60 * 60  # keep answering "410 Gone" this long after expiry
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost")
DEFAULT_MAX_PER_TENANT = 10
MIN_UPSTREAM_PORT = 1024

_ID_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class PreviewError(Exception):
    pass


class UpstreamNotAllowed(PreviewError, ValueError):
    pass


class PreviewQuotaExceeded(PreviewError):
    pass


@dataclass(frozen=True)
class PreviewRoute:
    preview_id: str
    tenant_id: str
    project_id: str
    upstream: str  # normalized, e.g. "http://127.0.0.1:3000"
    created_at: float
    expires_at: float
    reaped: bool = False  # True once the sandbox has been stopped


@dataclass(frozen=True)
class PreviewInfo:
    preview_id: str
    url: str
    expires_at: float


class PreviewRegistry(Protocol):
    def add(self, route: PreviewRoute) -> None: ...
    def get(self, preview_id: str) -> Optional[PreviewRoute]: ...
    def find_by_project(self, tenant_id: str, project_id: str) -> Optional[PreviewRoute]: ...
    def count_active(self, tenant_id: str, now: float) -> int: ...
    def remove(self, preview_id: str) -> Optional[PreviewRoute]: ...
    def reap(self, now: float, grace_seconds: float) -> list[PreviewRoute]: ...


class InMemoryPreviewRegistry:
    """Thread-safe, single-process registry. Swap for a database-backed one
    (with a tenant_id column) if the router runs as a separate process."""

    def __init__(self) -> None:
        self._routes: dict[str, PreviewRoute] = {}
        self._lock = threading.Lock()

    def add(self, route: PreviewRoute) -> None:
        with self._lock:
            self._routes[route.preview_id] = route

    def get(self, preview_id: str) -> Optional[PreviewRoute]:
        with self._lock:
            return self._routes.get(preview_id)

    def find_by_project(self, tenant_id: str, project_id: str) -> Optional[PreviewRoute]:
        with self._lock:
            for route in self._routes.values():
                if route.tenant_id == tenant_id and route.project_id == project_id:
                    return route
        return None

    def count_active(self, tenant_id: str, now: float) -> int:
        with self._lock:
            return sum(1 for r in self._routes.values() if r.tenant_id == tenant_id and now < r.expires_at)

    def remove(self, preview_id: str) -> Optional[PreviewRoute]:
        with self._lock:
            return self._routes.pop(preview_id, None)

    def reap(self, now: float, grace_seconds: float) -> list[PreviewRoute]:
        """Mark newly expired routes as reaped (returned so the caller can stop
        their sandboxes) and delete routes that expired longer than the grace period ago."""
        newly_expired: list[PreviewRoute] = []
        with self._lock:
            for preview_id, route in list(self._routes.items()):
                if now < route.expires_at:
                    continue
                if route.reaped:
                    if now >= route.expires_at + grace_seconds:
                        del self._routes[preview_id]
                    continue
                reaped = replace(route, reaped=True)
                self._routes[preview_id] = reaped
                newly_expired.append(reaped)
        return newly_expired


def validate_upstream(upstream: str, allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS) -> str:
    """Return the normalized upstream ("http://host:port") or raise UpstreamNotAllowed."""
    if not isinstance(upstream, str) or not upstream:
        raise UpstreamNotAllowed("Upstream must be a non-empty string")
    try:
        parts = urlsplit(upstream)
        port = parts.port
    except ValueError:
        raise UpstreamNotAllowed("Upstream is not a valid URL") from None
    if parts.scheme != "http":
        raise UpstreamNotAllowed("Upstream must use http")
    if parts.username is not None or parts.password is not None:
        raise UpstreamNotAllowed("Upstream must not contain credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise UpstreamNotAllowed("Upstream must be only scheme://host:port")
    host = (parts.hostname or "").lower()
    if host not in {h.lower() for h in allowed_hosts}:
        raise UpstreamNotAllowed("Upstream host is not allowed")
    if port is None or not (MIN_UPSTREAM_PORT <= port <= 65535):
        raise UpstreamNotAllowed(f"Upstream port must be between {MIN_UPSTREAM_PORT} and 65535")
    return f"http://{host}:{port}"


def _check_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID_PART.match(value):
        raise ValueError(f"Invalid {label}")


class PreviewService:
    """What the Build Engine calls: register_preview(tenant_id, project_id, upstream)."""

    def __init__(
        self,
        registry: PreviewRegistry,
        base_domain: str,
        *,
        scheme: str = "https",
        public_port: Optional[int] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        grace_seconds: int = DEFAULT_GRACE_SECONDS,
        allowed_upstream_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
        max_per_tenant: int = DEFAULT_MAX_PER_TENANT,
        on_stop: Optional[Callable[[PreviewRoute], None]] = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._registry = registry
        self._base_domain = base_domain.lower()
        self._scheme = scheme
        self._public_port = public_port
        self._ttl = ttl_seconds
        self._grace = grace_seconds
        self._allowed_hosts = allowed_upstream_hosts
        self._max_per_tenant = max_per_tenant
        self._on_stop = on_stop
        self._clock = clock

    def _url_for(self, preview_id: str) -> str:
        port = f":{self._public_port}" if self._public_port else ""
        return f"{self._scheme}://{PREVIEW_PREFIX}{preview_id}.{self._base_domain}{port}"

    def _stop(self, route: PreviewRoute) -> None:
        if self._on_stop is None:
            return
        try:
            self._on_stop(route)
        except Exception:
            logger.exception("Stopping preview %s failed", route.preview_id)

    def register_preview(self, tenant_id: str, project_id: str, upstream: str) -> PreviewInfo:
        _check_id(tenant_id, "tenant_id")
        _check_id(project_id, "project_id")
        upstream = validate_upstream(upstream, self._allowed_hosts)
        now = self._clock()

        # One preview per project: a new one replaces (and stops) the old one.
        existing = self._registry.find_by_project(tenant_id, project_id)
        if existing is not None:
            self._registry.remove(existing.preview_id)
            if not existing.reaped:
                self._stop(existing)

        if self._registry.count_active(tenant_id, now) >= self._max_per_tenant:
            raise PreviewQuotaExceeded(f"Limit of {self._max_per_tenant} active previews reached")

        preview_id = secrets.token_hex(ID_BYTES)
        while self._registry.get(preview_id) is not None:  # astronomically unlikely
            preview_id = secrets.token_hex(ID_BYTES)
        route = PreviewRoute(
            preview_id=preview_id,
            tenant_id=tenant_id,
            project_id=project_id,
            upstream=upstream,
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._registry.add(route)
        return PreviewInfo(preview_id, self._url_for(preview_id), route.expires_at)

    def get_status(self, tenant_id: str, preview_id: str) -> Optional[str]:
        """'active', 'expired', or None (unknown, or belongs to another tenant)."""
        route = self._registry.get(preview_id)
        if route is None or route.tenant_id != tenant_id:
            return None
        return "expired" if self._clock() >= route.expires_at else "active"

    def stop_preview(self, tenant_id: str, project_id: str) -> bool:
        route = self._registry.find_by_project(tenant_id, project_id)
        if route is None:
            return False
        self._registry.remove(route.preview_id)
        if not route.reaped:
            self._stop(route)
        return True

    def reap(self) -> list[PreviewRoute]:
        """Stop sandboxes of expired previews. Call every minute or so."""
        expired = self._registry.reap(self._clock(), self._grace)
        for route in expired:
            self._stop(route)
        return expired