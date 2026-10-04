import re

import pytest

from app.deployment.preview_registry import (
    InMemoryPreviewRegistry,
    PreviewQuotaExceeded,
    PreviewService,
    UpstreamNotAllowed,
    validate_upstream,
)

A, B = "tenant-a", "tenant-b"
UP = "http://127.0.0.1:3000"


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def make(**kwargs):
    clock = Clock()
    stopped = []
    registry = InMemoryPreviewRegistry()
    options = dict(scheme="http", public_port=8080, on_stop=stopped.append, clock=clock)
    options.update(kwargs)
    service = PreviewService(registry, "localhost", **options)
    return service, registry, stopped, clock


# -- registering ---------------------------------------------------------
def test_register_returns_random_subdomain_url_and_30_minute_expiry():
    service, _, _, clock = make()
    info = service.register_preview(A, "proj1", UP)
    assert re.fullmatch(r"http://preview-[0-9a-f]{16}\.localhost:8080", info.url)
    assert info.expires_at == clock.now + 30 * 60


def test_preview_ids_are_unique():
    service, *_ = make(max_per_tenant=100)
    ids = {service.register_preview(A, f"proj{i}", UP).preview_id for i in range(50)}
    assert len(ids) == 50


def test_default_url_has_no_port_and_uses_https():
    service = PreviewService(InMemoryPreviewRegistry(), "teslalab.dev")
    assert re.fullmatch(r"https://preview-[0-9a-f]{16}\.teslalab\.dev", service.register_preview(A, "p", UP).url)


@pytest.mark.parametrize("tenant,project", [("", "p"), ("t", ""), ("a/b", "p"), ("t", "p q"), ("t\n", "p"), ("x" * 200, "p")])
def test_invalid_ids_are_rejected(tenant, project):
    service, *_ = make()
    with pytest.raises(ValueError):
        service.register_preview(tenant, project, UP)


# -- upstream validation (SSRF protection) -------------------------------
@pytest.mark.parametrize("value,normalized", [
    ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
    ("http://localhost:4000/", "http://localhost:4000"),
    ("HTTP://LOCALHOST:5000", "http://localhost:5000"),
])
def test_valid_upstreams_are_normalized(value, normalized):
    assert validate_upstream(value) == normalized


@pytest.mark.parametrize("bad", [
    "", "127.0.0.1:3000", "ftp://127.0.0.1:3000", "https://127.0.0.1:3000",
    "http://evil.com:3000", "http://169.254.169.254:8080", "http://10.0.0.5:3000",
    "http://127.0.0.1", "http://127.0.0.1:80", "http://127.0.0.1:99999",
    "http://user:pw@127.0.0.1:3000", "http://127.0.0.1:3000@evil.com:3000",
    "http://127.0.0.1:3000/path", "http://127.0.0.1:3000?x=1", "http://127.0.0.1:3000#frag",
])
def test_bad_upstreams_are_rejected(bad):
    with pytest.raises(UpstreamNotAllowed):
        validate_upstream(bad)


def test_custom_allowed_hosts_for_sandbox_network():
    service, *_ = make(allowed_upstream_hosts=("sandbox-1",))
    assert service.register_preview(A, "p", "http://sandbox-1:3000").url
    with pytest.raises(UpstreamNotAllowed):
        service.register_preview(A, "p2", UP)  # 127.0.0.1 no longer allowed


# -- replacing, quota, status, stopping ----------------------------------
def test_new_preview_for_same_project_replaces_and_stops_the_old_one():
    service, registry, stopped, _ = make()
    first = service.register_preview(A, "proj1", UP)
    second = service.register_preview(A, "proj1", "http://127.0.0.1:3001")
    assert [r.preview_id for r in stopped] == [first.preview_id]
    assert service.get_status(A, first.preview_id) is None
    assert service.get_status(A, second.preview_id) == "active"


def test_quota_per_tenant_and_expired_previews_do_not_count():
    service, _, _, clock = make(max_per_tenant=2)
    service.register_preview(A, "p1", UP)
    service.register_preview(A, "p2", UP)
    with pytest.raises(PreviewQuotaExceeded):
        service.register_preview(A, "p3", UP)
    assert service.register_preview(B, "p1", UP).url  # other tenant unaffected
    clock.now += 31 * 60
    assert service.register_preview(A, "p3", UP).url  # old ones expired


def test_status_is_tenant_scoped_and_turns_expired():
    service, _, _, clock = make()
    info = service.register_preview(A, "p1", UP)
    assert service.get_status(A, info.preview_id) == "active"
    assert service.get_status(B, info.preview_id) is None
    assert service.get_status(A, "0" * 16) is None
    clock.now = info.expires_at  # exactly at expiry counts as expired
    assert service.get_status(A, info.preview_id) == "expired"


def test_stop_preview_is_tenant_scoped_and_stops_sandbox_once():
    service, _, stopped, _ = make()
    info = service.register_preview(A, "p1", UP)
    assert service.stop_preview(B, "p1") is False
    assert service.get_status(A, info.preview_id) == "active"
    assert service.stop_preview(A, "p1") is True
    assert service.stop_preview(A, "p1") is False
    assert len(stopped) == 1
    assert service.get_status(A, info.preview_id) is None


# -- reaping ---------------------------------------------------------------
def test_reap_stops_expired_previews_once_then_purges_after_grace():
    service, registry, stopped, clock = make(grace_seconds=3600)
    live = service.register_preview(A, "live", UP)
    clock.now += 10 * 60
    old = service.register_preview(A, "old", UP)
    clock.now += 21 * 60  # "live" expired (31 min), "old" still active (21 min)
    reaped = service.reap()
    assert [r.project_id for r in reaped] == ["live"]
    assert [r.project_id for r in stopped] == ["live"]
    assert service.get_status(A, live.preview_id) == "expired"
    assert service.get_status(A, old.preview_id) == "active"
    assert service.reap() == []  # not stopped twice
    clock.now += 3600 + 31 * 60
    service.reap()
    assert registry.get(live.preview_id) is None  # purged after the grace period


def test_failing_stop_callback_does_not_break_reaping():
    calls = []

    def broken(route):
        calls.append(route.project_id)
        raise RuntimeError("sandbox unreachable")

    service, _, _, clock = make(on_stop=broken)
    service.register_preview(A, "p1", UP)
    service.register_preview(A, "p2", UP)
    clock.now += 31 * 60
    assert len(service.reap()) == 2
    assert sorted(calls) == ["p1", "p2"]
    assert service.reap() == []


def test_replacing_a_reaped_preview_does_not_stop_it_again():
    service, _, stopped, clock = make()
    service.register_preview(A, "p1", UP)
    clock.now += 31 * 60
    service.reap()
    assert len(stopped) == 1
    service.register_preview(A, "p1", UP)
    assert len(stopped) == 1
