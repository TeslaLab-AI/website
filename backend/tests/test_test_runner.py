"""
Purpose:
Deterministic tests for Day 5 Task 28: Structured TestRunner.

Verifies:
1. 8 passing + 2 failing tests (exact counts, test_names, files, line_numbers, messages, stack traces)
2. Completely passing suite (exact counts, zero failures)
3. Timeout/hanging test (hard timeout, process & child termination, error result, never passing)
4. Structured parsing of JUnit XML and Jest/Vitest JSON failure details
"""

import os
import tempfile
import time
import pytest

from app.agents.tester import (
    TestRunner,
    TestSuiteResult,
    TestFailure,
    parse_junit_xml,
    parse_jest_json,
)


def test_suite_8_passing_2_failing():
    """
    Deterministic test 1:
    Suite containing exactly 8 passing tests and 2 failing tests.
    Verifies exact passed, failed, errors, duration, failure details.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "test_mixed.py")
        content = """# 8 passing tests
def test_pass_1():
    assert 1 == 1

def test_pass_2():
    assert 2 == 2

def test_pass_3():
    assert 3 == 3

def test_pass_4():
    assert 4 == 4

def test_pass_5():
    assert 5 == 5

def test_pass_6():
    assert 6 == 6

def test_pass_7():
    assert 7 == 7

def test_pass_8():
    assert 8 == 8

# 2 failing tests with known assertions
def test_fail_alpha():
    expected = 100
    actual = 99
    assert actual == expected, "Alpha mismatch"

def test_fail_beta():
    assert False, "Beta failure occurred"
"""
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(content)

        runner = TestRunner(timeout_seconds=30.0)
        result = runner.run(workspace_root=tmp_dir, test_path="test_mixed.py")

        # 1. Exact counts
        assert result.passed == 8, f"Expected 8 passed, got {result.passed}"
        assert result.failed == 2, f"Expected 2 failed, got {result.failed}"
        assert result.errors == 0, f"Expected 0 errors, got {result.errors}"
        assert result.duration_seconds > 0.0, f"Expected positive duration, got {result.duration_seconds}"
        assert len(result.failures) == 2, f"Expected 2 failure records, got {len(result.failures)}"

        # 2. Failure specifics
        fail_map = {f.test_name: f for f in result.failures}
        assert "test_fail_alpha" in fail_map, "Missing test_fail_alpha failure"
        assert "test_fail_beta" in fail_map, "Missing test_fail_beta failure"

        alpha = fail_map["test_fail_alpha"]
        assert alpha.test_name == "test_fail_alpha"
        assert "test_mixed.py" in alpha.file
        assert alpha.line_number is not None
        assert "Alpha mismatch" in alpha.failure_message or "assert 99 == 100" in alpha.failure_message
        assert "AssertionError" in alpha.stack_trace

        beta = fail_map["test_fail_beta"]
        assert beta.test_name == "test_fail_beta"
        assert "test_mixed.py" in beta.file
        assert beta.line_number is not None
        assert "Beta failure occurred" in beta.failure_message or "assert False" in beta.failure_message
        assert "AssertionError" in beta.stack_trace


def test_suite_completely_passing():
    """
    Deterministic test 2:
    Completely passing test suite (5 passing tests).
    Verifies exact counts: passed=5, failed=0, errors=0, failures=[].
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "test_clean.py")
        content = """def test_item_one():
    assert True

def test_item_two():
    assert "hello".upper() == "HELLO"

def test_item_three():
    assert len([1, 2, 3]) == 3

def test_item_four():
    assert sum([10, 20]) == 30

def test_item_five():
    assert isinstance(42, int)
"""
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(content)

        runner = TestRunner(timeout_seconds=30.0)
        result = runner.run(workspace_root=tmp_dir, test_path="test_clean.py")

        assert result.passed == 5, f"Expected 5 passed, got {result.passed}"
        assert result.failed == 0, f"Expected 0 failed, got {result.failed}"
        assert result.errors == 0, f"Expected 0 errors, got {result.errors}"
        assert result.duration_seconds > 0.0
        assert len(result.failures) == 0, f"Expected 0 failures, got {result.failures}"


def test_suite_timeout_hanging_test():
    """
    Deterministic test 3:
    Hanging test that triggers hard timeout.
    Verifies:
    - Process and child processes are terminated
    - Structured timeout result returned
    - Never reported as passing
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = os.path.join(tmp_dir, "test_hanging.py")
        content = """import time

def test_hang():
    time.sleep(15)
    assert True
"""
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(content)

        # Set a short 2.0-second timeout for fast deterministic testing
        runner = TestRunner(timeout_seconds=2.0)
        start_time = time.time()
        result = runner.run(workspace_root=tmp_dir, test_path="test_hanging.py")
        elapsed = time.time() - start_time

        # Verifications
        assert elapsed >= 1.8, f"Should have waited for timeout, elapsed: {elapsed}"
        assert elapsed < 10.0, f"Should have terminated promptly after timeout, elapsed: {elapsed}"
        assert result.passed == 0, "Timed out suite must never report passed > 0"
        assert result.errors >= 1, "Timed out suite must report error"
        assert len(result.failures) == 1
        assert result.failures[0].test_name == "timeout"
        assert "timed out" in result.failures[0].failure_message.lower()
        assert "timeoutexpired" in result.failures[0].stack_trace.lower()


def test_parsing_junit_xml_details():
    """
    Deterministic test 4A:
    Verify exact parsing of JUnit XML failure details including
    passed, failed, errors, duration, test_name, file, line_number, failure_message, stack_trace.
    """
    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="0" failures="1" skipped="1" tests="3" time="1.452">
    <testcase classname="tests.test_auth" name="test_login_success" time="0.100" />
    <testcase classname="tests.test_auth" name="test_login_skipped" time="0.000">
      <skipped message="skip for now" />
    </testcase>
    <testcase classname="tests.test_auth" name="test_login_invalid_password" file="tests/test_auth.py" line="42" time="0.352">
      <failure message="assert 401 == 200">def test_login_invalid_password():
&gt;       assert response.status_code == 200
E       assert 401 == 200

tests/test_auth.py:42: AssertionError</failure>
    </testcase>
  </testsuite>
</testsuites>"""

    result = parse_junit_xml(sample_xml)
    assert result.passed == 1
    assert result.failed == 1
    assert result.errors == 0
    assert result.duration_seconds == 1.452
    assert len(result.failures) == 1

    failure = result.failures[0]
    assert failure.test_name == "test_login_invalid_password"
    assert failure.file == "tests/test_auth.py"
    assert failure.line_number == 42
    assert failure.failure_message == "assert 401 == 200"
    assert "AssertionError" in failure.stack_trace
    assert "tests/test_auth.py:42" in failure.stack_trace


def test_parsing_jest_vitest_json_details():
    """
    Deterministic test 4B:
    Verify exact parsing of Jest / Vitest JSON failure details.
    """
    sample_json = """{
  "numPassedTests": 8,
  "numFailedTests": 2,
  "numTotalTests": 10,
  "numRuntimeErrorTestSuites": 0,
  "startTime": 1700000000000,
  "testResults": [
    {
      "name": "src/__tests__/checkout.test.js",
      "startTime": 1700000000000,
      "endTime": 1700000001500,
      "assertionResults": [
        {
          "title": "applies coupon discount",
          "fullName": "Checkout applies coupon discount",
          "status": "passed",
          "duration": 15
        },
        {
          "title": "calculates tax rate",
          "fullName": "Checkout calculates tax rate",
          "status": "failed",
          "duration": 25,
          "failureMessages": [
            "Error: expect(received).toBe(expected) // Object.is equality\\n\\nExpected: 15.0\\nReceived: 0.0\\n    at Object.<anonymous> (src/__tests__/checkout.test.js:68:20)"
          ]
        }
      ]
    }
  ]
}"""

    result = parse_jest_json(sample_json)
    assert result.passed == 8
    assert result.failed == 2
    assert result.errors == 0
    assert result.duration_seconds == 1.5
    assert len(result.failures) == 1

    failure = result.failures[0]
    assert failure.test_name == "calculates tax rate"
    assert failure.file == "src/__tests__/checkout.test.js"
    assert failure.line_number == 68
    assert "expect(received).toBe(expected)" in failure.failure_message
    assert "Object.is equality" in failure.stack_trace
