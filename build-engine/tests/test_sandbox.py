"""Sandbox contract tests for the TeslaLab Build Engine."""
from __future__ import annotations

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

import sandbox


def _docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")


@pytest.fixture()
def sandbox_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path.resolve()
    monkeypatch.setattr(sandbox, "SANDBOX_ROOT", root)
    return root


def test_path_traversal_rejected(sandbox_root: Path) -> None:
    with pytest.raises(ValueError):
        sandbox.create_file("t1", "p1", "../escape.txt", "x")
    with pytest.raises(ValueError):
        sandbox.modify_file("t1", "p1", "a/../../escape.txt", "x")
    assert not (sandbox_root / "escape.txt").exists()


def test_absolute_path_rejected(sandbox_root: Path) -> None:
    with pytest.raises(ValueError):
        sandbox.create_file("t1", "p1", "/etc/passwd", "x")
    with pytest.raises(ValueError):
        sandbox.create_file("t1", "p1", "C:/Windows/x", "x")


def test_symlink_escape_rejected(sandbox_root: Path) -> None:
    project = sandbox_root / "t1" / "p1"
    outside = sandbox_root / "outside"
    project.mkdir(parents=True)
    outside.mkdir()
    try:
        (project / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(ValueError):
        sandbox.create_file("t1", "p1", "link/evil.txt", "x")


def test_create_modify_list_work(sandbox_root: Path) -> None:
    sandbox.create_file("t1", "p1", "src/index.js", "old")
    sandbox.modify_file("t1", "p1", "src/index.js", "new")
    assert sandbox.list_files("t1", "p1") == ["src/index.js"]
    written = sandbox_root / "t1" / "p1" / "src" / "index.js"
    assert written.read_text(encoding="utf-8") == "new"


def test_create_existing_file_rejected(sandbox_root: Path) -> None:
    sandbox.create_file("t1", "p1", "a.js", "1")
    with pytest.raises(FileExistsError):
        sandbox.create_file("t1", "p1", "a.js", "2")


def test_modify_missing_file_rejected(sandbox_root: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sandbox.modify_file("t1", "p1", "missing.js", "x")


def test_list_files_unknown_project_empty(sandbox_root: Path) -> None:
    assert sandbox.list_files("t1", "ghost") == []


def test_disallowed_command_rejected(sandbox_root: Path) -> None:
    for argv in (["rm", "-rf", "/workspace"], ["sh", "-c", "echo hi"], []):
        with pytest.raises(ValueError):
            sandbox.run_command("t1", "p1", argv)


def test_validate_relative_path_rejects_private_and_dependency_paths() -> None:
    for path in ("../outside", ".env", ".env.local", "node_modules/pkg/a.js", ".git/config"):
        with pytest.raises(ValueError):
            sandbox.validate_relative_path(path)
    assert sandbox.validate_relative_path("app/page.tsx") == "app/page.tsx"


def test_preview_server_publishes_loopback_and_reaps_at_ttl(
    sandbox_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = sandbox_root / "t1" / "p1"
    (project / "node_modules").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "container-id", "")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox.time, "time", lambda: 1000.0)
    monkeypatch.setattr(sandbox.socket, "create_connection", lambda *args, **kwargs: nullcontext())
    server = sandbox.start_dev_server("t1", "p1")
    assert "bridge" in calls[0]
    assert f"127.0.0.1:{server['port']}:3000" in calls[0]
    assert calls[0][-8:] == ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]
    assert sandbox.reap_dev_servers(now=1000.0 + sandbox.DEV_SERVER_TTL_S) == 1
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_preview_server_requires_prepared_dependencies(sandbox_root: Path) -> None:
    with pytest.raises(RuntimeError, match="npm install --prefix templates/base"):
        sandbox.start_dev_server("t1", "p1")


@requires_docker
def test_timeout_returns_timed_out(sandbox_root: Path) -> None:
    result = sandbox.run_command(
        "t1", "p1", ["node", "-e", "setInterval(()=>{},1000)"], timeout_s=3
    )
    assert result.timed_out is True
    assert result.ok is False
    assert result.exit_code == 124


@pytest.mark.docker
@requires_docker
def test_docker_npm_install_and_build(sandbox_root: Path) -> None:
    sandbox.create_file(
        "t1",
        "p1",
        "package.json",
        json.dumps({"name": "sandbox-smoke", "version": "1.0.0", "scripts": {"build": "node src.js"}}),
    )
    sandbox.create_file("t1", "p1", "src.js", "console.log('built ok');\n")

    install = sandbox.run_command("t1", "p1", ["npm", "install"], network=True, timeout_s=300)
    assert install.ok, install.stderr

    build = sandbox.run_command("t1", "p1", ["npm", "run", "build"], timeout_s=300)
    assert build.ok, build.stderr
    assert "built ok" in build.stdout
