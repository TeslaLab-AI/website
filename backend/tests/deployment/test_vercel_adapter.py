import json

import httpx
import pytest

from app.deployment.adapters.base import DeploymentError, DeploymentNotFound, DeployStatus
from app.deployment.adapters.vercel import VercelAdapter, parse_github_url, vercel_project_name
from app.deployment.deploy_lock import DeployLock
from app.deployment.deployment_engine import DeploymentEngine
from app.deployment.deployment_records import InMemoryDeploymentRepository
from app.deployment.failure_classifier import FailureKind
from app.deployment.secret_service import SecretService
from app.deployment.secret_store import ENV_VAR, generate_key
from app.deployment.secrets_repo import InMemorySecretsRepository
from app.deployment.validation_gate import CheckResult, CheckStatus

TOKEN = "vcp_secret_token_value"


def make(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return VercelAdapter(TOKEN, team_id="team_1", client=client)


def dep(tenant="t1", project="p1", state="READY", **extra):
    return {"id": "dpl_1", "readyState": state, "url": "raw.vercel.app",
            "alias": ["tl-x.vercel.app"], "meta": {"teamlabTenant": tenant, "teamlabProject": project}, **extra}


def test_parse_repo_url():
    assert parse_github_url("https://github.com/acme/site.git") == ("acme", "site")
    with pytest.raises(DeploymentError):
        parse_github_url("https://evil.com/acme/site")


def test_deploy_creates_project_env_and_deployment():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.content))
        assert req.headers["authorization"] == f"Bearer {TOKEN}"
        if req.url.path.startswith("/v9/projects"):
            return httpx.Response(404)
        if req.url.path == "/v13/deployments":
            body = json.loads(req.content)
            assert body["gitSource"] == {"type": "github", "org": "acme", "repo": "site", "ref": "main"}
            assert body["meta"]["teamlabTenant"] == "t1"
            return httpx.Response(200, json=dep(state="QUEUED"))
        return httpx.Response(200, json={})

    result = make(handler).deploy("t1", "p1", "https://github.com/acme/site", "main", {"API_KEY": "s3cret"})
    assert result.status == DeployStatus.QUEUED
    assert [p for _, p, _ in seen][:3] == ["/v9/projects/" + vercel_project_name("t1", "p1"),
                                           "/v11/projects",
                                           f"/v10/projects/{vercel_project_name('t1', 'p1')}/env"]


def test_status_maps_states_and_prefers_alias():
    r = make(lambda req: httpx.Response(200, json=dep(state="READY"))).status("t1", "dpl_1")
    assert r.status == DeployStatus.READY and r.url == "https://tl-x.vercel.app"
    r = make(lambda req: httpx.Response(200, json=dep(state="ERROR", errorMessage="boom"))).status("t1", "dpl_1")
    assert r.status == DeployStatus.FAILED and r.error == "boom"
    r = make(lambda req: httpx.Response(200, json=dep(state="INITIALIZING"))).status("t1", "dpl_1")
    assert r.status == DeployStatus.QUEUED


def test_other_tenant_gets_not_found():
    adapter = make(lambda req: httpx.Response(200, json=dep(tenant="other")))
    with pytest.raises(DeploymentNotFound):
        adapter.status("t1", "dpl_1")
    with pytest.raises(DeploymentNotFound):
        list(adapter.logs("t1", "dpl_1"))


def test_logs_are_masked_and_levels_set():
    def handler(req):
        if req.url.path.endswith("/events"):
            return httpx.Response(200, json=[
                {"type": "stdout", "text": "Installing", "created": 1700000000000},
                {"type": "stderr", "text": f"Authorization: Bearer {TOKEN}", "created": 1700000001000},
            ])
        return httpx.Response(200, json=dep())

    entries = list(make(handler).logs("t1", "dpl_1"))
    assert [e.level for e in entries] == ["info", "error"]
    assert TOKEN not in entries[1].message


def test_rollback_only_to_ready_deployment_of_same_project():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=dep())

    r = make(handler).rollback("t1", "p1", "dpl_1")
    assert r.status == DeployStatus.ROLLED_BACK and calls[-1].endswith("/promote/dpl_1")
    with pytest.raises(DeploymentNotFound):
        make(lambda req: httpx.Response(200, json=dep(project="other"))).rollback("t1", "p1", "dpl_1")
    with pytest.raises(DeploymentError):
        make(lambda req: httpx.Response(200, json=dep(state="ERROR"))).rollback("t1", "p1", "dpl_1")


def test_errors_never_leak_token():
    with pytest.raises(DeploymentError) as exc:
        make(lambda req: httpx.Response(401)).status("t1", "dpl_1")
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(make(lambda req: httpx.Response(200)))

    def boom(req):
        raise httpx.ConnectError("down", request=req)

    with pytest.raises(DeploymentError):
        make(boom).status("t1", "dpl_1")


# -- fixes from the review -----------------------------------------------------
def test_a_404_while_deploying_is_a_setup_error_not_deployment_not_found():
    def handler(req):
        if req.url.path.startswith("/v9/projects"):
            return httpx.Response(404)
        if req.url.path.endswith("/env"):
            return httpx.Response(404)  # project vanished or repo not connected
        return httpx.Response(200, json={})

    with pytest.raises(DeploymentError) as exc:
        make(handler).deploy("t1", "p1", "https://github.com/acme/site", "main", {"A": "b"})
    assert "GitHub app" in str(exc.value)
    assert not isinstance(exc.value, DeploymentNotFound)


def test_unreadable_json_is_a_provider_error():
    adapter = make(lambda req: httpx.Response(200, content=b"not json at all"))
    with pytest.raises(DeploymentError):
        adapter.status("t1", "dpl_1")


def test_logs_with_an_unexpected_shape_yield_nothing():
    def handler(req):
        if req.url.path.endswith("/events"):
            return httpx.Response(200, json={"unexpected": "object"})
        return httpx.Response(200, json=dep())

    assert list(make(handler).logs("t1", "dpl_1")) == []


@pytest.mark.parametrize("branch", ["", "../x", "a b", "main\n", "x" * 101, None])
def test_invalid_branch_names_are_rejected_before_any_request(branch):
    def handler(req):
        raise AssertionError("no request should be made")

    with pytest.raises(DeploymentError):
        make(handler).deploy("t1", "p1", "https://github.com/acme/site", branch, {})


def test_deleted_deployments_count_as_failed():
    r = make(lambda req: httpx.Response(200, json=dep(state="DELETED"))).status("t1", "dpl_1")
    assert r.status == DeployStatus.FAILED


def test_repo_url_with_trailing_newline_is_not_accepted_as_part_of_the_name():
    assert parse_github_url("https://github.com/acme/site\n") == ("acme", "site")  # stripped first
    with pytest.raises(DeploymentError):
        parse_github_url("https://github.com/acme/site\n/extra")


# -- the real adapter inside the deployment engine ---------------------------------
@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv(ENV_VAR, generate_key())


def engine_with(handler):
    return DeploymentEngine(
        make(handler), SecretService(InMemorySecretsRepository()),
        InMemoryDeploymentRepository(), DeployLock(), sleep=lambda s: None,
    )


GOOD = [CheckResult(n, CheckStatus.PASSED) for n in ("lint", "type_check", "build", "tests")]


def routes(states, events=None):
    """A fake Vercel: status() returns the given states in order, then repeats the last."""
    remaining = list(states)

    def handler(req):
        path = req.url.path
        if path.startswith("/v9/projects"):
            return httpx.Response(404)
        if path == "/v13/deployments" and req.method == "POST":
            return httpx.Response(200, json=dep(state="QUEUED"))
        if path == "/v13/deployments/dpl_1":
            state = remaining.pop(0) if len(remaining) > 1 else remaining[0]
            return httpx.Response(200, json=dep(state=state))
        if path.endswith("/events"):
            return httpx.Response(200, json=events or [])
        return httpx.Response(200, json={})

    return handler


def test_engine_with_vercel_adapter_reaches_ready_and_returns_the_public_url(env):
    record = engine_with(routes(["QUEUED", "BUILDING", "READY"])).deploy(
        "t1", "p1", "1.0.0", "https://github.com/acme/site", "main", GOOD)
    assert record.status == DeployStatus.READY
    assert record.url == "https://tl-x.vercel.app"
    assert record.provider_deployment_id == "dpl_1"


def test_engine_classifies_a_real_vercel_build_failure_from_the_event_logs(env):
    events = [
        {"type": "stdout", "text": "Running npm run build", "created": 1700000000000},
        {"type": "stderr", "text": 'npm error Missing script: "build"', "created": 1700000001000},
    ]
    record = engine_with(routes(["BUILDING", "ERROR"], events)).deploy(
        "t1", "p1", "1.0.0", "https://github.com/acme/site", "main", GOOD)
    assert record.status == DeployStatus.FAILED
    assert record.failure.kind == FailureKind.BUILD_SCRIPT
