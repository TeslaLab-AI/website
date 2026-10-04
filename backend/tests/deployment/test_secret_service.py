import pytest

from app.deployment.adapters import DeployStatus, FakeAdapter
from app.deployment.secret_service import (
    MissingSecretsError,
    SecretService,
    deploy_with_secrets,
)
from app.deployment.secret_store import ENV_VAR, generate_key
from app.deployment.secrets_repo import InMemorySecretsRepository

A, B = "tenant-a", "tenant-b"
VALUE = "sk_live_super_secret_value"


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, generate_key())


@pytest.fixture
def repo():
    return InMemorySecretsRepository()


@pytest.fixture
def service(repo):
    return SecretService(repo)


def test_round_trip(service):
    service.set_secret(A, "p1", "STRIPE_KEY", VALUE)
    assert service.get_env_for_deploy(A, "p1") == {"STRIPE_KEY": VALUE}


def test_only_ciphertext_is_stored(service, repo):
    service.set_secret(A, "p1", "STRIPE_KEY", VALUE)
    stored = repo.get_all(A, "p1")["STRIPE_KEY"]
    assert stored != VALUE and VALUE not in stored


def test_list_keys_returns_names_only(service):
    service.set_secret(A, "p1", "B_KEY", VALUE)
    service.set_secret(A, "p1", "A_KEY", VALUE)
    assert service.list_keys(A, "p1") == ["A_KEY", "B_KEY"]


def test_setting_again_overwrites(service):
    service.set_secret(A, "p1", "K", "old-value")
    service.set_secret(A, "p1", "K", "new-value")
    assert service.get_env_for_deploy(A, "p1") == {"K": "new-value"}


def test_other_tenant_cannot_see_or_delete(service):
    service.set_secret(A, "p1", "K", VALUE)
    assert service.get_env_for_deploy(B, "p1") == {}
    assert service.list_keys(B, "p1") == []
    assert service.delete_secret(B, "p1", "K") is False
    assert service.get_env_for_deploy(A, "p1") == {"K": VALUE}


def test_secrets_are_scoped_per_project(service):
    service.set_secret(A, "p1", "K", VALUE)
    assert service.get_env_for_deploy(A, "p2") == {}


def test_delete(service):
    service.set_secret(A, "p1", "K", VALUE)
    assert service.delete_secret(A, "p1", "K") is True
    assert service.list_keys(A, "p1") == []


def test_validation_and_errors_do_not_leak_value(service):
    with pytest.raises(ValueError) as exc:
        service.set_secret(A, "p1", "bad name!", VALUE)
    assert VALUE not in str(exc.value)
    with pytest.raises(ValueError):
        service.set_secret(A, "p1", "K", "")
    with pytest.raises(ValueError):
        service.set_secret("", "p1", "K", VALUE)
    with pytest.raises(ValueError):
        service.get_env_for_deploy(A, "")


def test_deploy_injects_decrypted_values_without_logging_them(service):
    service.set_secret(A, "p1", "STRIPE_KEY", VALUE)
    adapter = FakeAdapter()
    result = deploy_with_secrets(adapter, service, A, "p1", "https://github.com/x/y", "main")
    assert result.status == DeployStatus.QUEUED
    log_text = " ".join(e.message for e in adapter.logs(A, result.deployment_id))
    assert "STRIPE_KEY" in log_text  # names are fine
    assert VALUE not in log_text


def test_deploy_stops_when_required_variables_are_missing(service):
    service.set_secret(A, "p1", "HAVE_IT", VALUE)
    adapter = FakeAdapter()
    with pytest.raises(MissingSecretsError) as exc:
        deploy_with_secrets(
            adapter, service, A, "p1", "https://github.com/x/y",
            required={"HAVE_IT", "DATABASE_URL"},
        )
    assert exc.value.names == ["DATABASE_URL"]
    assert VALUE not in str(exc.value)


def test_variable_name_with_trailing_newline_is_rejected(service):
    with pytest.raises(ValueError):
        service.set_secret(A, "p1", "STRIPE_KEY\n", VALUE)
