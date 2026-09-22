"""
Purpose:
Task 38 Tests: Autonomous Dependency Agent.
Verifies AC-E3-D3-02:
1. Executes on 2 seeded dependency findings (pyproject.toml and requirements.txt).
2. Asserts correct version bump in manifests.
3. Asserts breaking changes are identified and code adjustments applied.
4. Asserts test suite passes cleanly post-upgrade.
"""

import os
import tempfile
import pytest

from agents.agent_3.day3_models import DependencyFinding, DependencyPlan
from agents.agent_3.dependency_agent import (
    DependencyAgent,
    DependencyInspector,
    BreakingChangeAnalyzer,
)
from tests.fixtures.day3_fixtures import (
    SEEDED_DEP_FINDING_REQUESTS,
    SEEDED_DEP_FINDING_PYDANTIC,
    setup_dependency_repo_pyproject,
    setup_dependency_repo_breaking_api,
)


def test_dependency_inspector_finds_pyproject_manifest():
    """Verifies that DependencyInspector locates package and version in pyproject.toml."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        files = setup_dependency_repo_pyproject(tmp_dir)
        manifest, ver = DependencyInspector.find_manifest_for_package(tmp_dir, "requests")
        assert manifest == "pyproject.toml"
        assert ver == "2.25.1"


def test_ac_e3_d3_02_dependency_upgrade_requests():
    """
    Verifies AC-E3-D3-02 (Scenario 1):
    Security bump of 'requests' in pyproject.toml from 2.25.1 to 2.31.0 (CVE-2023-32681).
    Version updated in manifest; tests pass cleanly.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        files = setup_dependency_repo_pyproject(tmp_dir)

        # Plan upgrade
        plan = DependencyAgent.plan_upgrade(tmp_dir, SEEDED_DEP_FINDING_REQUESTS)
        assert plan.package == "requests"
        assert plan.old_version == "2.25.1"
        assert plan.new_version == "2.31.0"
        assert plan.manifest_file == "pyproject.toml"

        # Execute upgrade
        success = DependencyAgent.execute_upgrade(tmp_dir, plan)
        assert success is True
        assert plan.status == "VALIDATED"

        # Verify pyproject.toml content was updated
        with open(files["manifest"], "r", encoding="utf-8") as f:
            manifest_content = f.read()
        assert "requests==2.31.0" in manifest_content
        assert "2.25.1" not in manifest_content


def test_ac_e3_d3_02_dependency_upgrade_with_breaking_changes_pydantic():
    """
    Verifies AC-E3-D3-02 (Scenario 2):
    Pydantic V1 -> V2 upgrade with breaking API change (.parse_obj() -> .model_validate()).
    Detects call site, updates requirements.txt, patches call site, and verifies tests pass.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        files = setup_dependency_repo_breaking_api(tmp_dir)

        # Plan upgrade
        plan = DependencyAgent.plan_upgrade(tmp_dir, SEEDED_DEP_FINDING_PYDANTIC)
        assert plan.package == "pydantic"
        assert plan.old_version == "1.8.2"
        assert plan.new_version == "2.4.2"
        assert len(plan.breaking_changes) > 0
        assert any("model_validate" in desc for desc in plan.breaking_changes)
        assert any("src/models/user.py" in site for site in plan.affected_call_sites)

        # Execute upgrade
        success = DependencyAgent.execute_upgrade(tmp_dir, plan)
        assert success is True
        assert plan.status == "VALIDATED"

        # Verify requirements.txt updated
        with open(files["manifest"], "r", encoding="utf-8") as f:
            req_content = f.read()
        assert "pydantic==2.4.2" in req_content

        # Verify source code was patched to use model_validate
        with open(files["source"], "r", encoding="utf-8") as f:
            code_content = f.read()
        assert ".model_validate(" in code_content
        assert ".parse_obj(" not in code_content
