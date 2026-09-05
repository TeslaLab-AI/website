"""
Purpose:
Pipeline Orchestrator — runs the full multi-agent fix pipeline for a single finding.

Flow:
  1. Triage Agents (parallel)  →  3 analyses
  2. Normalizer                →  NormalizedTask
  3. Planner Agent             →  FixPlan
  4. Workspace Isolation       →  IsolatedWorkspace
  5. Executor                  →  Apply FixPlan steps
  6. Testing Agent             →  TestResult
  7. Security Verifier         →  VerifyResult
  8a. FAIL                     →  Replanner (max MAX_ATTEMPTS total)
  8b. PASS                     →  Commit to branch + open PR

Max attempts: 3
"""

from __future__ import annotations
import base64
import json
import os
import uuid

from app.agents import event_bus
from app.agents.triage_agents import run_triage_agents
from app.agents.normalizer import normalize
from app.agents.planner import plan, PlannerInput, MAX_ATTEMPTS
from app.agents.sandbox import create_workspace
from app.agents.executor import execute_plan
from app.agents.tester import run_tests, TestStatus
from app.agents.verifier import verify_fix
from app.agents.sandbox import IsolatedWorkspace

from app.github_api import _json_request, _json_post, get_workspace_installation, get_installation_token
from app.config import supabase_url, supabase_service_role_key
from app.ingestion.github_downloader import download_and_extract_repo


def _github_request(url: str, token: str, method: str = "GET", payload: dict | None = None):
    """Local GitHub API helper."""
    import urllib.request
    import urllib.error

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "TeslaLab-Security-Scanner",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            return e.code, json.loads(body) if body else {}
        except Exception:
            return e.code, {}
    except Exception as ex:
        print(f"GitHub request error: {ex}")
        return 500, {}


def run_pipeline(
    run_id: str,
    finding: dict,
    repo: dict,
    workspace_id: str,
) -> None:
    """
    Full agentic fix pipeline. Runs in a background thread.
    Updates event_bus state throughout.
    """
    bus = event_bus  # alias for readability

    try:
        # ── 0. Setup ──────────────────────────────────────────────
        owner = repo["owner"]
        name = repo["name"]
        branch = repo["default_branch"]

        installation = get_workspace_installation(workspace_id)
        if not installation:
            bus.fail_run(run_id, "No GitHub installation found.")
            return

        token = get_installation_token(installation["github_installation_id"])

        # ── 1. Fetch file content from GitHub ─────────────────────
        bus.update_phase(run_id, "triage", f"Fetching {finding['file_path']} from GitHub...")
        c_status, c_body = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/contents/{finding['file_path']}",
            token,
        )
        if c_status != 200 or "content" not in c_body:
            bus.fail_run(run_id, f"Could not fetch file: {finding['file_path']}")
            return

        file_content = base64.b64decode(c_body["content"]).decode("utf-8")
        blob_sha = c_body["sha"]

        # ── 2. Triage Agents ──────────────────────────────────────
        bus.update_phase(run_id, "triage", "Running triage agents (Bug, Security, Dependency)...")
        triage_results = run_triage_agents(finding, file_content)
        bus.update_phase(run_id, "triage", f"Triage complete. {len(triage_results)} agents responded.")

        # ── 3. Normalize ──────────────────────────────────────────
        bus.update_phase(run_id, "normalize", "Normalizing triage outputs...")
        task = normalize(finding, triage_results)
        bus.update_phase(run_id, "normalize", f"Primary agent: {task.primary_agent}. Risk: {task.risk}.")

        # ── 4. Download repo for workspace isolation ───────────────
        bus.update_phase(run_id, "plan", "Downloading repository for workspace isolation...")
        repo_root = download_and_extract_repo(owner, name, token, branch)

        # ── 5. Plan → Execute → Test → Verify loop ────────────────
        # ── 4b. Find nearest package manifest (package.json, requirements.txt, etc.)
        from app.agents.tester import _find_nearest_file
        manifest_path = None
        manifest_content = None
        target_dir = os.path.dirname(os.path.join(repo_root, finding["file_path"]))
        for m_name in ["package.json", "requirements.txt", "pyproject.toml"]:
            m_abs = _find_nearest_file(target_dir, repo_root, m_name)
            if m_abs and os.path.isfile(m_abs):
                manifest_path = os.path.relpath(m_abs, repo_root).replace("\\", "/")
                try:
                    with open(m_abs, "r", encoding="utf-8", errors="ignore") as mf:
                        manifest_content = mf.read()
                except Exception:
                    pass
                break

        # ── 5. Plan → Execute → Test → Verify loop ────────────────
        previous_attempts: list[dict] = []
        final_plan = None
        final_test = None
        final_verify = None
        workspace: IsolatedWorkspace | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            event_bus.increment_attempt(run_id)
            bus.update_phase(run_id, "plan", f"Planner generating fix plan (attempt {attempt}/{MAX_ATTEMPTS})...")

            planner_input = PlannerInput(
                task=task,
                file_content=file_content,
                previous_attempts=previous_attempts,
                manifest_path=manifest_path,
                manifest_content=manifest_content,
            )
            final_plan = plan(planner_input)
            bus.update_phase(run_id, "plan", f"Plan ready: {final_plan.explanation[:120]}...")

            # Create fresh isolated workspace for each attempt
            if workspace:
                workspace.cleanup()
            workspace = create_workspace(repo_root, name)

            # Execute
            bus.update_phase(run_id, "execute", f"Applying {len(final_plan.steps)} fix step(s)...")
            exec_result = execute_plan(final_plan, workspace)
            if not exec_result.success:
                bus.update_phase(run_id, "execute", f"Executor errors: {exec_result.errors}")

            # Test
            bus.update_phase(run_id, "test", "Running test suite...")
            final_test = run_tests(workspace.root, changed_files=exec_result.changed_files)
            bus.update_phase(run_id, "test", f"Test result: {final_test.status.value} (runner: {final_test.runner})")

            # Verify
            bus.update_phase(run_id, "verify", "Running Semgrep security verification...")
            final_verify = verify_fix(
                workspace_root=workspace.root,
                changed_files=exec_result.changed_files,
                original_finding_title=finding["title"],
                original_file_path=finding["file_path"],
                original_line=finding.get("line_number", 0),
            )
            bus.update_phase(run_id, "verify", f"Verify result: {'PASS' if final_verify.passed else 'FAIL'}. Resolved: {final_verify.resolved_findings}. New issues: {final_verify.new_findings}")

            # PASS criteria: tests pass (or no tests) AND verification passes
            test_ok = final_test.status in (TestStatus.PASSED, TestStatus.PASS_WITHOUT_TESTS)
            verify_ok = final_verify.passed

            if test_ok and verify_ok:
                bus.update_phase(run_id, "verify", f"✅ Attempt {attempt} PASSED. Proceeding to PR creation.")
                break

            # FAIL — record this attempt for the replanner
            previous_attempts.append({
                "plan_explanation": final_plan.explanation,
                "test_result": f"{final_test.status.value}: {final_test.output[:500]}",
                "verify_result": f"Resolved={final_verify.resolved_findings}, Remaining={final_verify.remaining_findings}, New={final_verify.new_findings}",
            })

            if attempt == MAX_ATTEMPTS:
                bus.fail_run(run_id, f"All {MAX_ATTEMPTS} attempts failed. Last test: {final_test.status.value}. Last verify passed: {final_verify.passed}.")
                if workspace:
                    workspace.cleanup()
                return

        # ── 6. Commit changes to a new branch ─────────────────────
        bus.update_phase(run_id, "pr", "Creating branch and committing fix...")
        branch_name = f"teslalab-agentic-fix-{uuid.uuid4().hex[:8]}"

        ref_status, ref_body = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/git/ref/heads/{branch}", token
        )
        if ref_status != 200:
            bus.fail_run(run_id, f"Failed to get branch ref: {ref_status}")
            return
        base_sha = ref_body["object"]["sha"]

        b_status, _ = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/git/refs",
            token, method="POST",
            payload={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
        )
        if b_status != 201:
            bus.fail_run(run_id, f"Failed to create branch: {b_status}")
            return

        # Commit each changed file
        for step in final_plan.steps:
            if step.action in ("MODIFY", "CREATE") and step.content:
                abs_path = workspace.resolve(step.file_path)
                if not os.path.exists(abs_path):
                    continue

                # Get current blob SHA for the file (needed for update)
                fc_status, fc_body = _github_request(
                    f"https://api.github.com/repos/{owner}/{name}/contents/{step.file_path}",
                    token,
                )
                current_sha = fc_body.get("sha", blob_sha) if fc_status == 200 else blob_sha

                _github_request(
                    f"https://api.github.com/repos/{owner}/{name}/contents/{step.file_path}",
                    token, method="PUT",
                    payload={
                        "message": f"fix: {finding['title']} [{step.file_path}]",
                        "content": base64.b64encode(step.content.encode("utf-8")).decode("utf-8"),
                        "sha": current_sha,
                        "branch": branch_name,
                    },
                )

        # ── 7. Open PR ─────────────────────────────────────────────
        bus.update_phase(run_id, "pr", "Opening Pull Request...")

        # Build PR description with full agent trace
        test_summary = f"{final_test.status.value} ({final_test.runner})"
        verify_summary = (
            f"Resolved: {final_verify.resolved_findings or 'none'}, "
            f"New issues: {final_verify.new_findings or 'none'}"
        )
        attempts_made = event_bus.get_run(run_id)["attempts"]

        pr_body = (
            f"### 🤖 Automated Fix by TeslaLab Agentic Pipeline\n\n"
            f"**Finding**: {finding['title']}\n"
            f"**Severity**: {finding['severity'].upper()}\n"
            f"**File**: `{finding['file_path']}`\n\n"
            f"---\n\n"
            f"### Agent Plan\n{final_plan.explanation}\n\n"
            f"### Test Results\n`{test_summary}`\n\n"
            f"```\n{final_test.output[:800]}\n```\n\n"
            f"### Security Verification\n`{verify_summary}`\n\n"
            f"### Attempts\n{attempts_made} / {MAX_ATTEMPTS}\n"
        )

        p_status, p_body_resp = _github_request(
            f"https://api.github.com/repos/{owner}/{name}/pulls",
            token, method="POST",
            payload={
                "title": f"🤖 Agentic Fix: {finding['title']}",
                "head": branch_name,
                "base": branch,
                "body": pr_body,
            },
        )

        if p_status == 403:
            compare_url = f"https://github.com/{owner}/{name}/compare/{branch}...{branch_name}?expand=1"
            bus.fail_run(
                run_id,
                f"Fix was verified and committed to branch '{branch_name}'! "
                f"However, GitHub denied automatic PR creation (403) because the App lacks 'Pull requests: Read and write' permission. "
                f"Review & open PR manually: {compare_url}"
            )
            return

        if p_status == 422:
            # PR already exists — fetch it
            ls, lb = _github_request(
                f"https://api.github.com/repos/{owner}/{name}/pulls?head={owner}:{branch_name}&base={branch}&state=open",
                token,
            )
            pr_url = lb[0]["html_url"] if ls == 200 and lb else "https://github.com"
        elif p_status == 201:
            pr_url = p_body_resp["html_url"]
        else:
            bus.fail_run(run_id, f"Failed to create PR: {p_status} — {p_body_resp}")
            return

        # ── 8. Cleanup and complete ────────────────────────────────
        if workspace:
            workspace.cleanup()

        bus.complete_run(run_id, {
            "pr_url": pr_url,
            "plan": final_plan.explanation,
            "test_result": test_summary,
            "verify_result": verify_summary,
            "attempts": attempts_made,
        })

    except Exception as e:
        import traceback
        bus.fail_run(run_id, f"Pipeline error: {e}\n{traceback.format_exc()[:1000]}")
