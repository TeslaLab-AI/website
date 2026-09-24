"""
Sandbox v1 for Engineer 2 (Agent 2) — Task 24.

Provides isolated command and test execution with strict resource limits and security boundaries:
- Ephemeral container per task run
- Maximum 2 CPU cores
- Maximum 4 GB RAM
- Maximum 120 seconds timeout per command
- Network isolation (equivalent to --network none)
- Read-only root filesystem where compatible
- Immediate container cleanup after execution
- Clear distinction between Docker-isolated and local subprocess testing fallback
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import uuid
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("sandbox_v1")

# Hard resource & security ceilings
MAX_CPU_CORES: float = 2.0
MAX_MEMORY_BYTES: int = 4 * 1024 * 1024 * 1024  # 4 GB
MAX_TIMEOUT_SECONDS: int = 120  # 120 seconds hard ceiling
DEFAULT_TIMEOUT_SECONDS: int = 60
DEFAULT_BASE_IMAGE: str = "python:3.12-slim"

DESTRUCTIVE_COMMAND_PATTERNS = [
    r"\brm\s+-(?:rf|fr|r)\b",
    r"\bdrop\s+table\b",
    r"\bcurl\b.*\|\s*(?:ba)?sh",
    r"\bwget\b.*\|\s*(?:ba)?sh",
    r"\bgit\s+push\b.*(?:--force|-f\b|--force-with-lease)",
    r"\bmkfs\b",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;",
]


class DockerUnavailableError(RuntimeError):
    """Raised when Docker daemon or CLI is required but not available on host."""
    pass


class SandboxSecurityViolationError(ValueError):
    """Raised when a command violates sandbox security constraints."""
    pass


class CommandResult(BaseModel):
    """
    Standardized, serializable result model for sandbox command execution.
    Never exposes raw Docker SDK or subprocess objects to callers.
    """
    model_config = ConfigDict(extra="ignore")

    exit_code: int = Field(..., description="Process exit code (0 indicates success)")
    stdout: str = Field(default="", description="Captured standard output")
    stderr: str = Field(default="", description="Captured standard error")
    duration_ms: float = Field(default=0.0, ge=0.0, description="Execution duration in milliseconds")
    timed_out: bool = Field(default=False, description="Whether command timed out")
    driver: str = Field(default="docker", description="Execution driver: 'docker' or 'subprocess_fallback'")
    is_isolated: bool = Field(default=True, description="Whether execution was fully container-isolated")
    command: str = Field(default="", description="Original command string")
    container_id: str | None = Field(default=None, description="Ephemeral container name/ID if Docker was used")
    resource_limits: dict[str, Any] = Field(default_factory=dict, description="Resource limits applied")


def is_docker_available() -> bool:
    """
    Check whether Docker CLI is available on the system PATH and Docker daemon responds.
    """
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        res = subprocess.run(
            [docker_bin, "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return res.returncode == 0
    except Exception:
        return False


class DockerSandboxDriver:
    """
    Production Docker-based Sandbox Driver.
    Enforces ephemeral container lifecycle, CPU/RAM ceilings, network isolation,
    and guaranteed container destruction.
    """

    def __init__(
        self,
        base_image: str = DEFAULT_BASE_IMAGE,
        max_cpus: float = MAX_CPU_CORES,
        max_memory_bytes: int = MAX_MEMORY_BYTES,
        max_timeout_seconds: int = MAX_TIMEOUT_SECONDS,
        network_mode: str = "none",
        read_only_root: bool = True,
    ) -> None:
        self.base_image = base_image
        # Hard cap enforcement
        self.max_cpus = min(max_cpus, MAX_CPU_CORES)
        self.max_memory_bytes = min(max_memory_bytes, MAX_MEMORY_BYTES)
        self.max_timeout_seconds = min(max_timeout_seconds, MAX_TIMEOUT_SECONDS)
        self.network_mode = network_mode
        self.read_only_root = read_only_root
        self.driver_name = "docker"
        self.is_isolated = True

    def get_resource_limits(self) -> dict[str, Any]:
        """Return resource and isolation configuration dictionary."""
        return {
            "max_cpus": self.max_cpus,
            "max_memory_bytes": self.max_memory_bytes,
            "max_memory_human": "4GB",
            "max_timeout_seconds": self.max_timeout_seconds,
            "network_mode": self.network_mode,
            "read_only_root": self.read_only_root,
            "is_isolated": True,
            "driver": self.driver_name,
        }

    def build_docker_run_args(
        self,
        cmd: str,
        container_name: str,
        timeout: int = 60,
        cwd: str | None = None,
    ) -> list[str]:
        """Construct the exact Docker CLI command line with security and resource flags."""
        args = [
            "docker", "run",
            "--name", container_name,
            "--network", self.network_mode,
            "--cpus", str(self.max_cpus),
            "-m", "4g",
        ]
        if self.read_only_root:
            args.extend(["--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

        if cwd:
            norm_cwd = cwd.replace("\\", "/")
            if norm_cwd in (".", "./", ""):
                norm_cwd = "/"
            elif len(norm_cwd) >= 2 and norm_cwd[1] == ":":
                norm_cwd = norm_cwd[2:]
            if not norm_cwd.startswith("/"):
                norm_cwd = f"/{norm_cwd}"
            args.extend(["-w", norm_cwd])

        args.extend([self.base_image, "sh", "-c", cmd])
        return args

    def execute_command(
        self,
        cmd: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        cwd: str | None = None,
    ) -> CommandResult:
        """
        Execute command inside an isolated ephemeral Docker container.
        Lifecycle: create -> start -> execute -> capture -> stop -> remove container.
        Guarantees container cleanup in all outcomes (success, error, timeout).
        """
        if not is_docker_available():
            raise DockerUnavailableError(
                "Docker is not available on this host. Use SubprocessFallbackSandbox for testing/development."
            )

        actual_timeout = min(max(1, timeout), self.max_timeout_seconds)
        container_name = f"teslalab_sbx_{uuid.uuid4().hex[:12]}"
        docker_args = self.build_docker_run_args(cmd, container_name, timeout=actual_timeout, cwd=cwd)

        t0 = time.perf_counter()
        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = -1

        try:
            proc = subprocess.Popen(
                docker_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                stdout, stderr = proc.communicate(timeout=actual_timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
                stderr = f"Command exceeded timeout limit of {actual_timeout}s and was killed."
                try:
                    subprocess.run(["docker", "stop", "-t", "1", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass

        finally:
            # Ephemeral cleanup: Destroy container unconditionally
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception as e:
                logger.warning("Could not remove container %s: %s", container_name, e)

        duration_ms = (time.perf_counter() - t0) * 1000.0

        return CommandResult(
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=round(duration_ms, 2),
            timed_out=timed_out,
            driver=self.driver_name,
            is_isolated=True,
            command=cmd,
            container_id=container_name,
            resource_limits=self.get_resource_limits(),
        )


class SubprocessFallbackSandbox:
    """
    Local Subprocess Testing Fallback Sandbox.
    Used exclusively when Docker is unavailable in the test/development environment.
    Enforces timeout ceilings and blocks destructive host commands.
    Explicitly marks is_isolated=False and driver='subprocess_fallback'.
    """

    def __init__(
        self,
        max_timeout_seconds: int = MAX_TIMEOUT_SECONDS,
    ) -> None:
        self.max_timeout_seconds = min(max_timeout_seconds, MAX_TIMEOUT_SECONDS)
        self.driver_name = "subprocess_fallback"
        self.is_isolated = False

    def get_resource_limits(self) -> dict[str, Any]:
        """Return metadata indicating fallback execution mode."""
        return {
            "max_cpus": MAX_CPU_CORES,
            "max_memory_bytes": MAX_MEMORY_BYTES,
            "max_timeout_seconds": self.max_timeout_seconds,
            "network_mode": "unisolated_host_fallback",
            "read_only_root": False,
            "is_isolated": False,
            "driver": self.driver_name,
            "fallback_notice": "Testing fallback mode: Host subprocess without Docker isolation",
        }

    def _is_destructive(self, cmd: str) -> bool:
        return any(re.search(pat, cmd, re.IGNORECASE) for pat in DESTRUCTIVE_COMMAND_PATTERNS)

    def execute_command(
        self,
        cmd: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        cwd: str | None = None,
    ) -> CommandResult:
        """
        Execute command via controlled local subprocess with timeout enforcement.
        """
        if self._is_destructive(cmd):
            return CommandResult(
                exit_code=1,
                stdout="",
                stderr=f"[SAFETY_VIOLATION] Destructive command blocked in fallback sandbox: '{cmd}'",
                duration_ms=0.1,
                timed_out=False,
                driver=self.driver_name,
                is_isolated=False,
                command=cmd,
                resource_limits=self.get_resource_limits(),
            )

        actual_timeout = min(max(1, timeout), self.max_timeout_seconds)
        t0 = time.perf_counter()
        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = -1

        exec_cmd = cmd
        if exec_cmd.strip().startswith("pytest") and not shutil.which("pytest"):
            exec_cmd = f'"{sys.executable}" -m {exec_cmd.strip()}'

        try:
            proc = subprocess.Popen(
                exec_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
            )
            try:
                stdout, stderr = proc.communicate(timeout=actual_timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                exit_code = 124
                stderr = f"Command exceeded timeout limit of {actual_timeout}s and was terminated."
                try:
                    proc.kill()
                    stdout_extra, stderr_extra = proc.communicate(timeout=2)
                    stdout = (stdout or "") + (stdout_extra or "")
                except Exception:
                    pass

        except Exception as exc:
            stderr = f"[SUBPROCESS_ERROR] Failed to spawn process: {exc}"
            exit_code = 1

        duration_ms = (time.perf_counter() - t0) * 1000.0

        return CommandResult(
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=round(duration_ms, 2),
            timed_out=timed_out,
            driver=self.driver_name,
            is_isolated=False,
            command=cmd,
            container_id=None,
            resource_limits=self.get_resource_limits(),
        )


class Sandbox:
    """
    Unified Sandbox API.
    Routes commands to DockerSandboxDriver when Docker is present,
    or to SubprocessFallbackSandbox when Docker is unavailable in testing.
    """

    def __init__(
        self,
        driver: Any = None,
        allow_fallback: bool = True,
        base_image: str = DEFAULT_BASE_IMAGE,
    ) -> None:
        self.allow_fallback = allow_fallback
        self.base_image = base_image

        if driver is not None:
            self.driver = driver
        elif is_docker_available():
            self.driver = DockerSandboxDriver(base_image=base_image)
        elif allow_fallback:
            logger.info("Docker is unavailable on host. Initializing SubprocessFallbackSandbox for testing/development.")
            self.driver = SubprocessFallbackSandbox()
        else:
            raise DockerUnavailableError("Docker is unavailable and allow_fallback is False.")

    def execute_command(
        self,
        cmd: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        cwd: str | None = None,
    ) -> CommandResult:
        """
        Execute command with hard 120s timeout enforcement.
        Returns CommandResult(exit_code, stdout, stderr, duration_ms, timed_out, ...).
        """
        # Hard ceiling enforcement
        effective_timeout = min(max(1, timeout), MAX_TIMEOUT_SECONDS)
        return self.driver.execute_command(cmd, timeout=effective_timeout, cwd=cwd)

    def get_resource_limits(self) -> dict[str, Any]:
        """Return active sandbox driver's resource and isolation limits."""
        return self.driver.get_resource_limits()


# Global default Sandbox instance
default_sandbox = Sandbox()
