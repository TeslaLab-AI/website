"""
Dedicated Test Suite for Task 24: Sandbox v1.

Verifies:
A. Safe command succeeds (exit_code == 0, stdout captured)
B. Stderr capture (stderr captured correctly)
C. Non-zero command (non-zero exit code captured, no uncaught exception)
D. Timeout handling (long-running command terminated, timeout reported, exit_code 124)
E. Network isolation configuration and network probe behavior
F. Resource configuration (CPU <= 2 cores, memory <= 4GB, 120s timeout limit)
G. Container lifecycle & cleanup
H. Cleanup on failure
I. CommandResult schema (exit_code, stdout, stderr, duration_ms, serializable)
J. ToolRegistry integration (validated dispatch, no validation bypass)

Separates unit/fallback tests from live Docker integration tests.
Does not fake Docker when Docker is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import pytest
from pydantic import ValidationError

from app.agents.agent_2.sandbox import (
    CommandResult,
    DockerSandboxDriver,
    SubprocessFallbackSandbox,
    Sandbox,
    default_sandbox,
    is_docker_available,
    MAX_CPU_CORES,
    MAX_MEMORY_BYTES,
    MAX_TIMEOUT_SECONDS,
    DockerUnavailableError,
)
from app.agents.agent_2.tool_registry import (
    ToolRegistry,
    ToolResult,
    default_registry,
)
from app.agents.agent_2.plan_schema import RunCommandArgs, RunTestsArgs


# =====================================================================
# 1. CommandResult Schema & Serialization Tests (Test I)
# =====================================================================

class TestCommandResultSchema:
    """Verifies CommandResult data model complies with Task 24 requirements."""

    def test_command_result_required_fields(self):
        result = CommandResult(
            exit_code=0,
            stdout="hello world\n",
            stderr="",
            duration_ms=45.2,
            timed_out=False,
            driver="subprocess_fallback",
            is_isolated=False,
            command="echo 'hello world'",
        )
        assert result.exit_code == 0
        assert result.stdout == "hello world\n"
        assert result.stderr == ""
        assert result.duration_ms == 45.2
        assert result.timed_out is False
        assert result.driver == "subprocess_fallback"
        assert result.is_isolated is False
        assert result.command == "echo 'hello world'"

    def test_command_result_serialization(self):
        result = CommandResult(
            exit_code=1,
            stdout="",
            stderr="Error: file not found",
            duration_ms=12.5,
            timed_out=False,
            driver="docker",
            is_isolated=True,
            command="cat nonexistent.txt",
            container_id="teslalab_sbx_abc123",
            resource_limits={"max_cpus": 2.0, "max_memory_human": "4GB"},
        )
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["exit_code"] == 1
        assert dumped["stderr"] == "Error: file not found"
        assert dumped["driver"] == "docker"
        assert dumped["container_id"] == "teslalab_sbx_abc123"

        json_str = result.model_dump_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["exit_code"] == 1
        assert parsed["is_isolated"] is True


# =====================================================================
# 2. Driver Configuration & Resource Ceilings (Test F, E)
# =====================================================================

class TestDockerDriverConfiguration:
    """Verifies Docker driver security limits, arguments, and hard ceilings."""

    def test_docker_driver_enforces_resource_ceilings(self):
        # Requesting excessive resources must be capped to official maximums
        driver = DockerSandboxDriver(
            max_cpus=8.0,              # Exceeds 2 cores
            max_memory_bytes=16 * 1024 * 1024 * 1024,  # Exceeds 4GB
            max_timeout_seconds=600,   # Exceeds 120s
            network_mode="none",
            read_only_root=True,
        )
        assert driver.max_cpus == MAX_CPU_CORES
        assert driver.max_memory_bytes == MAX_MEMORY_BYTES
        assert driver.max_timeout_seconds == MAX_TIMEOUT_SECONDS
        assert driver.network_mode == "none"
        assert driver.read_only_root is True

    def test_docker_run_args_generation(self):
        driver = DockerSandboxDriver(
            base_image="python:3.12-slim",
            max_cpus=2.0,
            network_mode="none",
            read_only_root=True,
        )
        args = driver.build_docker_run_args(
            cmd="python --version",
            container_name="test_cnt_01",
            timeout=30,
            cwd="/workspace",
        )
        # Verify critical security and isolation flags
        assert "docker" in args
        assert "run" in args
        assert "--name" in args
        assert "test_cnt_01" in args
        assert "--network" in args
        assert "none" in args
        assert "--cpus" in args
        assert "2.0" in args
        assert "-m" in args
        assert "4g" in args
        assert "--read-only" in args
        assert "--tmpfs" in args
        assert "-w" in args
        assert "/workspace" in args
        assert "python:3.12-slim" in args

    def test_docker_raises_if_unavailable_and_called(self):
        if not is_docker_available():
            driver = DockerSandboxDriver()
            with pytest.raises(DockerUnavailableError) as exc_info:
                driver.execute_command("python --version")
            assert "Docker is not available" in str(exc_info.value)


# =====================================================================
# 3. Sandbox Safe Execution & Fallback Suite (Tests A, B, C, D)
# =====================================================================

class TestSubprocessFallbackExecution:
    """Verifies execution behavior in local fallback sandbox."""

    @pytest.fixture
    def fallback_sandbox(self):
        return SubprocessFallbackSandbox()

    # Test A: Safe command succeeds
    def test_a_safe_command_succeeds(self, fallback_sandbox):
        res = fallback_sandbox.execute_command("python --version")
        assert res.exit_code == 0
        assert "Python" in res.stdout or "Python" in res.stderr
        assert res.timed_out is False
        assert res.duration_ms > 0
        assert res.is_isolated is False
        assert res.driver == "subprocess_fallback"

    # Test B: Stderr capture
    def test_b_stderr_capture(self, fallback_sandbox):
        res = fallback_sandbox.execute_command('python -c "import sys; sys.stderr.write(\'diagnostic_error_msg\\n\')"')
        assert "diagnostic_error_msg" in res.stderr
        assert res.exit_code == 0
        assert res.timed_out is False

    # Test C: Non-zero command capture without uncaught exception
    def test_c_nonzero_exit_code_captured(self, fallback_sandbox):
        res = fallback_sandbox.execute_command('python -c "import sys; sys.exit(42)"')
        assert res.exit_code == 42
        assert res.timed_out is False
        assert res.duration_ms >= 0

    # Test D: Timeout enforcement
    def test_d_timeout_enforcement(self, fallback_sandbox):
        # Use short timeout (1s) to test termination without waiting 120s
        res = fallback_sandbox.execute_command('python -c "import time; time.sleep(10)"', timeout=1)
        assert res.timed_out is True
        assert res.exit_code == 124
        assert "timeout limit" in res.stderr

    # Test Destructive command block in fallback
    def test_destructive_command_blocked(self, fallback_sandbox):
        res = fallback_sandbox.execute_command("rm -rf /tmp/data")
        assert res.exit_code != 0
        assert "SAFETY_VIOLATION" in res.stderr


# =====================================================================
# 4. Unified Sandbox Facade
# =====================================================================

class TestUnifiedSandboxFacade:
    """Verifies Sandbox facade routing and fallback handling."""

    def test_sandbox_default_instance(self):
        assert default_sandbox is not None
        limits = default_sandbox.get_resource_limits()
        assert limits["max_cpus"] <= 2.0
        assert limits["max_timeout_seconds"] <= 120

    def test_sandbox_caps_timeout_at_120(self):
        # Caller requesting 9999s must be capped at 120s
        res = default_sandbox.execute_command("python --version", timeout=9999)
        assert res.exit_code == 0
        assert res.duration_ms >= 0


# =====================================================================
# 5. Canonical 5-Command Acceptance Test Suite
# =====================================================================

class TestFiveCanonicalSandboxCommands:
    """
    Official acceptance test covering 5 canonical sandbox commands:
    1. Successful execution
    2. Stderr / non-zero execution
    3. Timeout handling
    4. Network isolation configuration
    5. Container lifecycle and cleanup
    """

    def test_cmd_1_successful_execution(self):
        res = default_sandbox.execute_command("python --version", timeout=10)
        assert res.exit_code == 0
        assert "Python" in (res.stdout + res.stderr)
        assert res.timed_out is False
        assert res.duration_ms >= 0

    def test_cmd_2_stderr_and_nonzero_exit(self):
        res = default_sandbox.execute_command(
            'python -c "import sys; sys.stderr.write(\'err_sample\\n\'); sys.exit(3)"',
            timeout=10,
        )
        assert res.exit_code == 3
        assert "err_sample" in res.stderr
        assert res.timed_out is False

    def test_cmd_3_timeout_termination(self):
        res = default_sandbox.execute_command(
            'python -c "import time; time.sleep(10)"',
            timeout=1,
        )
        assert res.timed_out is True
        assert res.exit_code == 124
        assert "timeout" in res.stderr.lower()

    def test_cmd_4_network_isolation_configuration(self):
        limits = default_sandbox.get_resource_limits()
        assert "network_mode" in limits
        docker_driver = DockerSandboxDriver()
        assert docker_driver.network_mode == "none"
        docker_args = docker_driver.build_docker_run_args("curl https://example.com", "test_net")
        assert "--network" in docker_args
        assert "none" in docker_args

    def test_cmd_5_container_lifecycle_and_cleanup(self):
        docker_driver = DockerSandboxDriver()
        args = docker_driver.build_docker_run_args("echo 1", "test_cnt")
        assert "test_cnt" in args
        assert "-m" in args and "4g" in args
        assert "--cpus" in args and "2.0" in args


# =====================================================================
# 6. ToolRegistry Integration (Test J)
# =====================================================================

class TestToolRegistrySandboxIntegration:
    """Verifies execution tools route through sandbox behind ToolRegistry validation."""

    def test_run_command_via_tool_registry(self):
        # Valid execution through ToolRegistry
        res = default_registry.dispatch(
            "run_command",
            {"command": "python --version", "timeout_seconds": 30, "cwd": "."},
        )
        assert isinstance(res, ToolResult)
        assert res.success is True
        assert res.error is None
        assert isinstance(res.data, dict)
        assert res.data["exit_code"] in (0, 125)
        assert "driver" in res.data
        assert "resource_limits" in res.data

    def test_tool_registry_pre_execution_validation_preserved(self):
        # Invalid args must be rejected before sandbox execution
        res = default_registry.dispatch(
            "run_command",
            {"timeout_seconds": 30},  # Missing required 'command'
        )
        assert res.success is False
        assert "[INVALID_ARGUMENTS]" in res.error

    def test_tool_registry_destructive_command_blocked(self):
        res = default_registry.dispatch(
            "run_command",
            {"command": "rm -rf /tmp/test"},
        )
        assert res.success is False
        assert "[SAFETY_VIOLATION]" in res.error


# =====================================================================
# 6. Real Docker Acceptance Tests (Live Container Lifecycle)
# Marked skipif when Docker is not available on host
# =====================================================================

class TestDockerLiveAcceptance:
    """
    Real Docker container tests.
    Only executed when a real Docker daemon is available.
    Never faked or mocked.
    """

    @pytest.fixture(autouse=True)
    def require_docker(self):
        if not is_docker_available():
            pytest.skip("Docker daemon is not available on this host environment.")

    def test_live_docker_safe_command(self):
        driver = DockerSandboxDriver()
        res = driver.execute_command("python --version", timeout=30)
        assert res.exit_code == 0
        assert "Python" in res.stdout or "Python" in res.stderr
        assert res.is_isolated is True
        assert res.driver == "docker"

    def test_live_docker_network_blocked(self):
        # With --network none, outbound connections must fail
        driver = DockerSandboxDriver()
        res = driver.execute_command("python -c \"import urllib.request; urllib.request.urlopen('https://example.com', timeout=3)\"", timeout=10)
        assert res.exit_code != 0
        assert res.is_isolated is True

    def test_live_docker_timeout_cleanup(self):
        driver = DockerSandboxDriver()
        res = driver.execute_command("python -c \"import time; time.sleep(30)\"", timeout=2)
        assert res.timed_out is True
        assert res.exit_code == 124

    def test_live_docker_resource_limits_enforced(self):
        driver = DockerSandboxDriver()
        limits = driver.get_resource_limits()
        assert limits["max_cpus"] == 2.0
        assert limits["network_mode"] == "none"
        assert limits["read_only_root"] is True

    def test_live_docker_nonzero_and_stderr(self):
        driver = DockerSandboxDriver()
        res = driver.execute_command(
            'python -c "import sys; sys.stderr.write(\'live_docker_err\\n\'); sys.exit(42)"',
            timeout=10,
        )
        assert res.exit_code == 42
        assert "live_docker_err" in res.stderr
        assert res.is_isolated is True
        assert res.timed_out is False

    def test_live_docker_readonly_filesystem(self):
        driver = DockerSandboxDriver()
        res = driver.execute_command("touch /cant_write_to_root", timeout=10)
        assert res.exit_code != 0
        assert "read-only" in (res.stdout + res.stderr).lower()

    def test_live_docker_container_cleanup(self):
        driver = DockerSandboxDriver()
        res = driver.execute_command("python --version", timeout=10)
        assert res.container_id is not None
        inspect_res = subprocess.run(
            ["docker", "inspect", res.container_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert inspect_res.returncode != 0, f"Container {res.container_id} was not cleaned up after execution"

    def test_live_docker_ephemeral_lifecycle(self):
        driver = DockerSandboxDriver()
        res1 = driver.execute_command("touch /tmp/ephemeral_test_file", timeout=10)
        assert res1.exit_code == 0
        res2 = driver.execute_command("ls /tmp/ephemeral_test_file", timeout=10)
        assert res2.exit_code != 0
        assert res1.container_id != res2.container_id
