"""
Purpose:
Testing Agent — runs smoke validation (syntax & dependency checks) on changed files,
then detects and runs the project's test runner if present.

Smoke Checks on Changed Files:
  1. Syntax validation:
     - JavaScript / Node: node --check <file>
     - Python: python -m py_compile <file>
  2. Dependency validation:
     - JS/TS: ensures newly imported external packages exist in package.json
     - Python: ensures newly imported external packages exist in requirements.txt or pyproject.toml

Test runner detection priority:
  1. pytest (look for pytest.ini, setup.cfg [tool:pytest], pyproject.toml, tests/ dir)
  2. npm test (look for package.json with a "test" script)
  3. No tests found → PASS_WITHOUT_TESTS (with verified smoke checks)

Max execution timeout: 120 seconds.
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum

TEST_TIMEOUT_SECONDS = 120

NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "fs/promises", "http", "http2", "https", "inspector",
    "module", "net", "os", "path", "path/posix", "path/win32", "perf_hooks",
    "process", "punycode", "querystring", "readline", "repl", "stream",
    "stream/consumers", "stream/promises", "stream/web", "string_decoder",
    "sys", "timers", "timers/promises", "tls", "trace_events", "tty",
    "url", "util", "util/types", "v8", "vm", "wasi", "worker_threads", "zlib",
}


class TestStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    PASS_WITHOUT_TESTS = "PASS_WITHOUT_TESTS"   # No test suite found


@dataclass
class TestResult:
    status: TestStatus
    runner: str         # "pytest" | "npm" | "smoke_check" | "none"
    output: str         # stdout + stderr truncated
    failed_count: int


def _find_nearest_file(start_dir: str, workspace_root: str, target_name: str) -> str | None:
    """Finds the nearest target file searching upward from start_dir up to workspace_root."""
    cur = os.path.abspath(start_dir)
    root = os.path.abspath(workspace_root)
    while True:
        candidate = os.path.join(cur, target_name)
        if os.path.isfile(candidate):
            return candidate
        if cur == root or not cur.startswith(root):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def _check_js_syntax(abs_path: str, rel_path: str) -> str | None:
    """Runs `node --check` to verify JavaScript syntax without executing."""
    try:
        res = subprocess.run(
            ["node", "--check", abs_path],
            capture_output=True,
            text=True,
            timeout=10,
            shell=(os.name == "nt"),
        )
        if res.returncode != 0:
            return f"JavaScript syntax error in {rel_path}:\n{res.stderr.strip()}"
    except Exception as ex:
        print(f"[Tester] node --check check skipped: {ex}")
    return None


def _check_python_syntax(abs_path: str, rel_path: str) -> str | None:
    """Runs python py_compile to verify syntax."""
    try:
        res = subprocess.run(
            [sys.executable, "-m", "py_compile", abs_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return f"Python syntax/compilation error in {rel_path}:\n{res.stderr.strip()}"
    except Exception as ex:
        print(f"[Tester] py_compile skipped: {ex}")
    return None


def _check_js_dependencies(abs_path: str, rel_path: str, workspace_root: str) -> str | None:
    """Checks if external npm packages imported in abs_path are declared in package.json."""
    pkg_path = _find_nearest_file(os.path.dirname(abs_path), workspace_root, "package.json")
    if not pkg_path:
        return None

    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return None

    declared_deps = set()
    for dep_key in ("dependencies", "devDependencies", "peerDependencies"):
        if dep_key in manifest and isinstance(manifest[dep_key], dict):
            declared_deps.update(manifest[dep_key].keys())

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception:
        return None

    # Find require('...') and import ... from '...'
    specifiers = re.findall(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""", code)
    specifiers += re.findall(r"""(?:import\s+.*?from\s+|import\s+)['"]([^'"]+)['"]""", code)

    rel_pkg_path = os.path.relpath(pkg_path, workspace_root).replace("\\", "/")

    for spec in specifiers:
        spec = spec.strip()
        if spec.startswith(".") or spec.startswith("/"):
            continue  # Local relative file
        if spec.startswith("node:"):
            continue  # Node builtin prefix

        # Extract root package name (e.g. '@types/node' or 'lodash')
        parts = spec.split("/")
        pkg_name = "/".join(parts[:2]) if spec.startswith("@") and len(parts) >= 2 else parts[0]

        if pkg_name in NODE_BUILTINS:
            continue

        if pkg_name not in declared_deps:
            return (
                f"Dependency Error in {rel_path}:\n"
                f"Package '{pkg_name}' is imported/required but NOT declared in '{rel_pkg_path}' dependencies.\n"
                f"The plan must include an action to update '{rel_pkg_path}' (NOT root package.json) to add '{pkg_name}'."
            )

    return None


def _check_python_dependencies(abs_path: str, rel_path: str, workspace_root: str) -> str | None:
    """Checks if external python packages imported in abs_path are in requirements.txt or pyproject.toml."""
    req_path = _find_nearest_file(os.path.dirname(abs_path), workspace_root, "requirements.txt")
    if not req_path:
        return None

    rel_req_path = os.path.relpath(req_path, workspace_root).replace("\\", "/")

    try:
        with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
            req_lines = [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]
    except Exception:
        return None

    # Normalize declared packages (strip version pins like ==, >=, etc.)
    declared_pkgs = set()
    for line in req_lines:
        pkg = re.split(r"[=><~]", line)[0].strip().replace("-", "_")
        if pkg:
            declared_pkgs.add(pkg)

    stdlib = getattr(sys, "stdlib_module_names", set()) | set(sys.builtin_module_names)

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception:
        return None

    # Extract imports
    imports = re.findall(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)", code, re.MULTILINE)
    file_dir = os.path.dirname(abs_path)

    for mod in set(imports):
        mod_norm = mod.lower().replace("-", "_")
        if mod_norm in stdlib:
            continue
        # Check if local module file or folder exists
        if os.path.exists(os.path.join(file_dir, f"{mod}.py")) or os.path.isdir(os.path.join(file_dir, mod)):
            continue
        if os.path.exists(os.path.join(workspace_root, f"{mod}.py")) or os.path.isdir(os.path.join(workspace_root, mod)):
            continue

        if mod_norm not in declared_pkgs:
            return (
                f"Dependency Error in {rel_path}:\n"
                f"Module '{mod}' is imported but NOT declared in '{rel_req_path}'.\n"
                f"The plan must include an action to update '{rel_req_path}' to declare '{mod}'."
            )

    return None


def _run_smoke_checks(workspace_root: str, changed_files: list[str]) -> tuple[bool, str]:
    """Runs syntax and dependency smoke checks against modified files."""
    for rel_path in changed_files:
        abs_path = os.path.abspath(os.path.join(workspace_root, rel_path))
        if not os.path.isfile(abs_path):
            continue

        ext = os.path.splitext(rel_path)[1].lower()

        # 1. Syntax check
        if ext in (".js", ".mjs", ".cjs"):
            err = _check_js_syntax(abs_path, rel_path)
            if err:
                return False, err
            dep_err = _check_js_dependencies(abs_path, rel_path, workspace_root)
            if dep_err:
                return False, dep_err

        elif ext == ".py":
            err = _check_python_syntax(abs_path, rel_path)
            if err:
                return False, err
            dep_err = _check_python_dependencies(abs_path, rel_path, workspace_root)
            if dep_err:
                return False, dep_err

    return True, "Smoke checks passed."


def _detect_runner(workspace_root: str) -> str | None:
    """Returns 'pytest', 'npm', or None."""
    for indicator in ["pytest.ini", "setup.cfg", "pyproject.toml"]:
        if os.path.exists(os.path.join(workspace_root, indicator)):
            return "pytest"

    for d in ["tests", "test"]:
        if os.path.isdir(os.path.join(workspace_root, d)):
            return "pytest"

    for f in os.listdir(workspace_root):
        if f.startswith("test_") and f.endswith(".py"):
            return "pytest"

    pkg_path = os.path.join(workspace_root, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as fp:
                pkg = json.load(fp)
            scripts = pkg.get("scripts", {})
            if "test" in scripts and scripts["test"] not in ("", "echo \"Error: no test specified\" && exit 1"):
                return "npm"
        except Exception:
            pass

    return None


def run_tests(workspace_root: str, changed_files: list[str] | None = None) -> TestResult:
    # ── 1. Smoke Checks on Changed Files ───────────────────────
    if changed_files:
        smoke_ok, smoke_msg = _run_smoke_checks(workspace_root, changed_files)
        if not smoke_ok:
            print(f"[Tester] Smoke check failed:\n{smoke_msg}")
            return TestResult(
                status=TestStatus.FAILED,
                runner="smoke_checker",
                output=smoke_msg,
                failed_count=1,
            )

    # ── 2. Project Test Suite Execution ────────────────────────
    runner = _detect_runner(workspace_root)

    if runner is None:
        count = len(changed_files) if changed_files else 0
        msg = f"Smoke checks passed (syntax & dependency validation OK for {count} file(s)). No formal test suite found in workspace."
        print(f"[Tester] {msg} -> PASS_WITHOUT_TESTS")
        return TestResult(
            status=TestStatus.PASS_WITHOUT_TESTS,
            runner="none",
            output=msg,
            failed_count=0,
        )

    if runner == "pytest":
        cmd = ["python", "-m", "pytest", "--tb=short", "-q"]
    else:  # npm
        cmd = ["npm", "test", "--", "--passWithNoTests"]

    print(f"[Tester] Running {runner} tests in {workspace_root}...")
    try:
        result = subprocess.run(
            cmd,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            shell=(os.name == "nt"),
        )
        output = (result.stdout + result.stderr)[:3000]
        passed = result.returncode == 0

        failed_count = 0
        if runner == "pytest" and not passed:
            for line in result.stdout.splitlines():
                if "failed" in line.lower():
                    m = re.search(r"(\d+) failed", line)
                    if m:
                        failed_count = int(m.group(1))

        return TestResult(
            status=TestStatus.PASSED if passed else TestStatus.FAILED,
            runner=runner,
            output=output,
            failed_count=failed_count,
        )
    except subprocess.TimeoutExpired:
        return TestResult(
            status=TestStatus.FAILED,
            runner=runner,
            output=f"Test runner timed out after {TEST_TIMEOUT_SECONDS}s.",
            failed_count=0,
        )
    except Exception as e:
        return TestResult(
            status=TestStatus.FAILED,
            runner=runner,
            output=f"Failed to run tests: {e}",
            failed_count=0,
        )
