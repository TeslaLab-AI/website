import pytest

from app.deployment.adapters import (
    DeploymentError,
    DeploymentNotFound,
    DeployResult,
    DeployStatus,
    FakeAdapter,
)
from app.deployment.deploy_lock import DeployInProgress, DeployLock
from app.deployment.deployment_poller import PollTimeout, poll_deployment
from app.deployment.deployment_records import DeploymentRecord, InMemoryDeploymentRepository

A, B = "tenant-a", "tenant-b"


class Clock:
    def __init__(self, now=1_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


# -- lock --------------------------------------------------------------------
def test_second_owner_cannot_take_a_held_lock():
    lock = DeployLock()
    assert lock.acquire(A, "p1", "d1") is True
    assert lock.acquire(A, "p1", "d2") is False
    assert lock.is_locked(A, "p1") is True


def test_lock_is_scoped_by_tenant_and_project():
    lock = DeployLock()
    lock.acquire(A, "p1", "d1")
    assert lock.acquire(A, "p2", "d2") is True
    assert lock.acquire(B, "p1", "d3") is True


def test_only_the_owner_can_release():
    lock = DeployLock()
    lock.acquire(A, "p1", "d1")
    assert lock.release(A, "p1", "intruder") is False
    assert lock.is_locked(A, "p1") is True
    assert lock.release(A, "p1", "d1") is True
    assert lock.is_locked(A, "p1") is False
    assert lock.release(A, "p1", "d1") is False


def test_expired_lock_can_be_taken_over():
    clock = Clock()
    lock = DeployLock(ttl_seconds=60, clock=clock)
    lock.acquire(A, "p1", "d1")
    clock.now += 59
    assert lock.acquire(A, "p1", "d2") is False
    clock.now += 2
    assert lock.is_locked(A, "p1") is False
    assert lock.acquire(A, "p1", "d2") is True
    assert lock.release(A, "p1", "d1") is False  # the stale owner cannot free it


def test_owner_can_refresh_its_own_lock():
    clock = Clock()
    lock = DeployLock(ttl_seconds=60, clock=clock)
    lock.acquire(A, "p1", "d1")
    clock.now += 50
    assert lock.acquire(A, "p1", "d1") is True
    clock.now += 50
    assert lock.is_locked(A, "p1") is True


def test_hold_releases_even_on_error_and_blocks_others():
    lock = DeployLock()
    with pytest.raises(RuntimeError):
        with lock.hold(A, "p1", "d1"):
            with pytest.raises(DeployInProgress):
                with lock.hold(A, "p1", "d2"):
                    pass
            raise RuntimeError("deploy crashed")
    assert lock.is_locked(A, "p1") is False


@pytest.mark.parametrize("tenant,project", [("", "p"), ("t", ""), ("a/b", "p"), ("t\n", "p")])
def test_lock_rejects_invalid_ids(tenant, project):
    with pytest.raises(ValueError):
        DeployLock().acquire(tenant, project, "d1")


# -- records -------------------------------------------------------------------
def record(deployment_id, tenant=A, project="p1", created=1.0, status=DeployStatus.READY):
    return DeploymentRecord(deployment_id, tenant, project, "1.0.0", "manual", status, created, created)


def test_records_are_tenant_scoped():
    repo = InMemoryDeploymentRepository()
    repo.save(record("d1"))
    assert repo.get(A, "d1").deployment_id == "d1"
    assert repo.get(B, "d1") is None
    assert repo.get(A, "nope") is None
    assert repo.list_for_project(B, "p1") == []


def test_history_is_newest_first_per_project_and_limited():
    repo = InMemoryDeploymentRepository()
    for i in range(5):
        repo.save(record(f"d{i}", created=float(i)))
    repo.save(record("other-project", project="p2", created=99.0))
    ids = [r.deployment_id for r in repo.list_for_project(A, "p1", limit=3)]
    assert ids == ["d4", "d3", "d2"]


def test_saving_again_updates_the_record():
    repo = InMemoryDeploymentRepository()
    repo.save(record("d1", status=DeployStatus.BUILDING))
    repo.save(record("d1", status=DeployStatus.READY))
    assert repo.get(A, "d1").status == DeployStatus.READY


# -- poller --------------------------------------------------------------------
def deploy(adapter, tenant=A):
    return adapter.deploy(tenant, "p1", "https://github.com/x/y", "main", {})


def test_polls_until_ready_and_reports_each_status_change():
    adapter = FakeAdapter()
    started = deploy(adapter)
    clock = Clock()
    seen = []
    result = poll_deployment(adapter, A, started.deployment_id, sleep=clock.sleep, clock=clock,
                             on_update=lambda r: seen.append(r.status))
    assert result.status == DeployStatus.READY
    assert result.url
    assert seen == [DeployStatus.BUILDING, DeployStatus.READY]


def test_failed_deployment_is_returned_not_raised():
    adapter = FakeAdapter(fail_with="boom")
    started = deploy(adapter)
    clock = Clock()
    result = poll_deployment(adapter, A, started.deployment_id, sleep=clock.sleep, clock=clock)
    assert result.status == DeployStatus.FAILED
    assert result.error == "boom"


class StuckAdapter(FakeAdapter):
    def status(self, tenant_id, deployment_id):
        return DeployResult(deployment_id, DeployStatus.BUILDING)


def test_times_out_when_the_deployment_never_finishes():
    adapter = StuckAdapter()
    started = deploy(adapter)
    clock = Clock()
    with pytest.raises(PollTimeout) as exc:
        poll_deployment(adapter, A, started.deployment_id, timeout=60, sleep=clock.sleep, clock=clock)
    assert exc.value.waited_seconds >= 60


def test_backoff_grows_and_is_capped():
    adapter = StuckAdapter()
    started = deploy(adapter)
    delays = []
    clock = Clock()

    def sleep(seconds):
        delays.append(seconds)
        clock.sleep(seconds)

    with pytest.raises(PollTimeout):
        poll_deployment(adapter, A, started.deployment_id, interval=2, max_interval=10, backoff=2,
                        timeout=100, sleep=sleep, clock=clock)
    assert delays[:4] == [2, 4, 8, 10]
    assert max(delays) == 10


class FlakyAdapter(FakeAdapter):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def status(self, tenant_id, deployment_id):
        if self.failures > 0:
            self.failures -= 1
            raise DeploymentError("provider hiccup")
        return super().status(tenant_id, deployment_id)


def test_transient_provider_errors_are_retried():
    adapter = FlakyAdapter(failures=2)
    started = deploy(adapter)
    clock = Clock()
    result = poll_deployment(adapter, A, started.deployment_id, sleep=clock.sleep, clock=clock)
    assert result.status == DeployStatus.READY


def test_too_many_consecutive_errors_are_raised():
    adapter = FlakyAdapter(failures=10)
    started = deploy(adapter)
    clock = Clock()
    with pytest.raises(DeploymentError):
        poll_deployment(adapter, A, started.deployment_id, max_consecutive_errors=3,
                        sleep=clock.sleep, clock=clock)


def test_unknown_or_other_tenants_deployment_is_not_retried():
    adapter = FakeAdapter()
    started = deploy(adapter)
    clock = Clock()
    with pytest.raises(DeploymentNotFound):
        poll_deployment(adapter, B, started.deployment_id, sleep=clock.sleep, clock=clock)
