"""Offline tests for generation, LLM calls, and the bounded build loop."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import build
import llm
import sandbox
from models.project import ProjectStatus
from plan import Plan


def make_plan() -> Plan:
    return Plan.model_validate({
        "version": "1", "app_type": "website", "name": "Example",
        "requirements": [], "pages": [{"route": "/", "title": "Home", "purpose": "Main"}],
        "features": [], "db": [], "apis": [], "env_vars": [],
        "files": [{"path": "app/page.tsx", "purpose": "Main page"}],
    })


def make_project(status: ProjectStatus = ProjectStatus.BUILDING) -> SimpleNamespace:
    return SimpleNamespace(
        id="p1", tenant_id="t1", status=status, history=[], maintenance=None, deployment=None
    )


@pytest.fixture()
def sandbox_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "sandboxes"
    monkeypatch.setattr(sandbox, "SANDBOX_ROOT", root)
    return root


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def test_generate_files_uses_template_and_writes_plan_file(
    tmp_path: Path, sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    template = root / "templates" / "base"
    (template / "node_modules").mkdir(parents=True)
    (template / "app").mkdir()
    (template / "app" / "page.tsx").write_text("starter", encoding="utf-8")
    (root / "prompts").mkdir()
    (root / "prompts" / "code.v1.md").write_text("code", encoding="utf-8")
    monkeypatch.setattr(build, "ROOT", root)
    monkeypatch.setattr(build, "complete", lambda system, user, json_mode=False: "export default 1")
    build.generate_files(make_plan(), "t1", "p1")
    assert (sandbox_root / "t1" / "p1" / "app" / "page.tsx").read_text() == "export default 1"


def test_generate_files_fails_clearly_without_template_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    (root / "templates" / "base").mkdir(parents=True)
    monkeypatch.setattr(build, "ROOT", root)
    with pytest.raises(RuntimeError, match="npm install --prefix templates/base"):
        build.generate_files(make_plan(), "t1", "p1")


def test_build_loop_stops_on_repeated_signature_and_saves_run_result(
    sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox.create_file("t1", "p1", "app/page.tsx", "broken")
    result = sandbox.RunResult(False, 1, "", "app/page.tsx: Type error", 0.1, False)
    calls: list[list[str]] = []

    def run_command(tenant_id: str, project_id: str, argv: list[str], **kwargs: object) -> sandbox.RunResult:
        calls.append(argv)
        return result

    monkeypatch.setattr(sandbox, "run_command", run_command)
    monkeypatch.setattr(build, "complete", lambda *args, **kwargs: json.dumps({"app/page.tsx": "still broken"}))
    project = make_project()
    assert build.build_loop(project) is False
    assert len(calls) == 2
    assert project.status == ProjectStatus.ERROR
    assert project.maintenance["last_error"] == {
        "ok": False, "exit_code": 1, "stdout": "", "stderr": "app/page.tsx: Type error",
        "duration_s": 0.1, "timed_out": False,
    }


def test_build_loop_stops_after_five_attempts(
    sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox.create_file("t1", "p1", "app/page.tsx", "broken")
    results = [sandbox.RunResult(False, 1, "", f"app/page.tsx: Error {n}", 0.1, False) for n in range(5)]
    calls = 0

    def run_command(*args: object, **kwargs: object) -> sandbox.RunResult:
        nonlocal calls
        calls += 1
        return results[calls - 1]

    monkeypatch.setattr(sandbox, "run_command", run_command)
    monkeypatch.setattr(build, "complete", lambda *args, **kwargs: json.dumps({"app/page.tsx": "still broken"}))
    assert build.build_loop(make_project()) is False
    assert calls == 5


def test_build_loop_respects_ready_transition_and_succeeds(
    sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "run_command", lambda *args, **kwargs: sandbox.RunResult(True, 0, "ok", "", 0.1, False))
    project = make_project(ProjectStatus.READY)
    assert build.build_loop(project) is True
    assert project.status == ProjectStatus.READY
    assert project.history["events"][-1]["stage"] == "build"


def test_gemini_client_fails_cleanly_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY and GEMINI_MODEL"):
        llm.complete("system", "user")


def test_gemini_client_retries_server_error_and_uses_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    responses = iter([
        httpx.Response(503, json={}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}),
    ])
    calls: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return next(responses)

    monkeypatch.setattr(llm.httpx, "post", post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    assert llm.complete("system", "user", json_mode=True) == "{}"
    assert len(calls) == 2
    assert calls[0]["headers"] == {"x-goog-api-key": "test-key"}
    assert calls[0]["json"]["generationConfig"] == {"responseMimeType": "application/json"}


def test_background_pipeline_calls_preview_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    import api

    from models.project import Project

    api.Base.metadata.create_all(api.engine)
    with api.SessionLocal() as session:
        project = Project(
            id="preview-test", tenant_id="preview-tenant", owner_id="u", name="Preview",
            type="website", stack="nextjs", status=ProjectStatus.BUILDING,
        )
        session.add(project)
        session.commit()
    monkeypatch.setattr("plan.parse_plan", lambda prompt: make_plan())
    monkeypatch.setattr(build, "generate_files", lambda *args: None)
    monkeypatch.setattr(build, "build_loop", lambda project: True)
    monkeypatch.setattr(sandbox, "start_dev_server", lambda *args: {"port": 43123, "container": "preview"})
    seen: list[tuple[str, str, str]] = []

    def callback(tenant_id: str, project_id: str, upstream: str) -> str:
        seen.append((tenant_id, project_id, upstream))
        return "https://preview.test"

    monkeypatch.setattr(build, "on_preview_ready", callback)
    api._run_build_project("preview-test", "preview-tenant", "prompt")
    assert seen == [("preview-tenant", "preview-test", "http://127.0.0.1:43123")]
    with api.SessionLocal() as session:
        project = session.get(Project, "preview-test")
        assert project.deployment["preview"] == "https://preview.test"


@pytest.mark.docker
@pytest.mark.skipif(not docker_available(), reason="Docker daemon not available")
@pytest.mark.skipif(
    not (Path(__file__).parents[1] / "templates" / "base" / "node_modules").is_dir(),
    reason="base template dependencies are not installed",
)
def test_docker_builds_base_template(sandbox_root: Path) -> None:
    template = Path(__file__).parents[1] / "templates" / "base"
    target = sandbox._project_dir("t1", "template-smoke")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, target, dirs_exist_ok=True)
    result = sandbox.run_command("t1", "template-smoke", ["npm", "run", "build"], timeout_s=300)
    assert result.ok, result.stderr

