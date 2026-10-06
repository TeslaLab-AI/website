import pytest

from app.deployment.adapters import DeploymentError, DeployResult, DeployStatus, FakeAdapter
from app.deployment.deploy_lock import DeployInProgress, DeployLock
from app.deployment.deployment_engine import DeploymentEngine
from app.deployment.deployment_records import InMemoryDeploymentRepository
from app.deployment.failure_classifier import FailureKind, Recovery
from app.deployment.secret_service import SecretService
from app.deployment.secret_store import ENV_VAR, generate_key
from app.deployment.secrets_repo import InMemorySecretsRepository
from app.deployment.validation_gate import CheckResult, CheckStatus

A, B = "tenant-a", "tenant-b"
REPO = "https://github.com/x/tl-p1"
P, F = CheckStatus.PASSED, CheckStatus.FAILED


class Clock:
    def __init__(self, now=1_000.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def good_checks(**overrides):
    status = {"lint": P, "type_check": P, "build": P, "tests": P, **overrides}
    return [CheckResult(name, s) for name, s in status.items()]


class CountingAdapter(FakeAdapter):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.deploy_calls = 0

    def deploy(self, *args, **kwargs):
        self.deploy_calls += 1
        return super().deploy(*args, **kwargs)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, generate_key())


class Env:
    def __init__(self, adapter=None, **engine_kwargs):
        self.clock = Clock()
        self.adapter = adapter or CountingAdapter()
        self.secrets = SecretService(InMemorySecretsRepository())
        self.records = InMemoryDeploymentRepository()
        self.lock = DeployLock(clock=self.clock)
        self.events = []
        self.engine = DeploymentEngine(
            self.adapter, self.secrets, self.records, self.lock,
            sleep=self.clock.sleep, clock=self.clock, poll_clock=self.clock,
            on_event=self.events.append, **engine_kwargs,
        )

    def deploy(self, tenant=A, project="p1", checks=None, **kwargs):
        return self.engine.deploy(
            tenant, project, kwargs.pop("version", "1.0.0"), REPO, "main",
            good_checks() if checks is None else checks, **kwargs,
        )


# -- success --------------------------------------------------------------------
def test_successful_deploy_ends_ready_with_url_and_history():
    env = Env()
    record = env.deploy()
    assert record.status == DeployStatus.READY
    assert record.url.startswith("https://")
    assert record.failure is None and record.error is None
    assert [r.deployment_id for r in env.engine.history(A, "p1")] == [record.deployment_id]
    assert env.engine.get(A, record.deployment_id).status == DeployStatus.READY


def test_events_fire_once_per_status_change_in_order():
    env = Env()
    env.deploy()
    assert [e.status for e in env.events] == [
        DeployStatus.QUEUED, DeployStatus.BUILDING, DeployStatus.READY,
    ]


def test_secrets_are_decrypted_and_passed_to_the_provider(monkeypatch):
    env = Env()
    env.secrets.set_secret(A, "p1", "STRIPE_KEY", "sk_live_super_secret")
    seen = {}
    original = env.adapter.deploy

    def spy(tenant_id, project_id, repo_url, branch, env_vars):
        seen.update(env_vars)
        return original(tenant_id, project_id, repo_url, branch, env_vars)

    monkeypatch.setattr(env.adapter, "deploy", spy)
    record = env.deploy(required_env=["STRIPE_KEY"])
    assert seen == {"STRIPE_KEY": "sk_live_super_secret"}
    assert "sk_live_super_secret" not in repr(record)
    assert all("sk_live_super_secret" not in repr(e) for e in env.events)


# -- validation gate -------------------------------------------------------------
def test_failed_checks_block_the_deploy_without_calling_the_provider():
    env = Env()
    record = env.deploy(checks=good_checks(lint=F, tests=F))
    assert record.status == DeployStatus.FAILED
    assert "Blocked by validation gate" in record.error
    assert "lint failed" in record.error and "tests failed" in record.error
    assert env.adapter.deploy_calls == 0
    assert record.provider_deployment_id is None
    assert [e.status for e in env.events] == [DeployStatus.FAILED]


def test_missing_checks_also_block():
    env = Env()
    record = env.deploy(checks=[CheckResult("build", P)])
    assert record.status == DeployStatus.FAILED
    assert env.adapter.deploy_calls == 0


# -- missing environment variables ----------------------------------------------
def test_missing_variables_are_caught_before_a_build_is_wasted():
    env = Env()
    env.secrets.set_secret(A, "p1", "HAVE_IT", "value-1")
    record = env.deploy(required_env=["HAVE_IT", "DATABASE_URL", "STRIPE_KEY"])
    assert record.status == DeployStatus.FAILED
    assert record.failure.kind == FailureKind.MISSING_ENV
    assert record.failure.variables == ("DATABASE_URL", "STRIPE_KEY")
    assert record.failure.recovery == Recovery.SET_ENV
    assert env.adapter.deploy_calls == 0
    assert "value-1" not in repr(record)
    assert env.lock.is_locked(A, "p1") is False


def test_recovery_after_adding_the_missing_variable():
    env = Env()
    first = env.deploy(required_env=["DATABASE_URL"])
    assert first.status == DeployStatus.FAILED
    env.secrets.set_secret(A, "p1", "DATABASE_URL", "postgres://db")
    second = env.deploy(required_env=["DATABASE_URL"])
    assert second.status == DeployStatus.READY
    assert [r.status for r in env.engine.history(A, "p1")] == [DeployStatus.READY, DeployStatus.FAILED]


# -- provider failures are classified --------------------------------------------
@pytest.mark.parametrize("message,kind,detail", [
    ("Error: Environment variable not found: DATABASE_URL.", FailureKind.MISSING_ENV, ""),
    ('The engine "node" is incompatible with this module. Expected version ">=20.9.0". Got "18.17.0"', FailureKind.NODE_VERSION, "20"),
    ('npm error Missing script: "build"', FailureKind.BUILD_SCRIPT, "build"),
    ('Error: No Output Directory named "public" found after the Build completed.', FailureKind.OUTPUT_DIRECTORY, "public"),
    ("Module not found: Can't resolve 'framer-motion'", FailureKind.DEPENDENCY, "framer-motion"),
])
def test_provider_build_failures_are_classified_with_a_recovery(message, kind, detail):
    env = Env(adapter=CountingAdapter(fail_with=message))
    record = env.deploy()
    assert record.status == DeployStatus.FAILED
    assert record.failure.kind == kind
    assert record.failure.detail == detail
    assert record.provider_deployment_id is not None
    assert [e.status for e in env.events][-1] == DeployStatus.FAILED
    assert [e.status for e in env.events].count(DeployStatus.FAILED) == 1
    assert env.lock.is_locked(A, "p1") is False


def test_errors_are_masked_before_being_stored():
    token = "ghp_" + "a1B2c3D4e5" * 4
    env = Env(adapter=CountingAdapter(fail_with=f"Error: clone failed, token={token}"))
    record = env.deploy()
    assert token not in repr(record)
    assert "REDACTED" in record.error


# -- lock -----------------------------------------------------------------------
def test_a_second_deploy_of_the_same_project_is_refused_and_leaves_no_record():
    env = Env()
    env.lock.acquire(A, "p1", "someone-else")
    with pytest.raises(DeployInProgress):
        env.deploy()
    assert env.engine.history(A, "p1") == []
    assert env.adapter.deploy_calls == 0
    assert env.deploy(project="p2").status == DeployStatus.READY  # other projects unaffected


def test_lock_is_released_after_success_and_after_failure():
    env = Env()
    env.deploy()
    assert env.lock.is_locked(A, "p1") is False
    env.deploy(checks=good_checks(build=F))
    assert env.lock.is_locked(A, "p1") is False


# -- timeouts and provider errors -----------------------------------------------
class StuckAdapter(CountingAdapter):
    def status(self, tenant_id, deployment_id):
        return DeployResult(deployment_id, DeployStatus.BUILDING)


def test_a_deployment_that_never_finishes_times_out_as_a_failure():
    env = Env(adapter=StuckAdapter(), poll_timeout=120)
    record = env.deploy()
    assert record.status == DeployStatus.FAILED
    assert record.failure.kind == FailureKind.TIMEOUT
    assert env.lock.is_locked(A, "p1") is False


class BrokenProvider(CountingAdapter):
    def deploy(self, *args, **kwargs):
        raise DeploymentError("provider is down")


def test_provider_errors_when_starting_are_recorded_as_failures():
    env = Env(adapter=BrokenProvider())
    record = env.deploy()
    assert record.status == DeployStatus.FAILED
    assert "provider is down" in record.error
    assert env.lock.is_locked(A, "p1") is False


class ExplodingProvider(CountingAdapter):
    def deploy(self, *args, **kwargs):
        raise RuntimeError("bug in the adapter")


def test_unexpected_errors_never_leave_a_stuck_record_or_lock():
    env = Env(adapter=ExplodingProvider())
    with pytest.raises(RuntimeError):
        env.deploy()
    [record] = env.engine.history(A, "p1")
    assert record.status == DeployStatus.FAILED
    assert env.lock.is_locked(A, "p1") is False


# -- tenants and validation ------------------------------------------------------
def test_history_and_records_are_tenant_scoped():
    env = Env()
    record = env.deploy()
    assert env.engine.history(B, "p1") == []
    assert env.engine.get(B, record.deployment_id) is None


def test_two_tenants_can_deploy_the_same_project_name_at_once():
    env = Env()
    env.lock.acquire(A, "p1", "someone-else")
    assert env.deploy(tenant=B).status == DeployStatus.READY


@pytest.mark.parametrize("tenant,project,version", [("", "p1", "1"), (A, "", "1"), (A, "p1", ""), (A, "p/1", "1"), (A, "p1", "1\n")])
def test_invalid_ids_are_rejected(tenant, project, version):
    env = Env()
    with pytest.raises(ValueError):
        env.engine.deploy(tenant, project, version, REPO, "main", good_checks())
