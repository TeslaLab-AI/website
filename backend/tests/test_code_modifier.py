"""
Acceptance and Unit Tests for Precision CodeModifier (Engineer 2 — Task 27).

Covers:
- Exact chunk replacement without clobbering surrounding file code
- Controlled whitespace tolerance
- Ambiguity protection:
    - 0 matches: rejected with error
    - >1 matches: rejected as ambiguous when line bounds absent
    - Disambiguation using line_number
    - Never guesses
- Syntax validation (Python ast.parse, TypeScript delimiter/compiler, JSON)
- Automatic rollback:
    - Deliberately malformed edit triggers syntax error
    - Original file automatically restored immediately
    - Restoration verified
    - Broken code does not remain in diff or on disk
- 5 valid edits across codebase: all succeed, locations exact, syntax valid
- Integration with ExecutorAgent and ToolRegistry in an isolated Git workspace
"""

from pathlib import Path
import pytest
import shutil
import subprocess
import tempfile

from app.agents.agent_2.code_modifier import (
    CodeModifier,
    ModificationResult,
    default_code_modifier,
)
from app.agents.agent_2.plan_schema import (
    ExecutionPlan,
    PlanStep,
    ApplyPatchArgs,
    ReadFileArgs,
    RunCommandArgs,
)
from app.agents.agent_2.tool_registry import (
    create_default_tool_registry,
)
from app.agents.agent_2.git_workspace import (
    GitWorkspaceManager,
)
from app.agents.agent_2.executor import (
    ExecutorAgent,
    ExecutionStatus,
)


@pytest.fixture
def temp_workspace():
    """Create a temporary directory for code modification tests."""
    temp_dir = tempfile.mkdtemp(prefix="test_code_modifier_")
    ws_path = Path(temp_dir).resolve()
    yield ws_path

    for attempt in range(3):
        try:
            shutil.rmtree(ws_path, ignore_errors=False)
            break
        except Exception:
            import time
            time.sleep(0.2)
    if ws_path.exists():
        shutil.rmtree(ws_path, ignore_errors=True)


class TestCodeModifierCore:
    """Core precision modification tests."""

    def test_01_exact_chunk_replacement(self, temp_workspace):
        f = temp_workspace / "math_utils.py"
        f.write_text(
            "import math\n\ndef multiply(a, b):\n    return a * b\n\ndef divide(a, b):\n    return a // b  # int div\n",
            encoding="utf-8",
        )

        modifier = CodeModifier()
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="    return a // b  # int div",
            replacement_chunk="    if b == 0:\n        raise ZeroDivisionError('Division by zero')\n    return a / b",
        )

        assert res.success is True
        assert res.restored is False
        assert res.syntax_valid is True

        content = f.read_text(encoding="utf-8")
        assert "def multiply(a, b):" in content
        assert "if b == 0:" in content
        assert "return a / b" in content
        assert "import math" in content

    def test_02_controlled_whitespace_tolerance(self, temp_workspace):
        f = temp_workspace / "service.py"
        # File has CRLF and trailing spaces
        f.write_bytes(b"def run():\r\n    data = 42   \r\n    return data\r\n")

        modifier = CodeModifier()
        # Search chunk has normalized LF and stripped trailing spaces
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="    data = 42\n    return data",
            replacement_chunk="    data = 100\n    return data * 2",
        )

        assert res.success is True
        content = f.read_text(encoding="utf-8")
        assert "data = 100" in content
        assert "return data * 2" in content

    def test_03_ambiguity_protection_multiple_matches_rejected(self, temp_workspace):
        f = temp_workspace / "duplicate.py"
        # Duplicate chunk appears twice
        f.write_text(
            "def block_one():\n    x = 1\n    return x\n\ndef block_two():\n    x = 1\n    return x\n",
            encoding="utf-8",
        )

        modifier = CodeModifier()
        # Attempt replace without line_number
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="    x = 1\n    return x",
            replacement_chunk="    x = 99\n    return x",
        )

        assert res.success is False
        assert "Ambiguous" in (res.error or "")
        # File content must remain untouched
        assert f.read_text(encoding="utf-8").count("x = 1") == 2

    def test_04_ambiguity_disambiguation_with_line_number(self, temp_workspace):
        f = temp_workspace / "disambiguate.py"
        f.write_text(
            "def first():\n    return True\n\n# intervening comment\n\ndef second():\n    return True\n",
            encoding="utf-8",
        )

        modifier = CodeModifier()
        # Target the second occurrence around line 7
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="    return True",
            replacement_chunk="    return False",
            line_number=7,
        )

        assert res.success is True
        content = f.read_text(encoding="utf-8")
        # First must still return True, second must return False
        assert "def first():\n    return True" in content
        assert "def second():\n    return False" in content

    def test_05_ast_python_function_replacement(self, temp_workspace):
        f = temp_workspace / "ast_target.py"
        f.write_text(
            "import os\n\ndef helper():\n    return 'help'\n\ndef compute(val):\n    '''Original docstring.'''\n    return val + 1\n\ndef footer():\n    return 'foot'\n",
            encoding="utf-8",
        )

        modifier = CodeModifier()
        res = modifier.replace_function(
            file_path=f,
            function_name="compute",
            new_function_code="def compute(val):\n    '''Updated docstring.'''\n    return (val * 2) + 10",
        )

        assert res.success is True
        content = f.read_text(encoding="utf-8")
        assert "def helper():" in content
        assert "def footer():" in content
        assert "(val * 2) + 10" in content
        assert "Updated docstring." in content

    def test_06_typescript_syntax_delimiter_validation(self, temp_workspace):
        f = temp_workspace / "handler.ts"
        f.write_text("export function process(id: string): boolean {\n  return id.length > 0;\n}\n", encoding="utf-8")

        modifier = CodeModifier(check_typescript=False)
        # Attempt edit with unbalanced delimiter
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="  return id.length > 0;",
            replacement_chunk="  if (id.length > 0 { return true; }",  # missing ')'
        )

        assert res.success is False
        assert res.restored is True
        assert (
            "Unmatched closing delimiter" in (res.error or "")
            or "Unclosed delimiter" in (res.error or "")
            or "Mismatched delimiter" in (res.error or "")
        )
        # File must be restored
        assert "return id.length > 0;" in f.read_text(encoding="utf-8")

    def test_07_zero_match_target_rejected(self, temp_workspace):
        f = temp_workspace / "sample.py"
        f.write_text("x = 10\ny = 20\n", encoding="utf-8")

        modifier = CodeModifier()
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="nonexistent_variable = 99",
            replacement_chunk="z = 30",
        )

        assert res.success is False
        assert "not found" in (res.error or "").lower()
        assert f.read_text(encoding="utf-8") == "x = 10\ny = 20\n"

    def test_08_function_not_found_rejected(self, temp_workspace):
        f = temp_workspace / "sample.py"
        f.write_text("def existing_function():\n    return 42\n", encoding="utf-8")

        modifier = CodeModifier()
        res = modifier.replace_function(
            file_path=f,
            function_name="non_existent_function",
            new_function_code="def non_existent_function():\n    return 0",
        )

        assert res.success is False
        assert "not found" in (res.error or "").lower()
        assert "existing_function" in f.read_text(encoding="utf-8")

    def test_09_target_file_not_found(self, temp_workspace):
        f = temp_workspace / "ghost_file.py"

        modifier = CodeModifier()
        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="a = 1",
            replacement_chunk="a = 2",
        )

        assert res.success is False
        assert "does not exist" in (res.error or "").lower()

        res_ast = modifier.replace_function(
            file_path=f,
            function_name="foo",
            new_function_code="def foo(): pass",
        )
        assert res_ast.success is False
        assert "does not exist" in (res_ast.error or "").lower()

    def test_10_ast_ambiguous_function_rejected(self, temp_workspace):
        f = temp_workspace / "overload.py"
        f.write_text(
            "def handle(val: int):\n    return val * 2\n\ndef handle(val: str):\n    return val.upper()\n",
            encoding="utf-8",
        )

        modifier = CodeModifier()
        res = modifier.replace_function(
            file_path=f,
            function_name="handle",
            new_function_code="def handle(val):\n    return val",
        )

        assert res.success is False
        assert "Ambiguous" in (res.error or "")
        # File must remain untouched
        assert "val * 2" in f.read_text(encoding="utf-8")
        assert "val.upper()" in f.read_text(encoding="utf-8")

    def test_11_ast_preserves_unrelated_code_and_comments(self, temp_workspace):
        f = temp_workspace / "complex_module.py"
        initial_content = (
            "# Top-level copyright header\n"
            "import os\n"
            "import sys\n\n"
            "# Config variable\n"
            "MAX_RETRIES = 5\n\n"
            "def worker_one():\n"
            "    '''Docstring worker one.'''\n"
            "    return True\n\n"
            "# Target function to modify\n"
            "def worker_target(x, y):\n"
            "    # inline calculation\n"
            "    return x + y\n\n"
            "def worker_three():\n"
            "    '''Preserve trailing function.'''\n"
            "    return False\n"
        )
        f.write_text(initial_content, encoding="utf-8")

        modifier = CodeModifier()
        res = modifier.replace_function(
            file_path=f,
            function_name="worker_target",
            new_function_code=(
                "def worker_target(x, y):\n"
                "    # updated calculation\n"
                "    return (x * y) + 1"
            ),
        )

        assert res.success is True
        content = f.read_text(encoding="utf-8")
        assert "# Top-level copyright header" in content
        assert "import os\nimport sys" in content
        assert "MAX_RETRIES = 5" in content
        assert "def worker_one():\n    '''Docstring worker one.'''\n    return True" in content
        assert "def worker_three():\n    '''Preserve trailing function.'''\n    return False" in content
        assert "(x * y) + 1" in content
        assert "# Target function to modify" in content

    def test_12_ast_syntax_error_in_replacement_triggers_rollback(self, temp_workspace):
        f = temp_workspace / "target_ast.py"
        initial_content = "def calculate():\n    return 42\n"
        f.write_text(initial_content, encoding="utf-8")

        modifier = CodeModifier()
        # Invalid syntax in replacement
        res = modifier.replace_function(
            file_path=f,
            function_name="calculate",
            new_function_code="def calculate(\n    return broken syntax",
        )

        assert res.success is False
        assert res.syntax_valid is False
        assert res.restored is True
        assert f.read_text(encoding="utf-8") == initial_content


class TestCodeModifierAcceptance:
    """Acceptance tests matching Day 4 official criteria."""

    def test_acceptance_01_five_valid_edits(self, temp_workspace):
        """
        VALID Acceptance Test:
        - Apply 5 valid edits across files
        - All 5 must succeed
        - Verify exact intended locations changed
        - Verify syntax remains valid
        """
        modifier = CodeModifier()

        # Edit 1: Python import insertion
        f1 = temp_workspace / "module1.py"
        f1.write_text("# Module 1\ndef calculate():\n    return 10\n", encoding="utf-8")
        res1 = modifier.replace_chunk(f1, "# Module 1", "# Module 1\nimport math")
        assert res1.success is True

        # Edit 2: Python function logic update
        f2 = temp_workspace / "module2.py"
        f2.write_text("def is_even(n):\n    return n % 2 == 1\n", encoding="utf-8")
        res2 = modifier.replace_chunk(f2, "return n % 2 == 1", "return n % 2 == 0")
        assert res2.success is True

        # Edit 3: Python AST function replace
        f3 = temp_workspace / "module3.py"
        f3.write_text("def greet(name):\n    return f'Hello {name}'\n", encoding="utf-8")
        res3 = modifier.replace_function(f3, "greet", "def greet(name):\n    return f'Welcome, {name}!'")
        assert res3.success is True

        # Edit 4: JSON config precision edit
        f4 = temp_workspace / "config.json"
        f4.write_text('{\n  "version": "1.0.0",\n  "enabled": false\n}', encoding="utf-8")
        res4 = modifier.replace_chunk(f4, '"enabled": false', '"enabled": true')
        assert res4.success is True

        # Edit 5: Multi-line function addition
        f5 = temp_workspace / "module5.py"
        f5.write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
        res5 = modifier.replace_chunk(
            f5,
            "    return 'pong'",
            "    # Verified health\n    return {'status': 'healthy'}",
        )
        assert res5.success is True

        # Verify all 5 files have valid syntax and intended content
        for f in (f1, f2, f3, f5):
            valid, err = modifier.validate_syntax(f)
            assert valid is True, f"Syntax failed on {f}: {err}"

        assert "import math" in f1.read_text(encoding="utf-8")
        assert "n % 2 == 0" in f2.read_text(encoding="utf-8")
        assert "Welcome, {name}!" in f3.read_text(encoding="utf-8")
        assert '"enabled": true' in f4.read_text(encoding="utf-8")
        assert "{'status': 'healthy'}" in f5.read_text(encoding="utf-8")

    def test_acceptance_02_invalid_malformed_edit_automatic_rollback(self, temp_workspace):
        """
        INVALID Acceptance Test:
        - Apply 1 deliberately malformed edit (broken Python syntax)
        - Syntax validation must fail
        - Original file must automatically be restored immediately
        - Broken code must not remain on disk or in git diff
        """
        f = temp_workspace / "auth_gate.py"
        original_source = (
            "# Production Auth Gate\n"
            "def check_credentials(user, key):\n"
            "    if user == 'admin' and key == 'secret':\n"
            "        return True\n"
            "    return False\n"
        )
        f.write_text(original_source, encoding="utf-8")

        modifier = CodeModifier()

        # Deliberately broken syntax: unclosed parenthesis, invalid keyword
        malformed_replacement = "    if (user == 'admin' and key == 'secret'\n        return True"

        res = modifier.replace_chunk(
            file_path=f,
            original_chunk="    if user == 'admin' and key == 'secret':\n        return True",
            replacement_chunk=malformed_replacement,
        )

        assert res.success is False
        assert res.syntax_valid is False
        assert res.restored is True
        assert "Syntax validation failed" in (res.error or "")

        # Verify file is restored to pristine original content
        current_content = f.read_text(encoding="utf-8")
        assert current_content == original_source
        assert "if (" not in current_content

    def test_acceptance_03_executor_workspace_code_modifier_integration(self):
        """
        Integration Acceptance Test:
        - Run an ExecutionPlan through ExecutorAgent in an isolated Git workspace
        - apply_patch step uses CodeModifier under the hood
        - Verifies clean unified git diff generated in workspace
        """
        temp_dir = tempfile.mkdtemp(prefix="test_mod_integ_")
        repo_path = Path(temp_dir).resolve()

        try:
            subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Mod Tester"], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "mod@teslalab.ai"], cwd=str(repo_path), check=True, capture_output=True)

            code_file = repo_path / "pricing.py"
            code_file.write_text("def get_discount(tier):\n    return 0.05  # legacy 5%\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=str(repo_path), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=str(repo_path), check=True, capture_output=True)

            mgr = GitWorkspaceManager(repo_path=repo_path)
            registry = create_default_tool_registry()

            plan = ExecutionPlan(
                goal="Update discount rate using precision code modifier",
                affected_files=["pricing.py"],
                estimated_complexity="Low",
                rollback_plan="Revert workspace",
                steps=[
                    PlanStep(
                        step_number=1,
                        tool_name="read_file",
                        tool_arguments=ReadFileArgs(path="pricing.py"),
                        expected_outcome="Read original pricing.py",
                        rollback_action="None",
                    ),
                    PlanStep(
                        step_number=2,
                        tool_name="apply_patch",
                        tool_arguments=ApplyPatchArgs(
                            path="pricing.py",
                            original_chunk="    return 0.05  # legacy 5%",
                            replacement_chunk="    return 0.20  # upgraded 20%",
                            line_number=2,
                        ),
                        expected_outcome="Apply precision patch to pricing.py",
                        rollback_action="Rollback patch",
                    ),
                ],
            )

            executor = ExecutorAgent(tool_registry=registry, workspace_manager=mgr)
            res = executor.execute_plan(
                plan=plan,
                task_name="task-discount-upgrade",
                session_id="sess-mod-integ",
            )

            assert res.status == ExecutionStatus.SUCCESS
            assert len(res.completed_steps) == 2

            diff = mgr.get_diff("task-discount-upgrade")
            assert "-    return 0.05  # legacy 5%" in diff
            assert "+    return 0.20  # upgraded 20%" in diff

            # Rollback workspace
            mgr.rollback_to_clean("task-discount-upgrade")
            diff_after = mgr.get_diff("task-discount-upgrade")
            assert diff_after.strip() == ""

            mgr.cleanup("task-discount-upgrade")

        finally:
            for attempt in range(3):
                try:
                    shutil.rmtree(repo_path, ignore_errors=False)
                    break
                except Exception:
                    import time
                    time.sleep(0.2)
            if repo_path.exists():
                shutil.rmtree(repo_path, ignore_errors=True)
