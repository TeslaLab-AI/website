"""Glue between the Build Engine (Intern 1's sandbox) and the Deployment Engine.

1. run_checks(...)        runs install, lint, type-check, build and tests in the
                          sandbox and returns CheckResults for the validation gate.
2. make_preview_hook(...) gives the Build Engine the function it calls after a dev
                          server starts: on_preview_ready(tenant_id, project_id, upstream) -> url

We do NOT import the Build Engine. Its sandbox is passed in as a plain function:

    run_command(tenant_id, project_id, argv: list[str]) -> RunResult
    RunResult = {ok, exit_code, stdout, stderr, duration_s, timed_out}   (object or dict)

Commands are argv LISTS built from fixed templates (the install and build commands
come from the already-validated deploy.json), never shell strings.
"""

from __future__ import annotations

import shlex
from typing import Any, Callable, Collection, Optional

from .deploy_config import DeployConfig
from .preview_registry import PreviewService
from .validation_gate import CheckResult, CheckStatus, check_from_command

RunCommand = Callable[[str, str, list], Any]

_SCRIPT_NAMES = {"lint": "lint", "tests": "test"}


def _field(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _manager(config: DeployConfig) -> str:
    command = config.install_command
    if command.startswith("pnpm"):
        return "pnpm"
    if command.startswith("yarn"):
        return "yarn"
    return "npm"


def _script(manager: str, name: str) -> list:
    return {"npm": ["npm", "run", name], "pnpm": ["pnpm", "run", name], "yarn": ["yarn", name]}[manager]


def _exec(manager: str, args: list) -> list:
    return {"npm": ["npx", *args], "pnpm": ["pnpm", "exec", *args], "yarn": ["yarn", *args]}[manager]


def _run(run_command: RunCommand, tenant_id: str, project_id: str, name: str, argv: list) -> CheckResult:
    try:
        result = run_command(tenant_id, project_id, argv)
    except Exception:
        # Do not copy the exception text: it may contain paths or secrets.
        return CheckResult(name, CheckStatus.ERROR, "sandbox could not run this command")
    output = "\n".join(
        str(part) for part in (_field(result, "stdout", ""), _field(result, "stderr", "")) if part
    )
    return check_from_command(
        name,
        _field(result, "exit_code"),
        output,
        _field(result, "duration_s"),
        timed_out=bool(_field(result, "timed_out", False)),
    )


def run_checks(
    run_command: RunCommand,
    tenant_id: str,
    project_id: str,
    config: DeployConfig,
    scripts: Optional[Collection[str]] = None,
) -> list:
    """Run install, lint, type_check, build and tests. Returns CheckResults.

    scripts: names of the scripts in package.json. If given, a missing 'lint' or
    'test' script gives a SKIPPED check (the gate then blocks, fail closed).
    If the install fails, the other checks are ERROR ("not run").
    """
    manager = _manager(config)
    install = _run(run_command, tenant_id, project_id, "install", shlex.split(config.install_command))
    results = [install]

    steps = [
        ("lint", _script(manager, "lint")),
        ("type_check", _exec(manager, ["tsc", "--noEmit"])),
        ("build", shlex.split(config.build_command)),
        ("tests", _script(manager, "test")),
    ]
    for name, argv in steps:
        script = _SCRIPT_NAMES.get(name)
        if install.status != CheckStatus.PASSED:
            results.append(CheckResult(name, CheckStatus.ERROR, "not run: dependency install failed"))
        elif script and scripts is not None and script not in scripts:
            results.append(CheckResult(name, CheckStatus.SKIPPED, f"no '{script}' script in package.json"))
        else:
            results.append(_run(run_command, tenant_id, project_id, name, argv))
    return results


def make_preview_hook(service: PreviewService) -> Callable[[str, str, str], str]:
    """The Build Engine calls this after its dev server starts. Returns the preview URL.

    Raises PreviewError (UpstreamNotAllowed, PreviewQuotaExceeded) or ValueError if the
    preview cannot be registered; the Build Engine should handle that.
    """

    def on_preview_ready(tenant_id: str, project_id: str, upstream: str) -> str:
        return service.register_preview(tenant_id, project_id, upstream).url

    return on_preview_ready
