"""Docker sandbox for the TeslaLab Build Engine."""
from __future__ import annotations

import os
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

SANDBOX_ROOT = Path(os.getenv("SANDBOX_ROOT", "./sandboxes")).resolve()
IMAGE = os.getenv("SANDBOX_IMAGE", "teslalab-sandbox:latest")
ALLOWED_COMMANDS = {"npm", "npx", "node"}
MAX_OUTPUT_CHARS = 200 * 1024
DEV_SERVER_TTL_S = 30 * 60
_DEV_SERVERS: dict[tuple[str, str], tuple[str, float]] = {}


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


def validate_relative_path(path: str) -> str:
    """Validate an untrusted project-relative POSIX path and return it unchanged."""
    if not path or "\x00" in path or "\\" in path or Path(path).is_absolute():
        raise ValueError(f"invalid relative path: {path!r}")
    parts = path.split("/")
    if any(part in {"", ".", "..", ".git", "node_modules"} for part in parts) or any(":" in part for part in parts):
        raise ValueError(f"invalid relative path: {path!r}")
    if parts[0] == ".env" or parts[0].startswith(".env."):
        raise ValueError(f"invalid relative path: {path!r}")
    return path


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


def stop_dev_server(tenant_id: str, project_id: str) -> None:
    """Stop the named preview server for one tenant project."""
    server = _DEV_SERVERS.pop((tenant_id, project_id), None)
    if server is None:
        return
    subprocess.run(["docker", "rm", "-f", server[0]], capture_output=True, text=True, timeout=30)


def reap_dev_servers(now: float | None = None) -> int:
    """Stop expired previews; callers trigger reaping without a scheduler."""
    current = time.time() if now is None else now
    expired = [key for key, (_, started) in _DEV_SERVERS.items() if current - started >= DEV_SERVER_TTL_S]
    for tenant_id, project_id in expired:
        stop_dev_server(tenant_id, project_id)
    return len(expired)


def _wait_for_preview(port: int) -> bool:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start_dev_server(tenant_id: str, project_id: str) -> dict[str, int | str]:
    """Start a port-published, resource-limited Next.js preview container."""
    reap_dev_servers()
    project_dir = _project_dir(tenant_id, project_id)
    if not (project_dir / "node_modules").is_dir():
        raise RuntimeError("template dependencies are missing; run npm install --prefix templates/base")
    stop_dev_server(tenant_id, project_id)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    container = f"teslalab-preview-{uuid.uuid4().hex[:12]}"
    command = [
        "docker", "run", "-d", "--rm", "--cpus=1", "--memory=512m", "--pids-limit=256",
        "--user", "node", "--network", "bridge", "--name", container,
        "-p", f"127.0.0.1:{port}:3000", "-v", f"{project_dir.as_posix()}:/workspace",
        "-w", "/workspace", IMAGE, "npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"preview container failed to start (docker exit {result.returncode})")
    _DEV_SERVERS[(tenant_id, project_id)] = (container, time.time())
    if not _wait_for_preview(port):
        stop_dev_server(tenant_id, project_id)
        raise RuntimeError("preview server did not become ready within 30 seconds")
    return {"port": port, "container": container}
