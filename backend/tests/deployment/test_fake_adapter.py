import pytest

from app.deployment.adapters import (
    DeploymentNotFound,
    DeployStatus,
    FakeAdapter,
    VercelAdapter,
)

TENANT = "tenant-a"
OTHER = "tenant-b"


def _deploy(adapter, tenant=TENANT, project="proj1"):
    return adapter.deploy(tenant, project, "https://github.com/x/tl-proj1", "main",
                          {"API_KEY": "super-secret-value"})


def test_deploy_returns_queued():
    result = _deploy(FakeAdapter())
    assert result.status == DeployStatus.QUEUED
    assert result.deployment_id


def test_status_progresses_to_ready_with_url():
    adapter = FakeAdapter()
    dep = _deploy(adapter)
    assert adapter.status(TENANT, dep.deployment_id).status == DeployStatus.BUILDING
    final = adapter.status(TENANT, dep.deployment_id)
    assert final.status == DeployStatus.READY
    assert final.url.startswith("https://")


def test_failure_mode_ends_in_failed_with_error():
    adapter = FakeAdapter(fail_with="Missing env var DATABASE_URL")
    dep = _deploy(adapter)
    adapter.status(TENANT, dep.deployment_id)
    final = adapter.status(TENANT, dep.deployment_id)
    assert final.status == DeployStatus.FAILED
    assert "DATABASE_URL" in final.error


def test_logs_never_contain_env_values():
    adapter = FakeAdapter()
    dep = _deploy(adapter)
    adapter.status(TENANT, dep.deployment_id)
    adapter.status(TENANT, dep.deployment_id)
    text = " ".join(e.message for e in adapter.logs(TENANT, dep.deployment_id))
    assert "super-secret-value" not in text


def test_log_entries_match_shared_schema():
    adapter = FakeAdapter()
    dep = _deploy(adapter)
    entry = next(adapter.logs(TENANT, dep.deployment_id))
    assert entry.project_id == "proj1"
    assert entry.level and entry.source and entry.message and entry.timestamp


def test_other_tenant_cannot_read_status_or_logs():
    adapter = FakeAdapter()
    dep = _deploy(adapter)
    with pytest.raises(DeploymentNotFound):
        adapter.status(OTHER, dep.deployment_id)
    with pytest.raises(DeploymentNotFound):
        list(adapter.logs(OTHER, dep.deployment_id))


def test_rollback_returns_rolled_back():
    adapter = FakeAdapter()
    dep = _deploy(adapter)
    adapter.status(TENANT, dep.deployment_id)
    adapter.status(TENANT, dep.deployment_id)
    result = adapter.rollback(TENANT, "proj1", dep.deployment_id)
    assert result.status == DeployStatus.ROLLED_BACK


def test_rollback_blocked_across_tenants_and_projects():
    adapter = FakeAdapter()
    dep = _deploy(adapter)
    with pytest.raises(DeploymentNotFound):
        adapter.rollback(OTHER, "proj1", dep.deployment_id)
    with pytest.raises(DeploymentNotFound):
        adapter.rollback(TENANT, "different-project", dep.deployment_id)


def test_vercel_adapter_stub_and_token_not_in_repr():
    adapter = VercelAdapter(token="vercel_secret_token")
    assert "vercel_secret_token" not in repr(adapter)
    with pytest.raises(NotImplementedError):
        adapter.deploy(TENANT, "p", "url", "main", {})
