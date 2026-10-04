"""Docker sandbox for the TeslaLab Build Engine."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

SANDBOX_ROOT = Path(os.getenv("SANDBOX_ROOT", "./sandboxes")).resolve()
IMAGE = os.getenv("SANDBOX_IMAGE", "teslalab-sandbox:latest")
ALLOWED_COMMANDS = {"npm", "npx", "node"}
MAX_OUTPUT_CHARS = 200 * 1024


@dataclass
class RunResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool


def _project_dir(tenant_id: str, project_id: str) -> Path:
    root = (SANDBOX_ROOT / tenant_id / project_id).resolve()
    if root != SANDBOX_ROOT and SANDBOX_ROOT not in root.parents:
        raise ValueError("project path escapes sandbox root")
    return root


def _resolve(tenant_id: str, project_id: str, path: str) -> Path:
    if Path(path).is_absolute():
        raise ValueError(f"absolute paths are not allowed: {path}")
    if ".." in Path(path).parts:
        raise ValueError(f"'..' is not allowed in paths: {path}")
    project_dir = _project_dir(tenant_id, project_id)
    target = (project_dir / path).resolve()
    if project_dir not in target.parents:
        raise ValueError(f"path escapes project directory: {path}")
    return target


def create_file(tenant_id: str, project_id: str, path: str, content: str) -> None:
    target = _resolve(tenant_id, project_id, path)
    if target.exists():
        raise FileExistsError(f"file already exists: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def modify_file(tenant_id: str, project_id: str, path: str, content: str) -> None:
    target = _resolve(tenant_id, project_id, path)
    if not target.exists():
        raise FileNotFoundError(f"file does not exist: {path}")
    target.write_text(content, encoding="utf-8")


def list_files(tenant_id: str, project_id: str) -> list[str]:
    project_dir = _project_dir(tenant_id, project_id)
    if not project_dir.exists():
        return []
    return sorted(
        path.relative_to(project_dir).as_posix()
        for path in project_dir.rglob("*")
        if path.is_file()
    )


def _tail(data: str | bytes | None) -> str:
    if data is None:
        return ""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    return text[-MAX_OUTPUT_CHARS:]


def _docker_command(name: str, workdir: Path, argv: list[str], network: bool) -> list[str]:
    return [
        "docker", "run", "--rm",
        "--cpus=1", "--memory=512m", "--pids-limit=256",
        "--user", "node",
        "--network", "bridge" if network else "none",
        "--name", name,
        "-v", f"{workdir.as_posix()}:/workspace",
        "-w", "/workspace",
        IMAGE,
        *argv,
    ]


def _kill_container(name: str) -> None:
    subprocess.run(["docker", "kill", name], capture_output=True, text=True, timeout=30)


def run_command(
    tenant_id: str,
    project_id: str,
    argv: list[str],
    timeout_s: int = 120,
    network: bool = False,
) -> RunResult:
    if not argv or argv[0] not in ALLOWED_COMMANDS:
        raise ValueError(f"command not allowed: {argv[0] if argv else '<empty>'}")
    workdir = _project_dir(tenant_id, project_id)
    workdir.mkdir(parents=True, exist_ok=True)
    name = f"teslalab-{uuid.uuid4().hex[:12]}"
    started = time.monotonic()
    try:
        completed = subprocess.run(
            _docker_command(name, workdir, argv, network),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        _kill_container(name)
        return RunResult(
            ok=False,
            exit_code=124,
            stdout=_tail(exc.stdout),
            stderr=_tail(exc.stderr),
            duration_s=round(time.monotonic() - started, 3),
            timed_out=True,
        )
    return RunResult(
        ok=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=_tail(completed.stdout),
        stderr=_tail(completed.stderr),
        duration_s=round(time.monotonic() - started, 3),
        timed_out=False,
    )
