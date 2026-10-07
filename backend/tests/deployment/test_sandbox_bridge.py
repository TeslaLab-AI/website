from dataclasses import dataclass

import pytest

from app.deployment.adapters import DeployStatus, FakeAdapter
from app.deployment.deploy_config import DeployConfig
from app.deployment.deploy_lock import DeployLock
from app.deployment.deployment_engine import DeploymentEngine
from app.deployment.deployment_records import InMemoryDeploymentRepository
from app.deployment.preview_registry import (
    InMemoryPreviewRegistry,
    PreviewService,
    UpstreamNotAllowed,
)
from app.deployment.sandbox_bridge import make_preview_hook, run_checks
from app.deployment.secret_service import SecretService
from app.deployment.secret_store import ENV_VAR, generate_key
from app.deployment.secrets_repo import InMemorySecretsRepository
from app.deployment.validation_gate import CheckStatus, evaluate_gate

A = "tenant-a"
P, F, S, E = CheckStatus.PASSED, CheckStatus.FAILED, CheckStatus.SKIPPED, CheckStatus.ERROR


@dataclass
class RunResult:  # same fields as the Build Engine's RunResult
    ok: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.1
    timed_out: bool = False


def config(install="npm ci", build="npm run build"):
    return DeployConfig(
        framework="nextjs", node_version="22", install_command=install, build_command=build,
        start_command="npm run start", output_directory=".next", required_env=(), database=False,
    )


class FakeSandbox:
    """Records every call. `failures` maps a command prefix to a RunResult to return."""

    def __init__(self, failures=None, raises=None, as_dict=False):
        self.calls = []
        self.failures = failures or {}
        self.raises = raises
        self.as_dict = as_dict

    def __call__(self, tenant_id, project_id, argv):
        self.calls.append((tenant_id, project_id, argv))
        if self.raises:
            raise self.raises
        for prefix, result in self.failures.items():
            if " ".join(argv).startswith(prefix):
                return self._wrap(result)
        return self._wrap(RunResult(True, 0))

    def _wrap(self, result):
        return result.__dict__ if self.as_dict else result


def statuses(results):
    return {r.name: r.status for r in results}


# -- run_checks ------------------------------------------------------------------
def test_all_commands_pass_and_the_gate_allows_the_deploy():
    sandbox = FakeSandbox()
    results = run_checks(sandbox, A, "p1", config())
    assert [r.name for r in results] == ["install", "lint", "type_check", "build", "tests"]
    assert all(r.status == P for r in results)
    assert evaluate_gate(results).allowed is True


def test_commands_are_argv_lists_run_for_the_right_tenant_and_project():
    sandbox = FakeSandbox()
    run_checks(sandbox, A, "p1", config())
    assert [call[2] for call in sandbox.calls] == [
        ["npm", "ci"], ["npm", "run", "lint"], ["npx", "tsc", "--noEmit"],
        ["npm", "run", "build"], ["npm", "run", "test"],
    ]
    assert all(call[:2] == (A, "p1") for call in sandbox.calls)
    assert all(isinstance(call[2], list) for call in sandbox.calls)


def test_a_failing_check_is_reported_and_blocks_the_gate():
    sandbox = FakeSandbox(failures={"npm run lint": RunResult(False, 1, stderr="Error: unused variable")})
    results = run_checks(sandbox, A, "p1", config())
    assert statuses(results)["lint"] == F
    assert "unused variable" in next(r for r in results if r.name == "lint").output
    assert evaluate_gate(results).reasons == ("lint failed",)


def test_install_failure_marks_everything_else_as_not_run():
    sandbox = FakeSandbox(failures={"npm ci": RunResult(False, 1, stderr="npm error code E404")})
    results = run_checks(sandbox, A, "p1", config())
    assert statuses(results) == {"install": F, "lint": E, "type_check": E, "build": E, "tests": E}
    assert len(sandbox.calls) == 1  # nothing else was run
    assert evaluate_gate(results).allowed is False


def test_timeout_and_missing_exit_code_are_errors_not_passes():
    timed_out = FakeSandbox(failures={"npm run build": RunResult(False, 124, timed_out=True)})
    assert statuses(run_checks(timed_out, A, "p1", config()))["build"] == E
    no_code = FakeSandbox(failures={"npm run build": RunResult(True, None)})
    assert statuses(run_checks(no_code, A, "p1", config()))["build"] == E


def test_missing_scripts_are_skipped_and_the_gate_blocks():
    results = run_checks(FakeSandbox(), A, "p1", config(), scripts={"build", "dev"})
    assert statuses(results)["lint"] == S and statuses(results)["tests"] == S
    assert "no 'lint' script" in next(r for r in results if r.name == "lint").output
    assert evaluate_gate(results).reasons == ("lint was skipped", "tests was skipped")


def test_all_scripts_present_runs_everything():
    results = run_checks(FakeSandbox(), A, "p1", config(), scripts={"lint", "test", "build"})
    assert evaluate_gate(results).allowed is True


def test_package_managers_use_their_own_commands():
    pnpm = FakeSandbox()
    run_checks(pnpm, A, "p1", config(install="pnpm install --frozen-lockfile", build="pnpm run build"))
    assert [c[2] for c in pnpm.calls][1:3] == [["pnpm", "run", "lint"], ["pnpm", "exec", "tsc", "--noEmit"]]
    yarn = FakeSandbox()
    run_checks(yarn, A, "p1", config(install="yarn install --frozen-lockfile", build="yarn build"))
    assert [c[2] for c in yarn.calls][1:3] == [["yarn", "lint"], ["yarn", "tsc", "--noEmit"]]


def test_accepts_dict_results_as_well_as_objects():
    sandbox = FakeSandbox(as_dict=True, failures={"npm run lint": RunResult(False, 2, stderr="bad")})
    results = run_checks(sandbox, A, "p1", config())
    assert statuses(results)["lint"] == F and statuses(results)["build"] == P


def test_sandbox_exceptions_become_errors_without_leaking_details():
    sandbox = FakeSandbox(raises=RuntimeError("secret path /root/token=abc123"))
    results = run_checks(sandbox, A, "p1", config())
    assert statuses(results)["install"] == E
    assert "abc123" not in repr(results)


def test_secrets_in_command_output_are_masked():
    token = "ghp_" + "a1B2c3D4e5" * 4
    sandbox = FakeSandbox(failures={"npm run build": RunResult(False, 1, stderr=f"clone failed token={token}")})
    results = run_checks(sandbox, A, "p1", config())
    assert token not in repr(results)


# -- preview hook -------------------------------------------------------------------
def test_preview_hook_registers_and_returns_the_url():
    registry = InMemoryPreviewRegistry()
    service = PreviewService(registry, "localhost", scheme="http", public_port=8080)
    hook = make_preview_hook(service)
    url = hook(A, "p1", "http://127.0.0.1:3005")
    assert url.startswith("http://preview-") and url.endswith(".localhost:8080")
    preview_id = url.split("//")[1].split(".")[0].removeprefix("preview-")
    assert service.get_status(A, preview_id) == "active"
    assert service.get_status("tenant-b", preview_id) is None


def test_preview_hook_rejects_upstreams_that_are_not_allowed():
    hook = make_preview_hook(PreviewService(InMemoryPreviewRegistry(), "localhost"))
    with pytest.raises(UpstreamNotAllowed):
        hook(A, "p1", "http://169.254.169.254:8080")


# -- end to end: sandbox checks -> gate -> engine -> live URL ----------------------------
@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv(ENV_VAR, generate_key())


def make_engine():
    return DeploymentEngine(
        FakeAdapter(), SecretService(InMemorySecretsRepository()),
        InMemoryDeploymentRepository(), DeployLock(), sleep=lambda s: None,
    )


def test_sandbox_checks_feed_the_engine_and_a_clean_build_goes_live(env):
    checks = run_checks(FakeSandbox(), A, "p1", config())
    record = make_engine().deploy(A, "p1", "1.0.0", "https://github.com/x/y", "main", checks)
    assert record.status == DeployStatus.READY and record.url


def test_a_failing_sandbox_check_stops_the_engine_before_the_provider(env):
    sandbox = FakeSandbox(failures={"npm run build": RunResult(False, 1, stderr="Type error: bad")})
    record = make_engine().deploy(A, "p1", "1.0.0", "https://github.com/x/y", "main",
                                  run_checks(sandbox, A, "p1", config()))
    assert record.status == DeployStatus.FAILED
    assert "build failed" in record.error and record.provider_deployment_id is None
