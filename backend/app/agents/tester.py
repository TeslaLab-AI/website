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
import time
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pydantic import BaseModel, Field

TEST_TIMEOUT_SECONDS = 120
DEFAULT_TEST_TIMEOUT_SECONDS: float = 60.0

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


class TestFailure(BaseModel):
    __test__ = False
    test_name: str
    file: str
    line_number: int | None = None
    failure_message: str
    stack_trace: str


class TestSuiteResult(BaseModel):
    __test__ = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    failures: list[TestFailure] = Field(default_factory=list)


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
    """Returns 'pytest', 'vitest', 'jest', 'npm', or None."""
    for indicator in ["pytest.ini", "setup.cfg", "pyproject.toml"]:
        if os.path.exists(os.path.join(workspace_root, indicator)):
            return "pytest"

    for d in ["tests", "test"]:
        if os.path.isdir(os.path.join(workspace_root, d)):
            return "pytest"

    try:
        for f in os.listdir(workspace_root):
            if f.startswith("test_") and f.endswith(".py"):
                return "pytest"
    except Exception:
        pass

    pkg_path = os.path.join(workspace_root, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as fp:
                pkg = json.load(fp)
            scripts = pkg.get("scripts", {})
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "vitest" in deps or "vitest" in scripts.get("test", ""):
                return "vitest"
            if "jest" in deps or "jest" in scripts.get("test", ""):
                return "jest"
            if "test" in scripts and scripts["test"] not in ("", "echo \"Error: no test specified\" && exit 1"):
                return "npm"
        except Exception:
            pass

    return None


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Terminates a process and all its child processes cleanly."""
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
    except Exception:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=5,
                )
            else:
                proc.kill()
        except Exception:
            pass


def parse_junit_xml(xml_content: str, workspace_root: str | None = None) -> TestSuiteResult:
    """Parses JUnit XML string and returns a structured TestSuiteResult."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        return TestSuiteResult(
            passed=0,
            failed=0,
            errors=1,
            duration_seconds=0.0,
            failures=[
                TestFailure(
                    test_name="xml_parse_error",
                    file="",
                    line_number=None,
                    failure_message=f"Failed to parse JUnit XML: {e}",
                    stack_trace="",
                )
            ],
        )

    duration = 0.0
    if "time" in root.attrib:
        try:
            duration = float(root.attrib["time"])
        except (ValueError, TypeError):
            pass
    elif root.tag == "testsuites":
        for ts in root.findall("testsuite"):
            if "time" in ts.attrib:
                try:
                    duration += float(ts.attrib["time"])
                except (ValueError, TypeError):
                    pass

    testcases = root.findall(".//testcase")
    passed = 0
    failed = 0
    errors = 0
    failures: list[TestFailure] = []

    for tc in testcases:
        tc_name = tc.attrib.get("name", "unnamed_test")
        tc_file = tc.attrib.get("file", "")
        tc_line = tc.attrib.get("line")
        line_num = int(tc_line) if tc_line and tc_line.isdigit() else None

        failure_elem = tc.find("failure")
        error_elem = tc.find("error")
        skipped_elem = tc.find("skipped")

        if failure_elem is not None or error_elem is not None:
            elem = failure_elem if failure_elem is not None else error_elem
            if failure_elem is not None:
                failed += 1
            else:
                errors += 1

            fail_msg = elem.attrib.get("message", "").strip()
            stack = (elem.text or "").strip()
            if not fail_msg and stack:
                fail_msg = stack.splitlines()[-1]

            extracted_file = tc_file
            extracted_line = line_num
            if stack:
                match = re.search(r'([^\s:<>"\']+\.(?:py|js|ts|jsx|tsx)):(\d+):', stack)
                if match:
                    if not extracted_file:
                        extracted_file = match.group(1)
                    if extracted_line is None:
                        try:
                            extracted_line = int(match.group(2))
                        except (ValueError, TypeError):
                            pass

            if not extracted_file and tc.attrib.get("classname"):
                extracted_file = tc.attrib.get("classname", "").replace(".", "/") + ".py"

            if extracted_file:
                if workspace_root and os.path.isabs(extracted_file):
                    try:
                        extracted_file = os.path.relpath(extracted_file, workspace_root)
                    except ValueError:
                        pass
                extracted_file = extracted_file.replace("\\", "/")

            failures.append(
                TestFailure(
                    test_name=tc_name,
                    file=extracted_file,
                    line_number=extracted_line,
                    failure_message=fail_msg,
                    stack_trace=stack,
                )
            )
        elif skipped_elem is not None:
            pass
        else:
            passed += 1

    if duration == 0.0:
        for tc in testcases:
            try:
                duration += float(tc.attrib.get("time", 0.0))
            except (ValueError, TypeError):
                pass

    return TestSuiteResult(
        passed=passed,
        failed=failed,
        errors=errors,
        duration_seconds=round(duration, 3),
        failures=failures,
    )


def parse_jest_json(json_content: str, workspace_root: str | None = None) -> TestSuiteResult:
    """Parses Jest / Vitest JSON output string and returns a structured TestSuiteResult."""
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return TestSuiteResult(
            passed=0,
            failed=0,
            errors=1,
            duration_seconds=0.0,
            failures=[
                TestFailure(
                    test_name="json_parse_error",
                    file="",
                    line_number=None,
                    failure_message=f"Failed to parse Jest/Vitest JSON: {e}",
                    stack_trace="",
                )
            ],
        )

    passed = data.get("numPassedTests", 0)
    failed = data.get("numFailedTests", 0)
    errors = data.get("numRuntimeErrorTestSuites", 0)

    start_time = data.get("startTime", 0)
    test_results = data.get("testResults", [])
    duration = 0.0
    if start_time and test_results:
        end_times = [tr.get("endTime", start_time) for tr in test_results]
        max_end = max(end_times) if end_times else start_time
        duration = max(0.0, (max_end - start_time) / 1000.0)

    failures: list[TestFailure] = []
    for tr in test_results:
        suite_file = tr.get("name", "")
        if workspace_root and os.path.isabs(suite_file):
            try:
                suite_file = os.path.relpath(suite_file, workspace_root)
            except ValueError:
                pass
        suite_file = suite_file.replace("\\", "/")

        for ar in tr.get("assertionResults", []):
            if ar.get("status") == "failed":
                t_name = ar.get("title") or ar.get("fullName") or "unnamed_test"
                messages = ar.get("failureMessages", [])
                stack = "\n".join(messages).strip()
                first_line = messages[0].splitlines()[0] if messages and messages[0] else "Assertion failed"

                line_num = None
                if stack:
                    m = re.search(r':(\d+):\d+', stack)
                    if m:
                        try:
                            line_num = int(m.group(1))
                        except (ValueError, TypeError):
                            pass

                failures.append(
                    TestFailure(
                        test_name=t_name,
                        file=suite_file,
                        line_number=line_num,
                        failure_message=first_line,
                        stack_trace=stack,
                    )
                )

    return TestSuiteResult(
        passed=passed,
        failed=failed,
        errors=errors,
        duration_seconds=round(duration, 3),
        failures=failures,
    )


class TestRunner:
    """
    Structured TestRunner for Day 5 (Task 28).
    Supports pytest and Jest/Vitest with machine-readable JUnit XML / JSON output,
    hard 60-second timeouts, and comprehensive child process termination.
    """
    __test__ = False

    def __init__(self, timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def run_tests(
        self,
        workspace_root: str,
        test_path: str | None = None,
        test_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> TestSuiteResult:
        """Alias for run() to match standard calling conventions."""
        return self.run(
            workspace_root=workspace_root,
            test_path=test_path,
            test_filter=test_filter,
            timeout_seconds=timeout_seconds,
        )

    def run(
        self,
        workspace_root: str,
        test_path: str | None = None,
        test_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> TestSuiteResult:
        timeout = timeout_seconds if timeout_seconds is not None else self.timeout_seconds
        runner = _detect_runner(workspace_root)
        if runner is None:
            runner = "pytest"

        temp_dir = tempfile.gettempdir()
        uid = uuid.uuid4().hex[:8]

        xml_path = None
        json_path = None

        if runner == "pytest":
            xml_path = os.path.join(temp_dir, f"junit_{uid}.xml")
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                f"--junitxml={xml_path}",
                "-o",
                "junit_family=xunit2",
                "--tb=short",
                "-q",
            ]
            if test_path:
                cmd.append(test_path)
            if test_filter:
                cmd.extend(["-k", test_filter])
        elif runner in ("jest", "vitest"):
            json_path = os.path.join(temp_dir, f"test_out_{uid}.json")
            tool = "vitest" if runner == "vitest" else "jest"
            if tool == "vitest":
                cmd = ["npx", "vitest", "run", "--reporter=json", f"--outputFile={json_path}"]
            else:
                cmd = ["npx", "jest", "--json", f"--outputFile={json_path}"]
            if test_path:
                cmd.append(test_path)
            if test_filter:
                cmd.extend(["-t", test_filter])
        else:
            cmd = ["npm", "test", "--", "--passWithNoTests"]

        start_time = time.time()
        try:
            use_shell = (os.name == "nt" and cmd[0] not in (sys.executable, "python"))
            proc = subprocess.Popen(
                cmd,
                cwd=workspace_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=use_shell,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc)
                duration = time.time() - start_time
                return TestSuiteResult(
                    passed=0,
                    failed=0,
                    errors=1,
                    duration_seconds=round(duration, 3),
                    failures=[
                        TestFailure(
                            test_name="timeout",
                            file=test_path or "",
                            line_number=None,
                            failure_message=f"Test runner timed out after {timeout}s.",
                            stack_trace="TimeoutExpired: Process terminated and remaining child processes killed.",
                        )
                    ],
                )

            duration = time.time() - start_time

            # 1. Parse JUnit XML if generated
            if xml_path and os.path.exists(xml_path):
                try:
                    with open(xml_path, "r", encoding="utf-8") as f:
                        xml_data = f.read()
                    return parse_junit_xml(xml_data, workspace_root=workspace_root)
                finally:
                    try:
                        os.remove(xml_path)
                    except Exception:
                        pass

            # 2. Parse JSON if generated
            if json_path and os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        json_data = f.read()
                    return parse_jest_json(json_data, workspace_root=workspace_root)
                finally:
                    try:
                        os.remove(json_path)
                    except Exception:
                        pass

            # 3. Fallback when output file was not generated
            if proc.returncode != 0:
                combined_output = (stderr or stdout or "Process exited with error").strip()
                m = re.search(r"(\d+) failed", stdout)
                failed_count = int(m.group(1)) if m else 1
                return TestSuiteResult(
                    passed=0,
                    failed=failed_count,
                    errors=0 if m else 1,
                    duration_seconds=round(duration, 3),
                    failures=[
                        TestFailure(
                            test_name="test_runner_error",
                            file=test_path or "",
                            line_number=None,
                            failure_message=combined_output[:300],
                            stack_trace=combined_output[:2000],
                        )
                    ],
                )

            return TestSuiteResult(
                passed=0,
                failed=0,
                errors=0,
                duration_seconds=round(duration, 3),
                failures=[],
            )

        except Exception as e:
            duration = time.time() - start_time
            return TestSuiteResult(
                passed=0,
                failed=0,
                errors=1,
                duration_seconds=round(duration, 3),
                failures=[
                    TestFailure(
                        test_name="execution_exception",
                        file=test_path or "",
                        line_number=None,
                        failure_message=str(e),
                        stack_trace=str(e),
                    )
                ],
            )


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

    runner_instance = TestRunner(timeout_seconds=TEST_TIMEOUT_SECONDS)
    suite_res = runner_instance.run(workspace_root)
    passed = (suite_res.failed == 0 and suite_res.errors == 0 and suite_res.passed > 0)
    failed_count = suite_res.failed + suite_res.errors

    output_lines = [f"Passed: {suite_res.passed}, Failed: {suite_res.failed}, Errors: {suite_res.errors}"]
    for f in suite_res.failures:
        output_lines.append(f"FAIL: {f.test_name} ({f.file}:{f.line_number}) - {f.failure_message}")
    output = "\n".join(output_lines)

    return TestResult(
        status=TestStatus.PASSED if passed else TestStatus.FAILED,
        runner=runner,
        output=output,
        failed_count=failed_count,
    )
