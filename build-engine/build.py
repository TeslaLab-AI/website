"""Plan-driven file generation, bounded build repair, and preview callback."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import object_session

from llm import complete
from models.project import Project, ProjectStatus, allowed_transition
from plan import File as PlanFile, Plan
import sandbox

ROOT = Path(__file__).parent
MAX_ATTEMPTS = 5


def _append_event(project: Project, stage: str, message: str) -> None:
    history = dict(project.history or {})
    events = list(history.get("events", []))
    events.append({"ts": datetime.now(timezone.utc).isoformat(), "stage": stage, "message": message})
    history["events"] = events
    project.history = history
    if isinstance(project, Project):
        session = object_session(project)
        if session is not None:
            session.commit()


def _set_status(project: Project, target: ProjectStatus) -> None:
    current = ProjectStatus(project.status)
    if current != target and allowed_transition(current, target):
        project.status = target


def _generated_context(entry: PlanFile, generated: dict[str, str]) -> dict[str, str]:
    purpose = entry.purpose.lower()
    return {
        path: content for path, content in generated.items()
        if Path(path).name.lower() in purpose or Path(path).stem.lower() in purpose
    }


def generate_files(plan: Plan, tenant_id: str, project_id: str) -> None:
    """Copy the prepared app template and generate each Plan-listed file."""
    template = ROOT / "templates" / "base"
    if not (template / "node_modules").is_dir():
        raise RuntimeError("base template dependencies are missing; run npm install --prefix templates/base")
    project_dir = sandbox._project_dir(tenant_id, project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, project_dir, dirs_exist_ok=True)
    system = (ROOT / "prompts" / "code.v1.md").read_text(encoding="utf-8")
    generated: dict[str, str] = {}
    entries = [item.model_dump() for item in plan.files]
    for entry in plan.files:
        path = sandbox.validate_relative_path(entry.path)
        user = json.dumps({
            "plan": plan.model_dump(),
            "files": entries,
            "current_file": entry.model_dump(),
            "already_generated_imports": _generated_context(entry, generated),
        })
        content = complete(system, user)
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"model returned empty content for {path}")
        target = sandbox._resolve(tenant_id, project_id, path)
        if target.exists():
            sandbox.modify_file(tenant_id, project_id, path, content)
        else:
            sandbox.create_file(tenant_id, project_id, path, content)
        generated[path] = content


def _result_error(result: sandbox.RunResult) -> tuple[str, str, list[str], str]:
    lines = (result.stderr or result.stdout).splitlines()
    first_line = next((line.strip() for line in lines if line.strip()), "command failed")
    files = []
    for match in re.findall(r"(?:^|\s)([\w./-]+\.(?:tsx|ts|jsx|js|css|json))(?::\d+)?", "\n".join(lines)):
        path = match.removeprefix("./")
        if path not in files:
            files.append(path)
    signature = f"{files[0] if files else 'unknown'}:{first_line}"
    return signature, first_line, files, "\n".join(lines)


def _fix_files(tenant_id: str, project_id: str, files: list[str], error: str) -> bool:
    selected = {}
    for candidate in files:
        try:
            path = sandbox.validate_relative_path(candidate)
        except ValueError:
            continue
        target = sandbox._resolve(tenant_id, project_id, path)
        if target.is_file():
            selected[path] = target.read_text(encoding="utf-8")
    if not selected:
        return False
    system = (ROOT / "prompts" / "fix.v1.md").read_text(encoding="utf-8")
    response = complete(system, json.dumps({"error": error, "files": selected}), json_mode=True)
    replacements = json.loads(response)
    if not isinstance(replacements, dict) or not replacements or not set(replacements) <= set(selected):
        raise ValueError("fix response must map only affected files to replacement contents")
    for path, content in replacements.items():
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"fix response has invalid content for {path}")
        sandbox.modify_file(tenant_id, project_id, sandbox.validate_relative_path(path), content)
    return True


def _build_once(project: Project) -> sandbox.RunResult:
    tenant_id, project_id = project.tenant_id, project.id
    package_path = "package.json"
    package_file = sandbox._resolve(tenant_id, project_id, package_path)
    if package_file.exists():
        package_hash = hashlib.sha256(package_file.read_bytes()).hexdigest()
        base_package = (ROOT / "templates" / "base" / package_path).read_bytes()
        baseline_hash = hashlib.sha256(base_package).hexdigest()
        maintenance = dict(project.maintenance or {})
        prior_hash = maintenance.get("package_hash", baseline_hash)
        if package_hash != prior_hash:
            install = sandbox.run_command(tenant_id, project_id, ["npm", "install"], network=True, timeout_s=600)
            if not install.ok:
                return install
            maintenance["package_hash"] = package_hash
            project.maintenance = maintenance
            _append_event(project, "install", "Installed changed package.json dependencies")
    return sandbox.run_command(tenant_id, project_id, ["npm", "run", "build"], timeout_s=600)


def build_loop(project: Project) -> bool:
    """Build at most five times, stopping after success or a repeated error."""
    _set_status(project, ProjectStatus.BUILDING)
    _append_event(project, "build", "Build started")
    previous_signature = None
    last_result = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        last_result = _build_once(project)
        if last_result.ok:
            _set_status(project, ProjectStatus.READY)
            _append_event(project, "build", f"Build succeeded on attempt {attempt}")
            return True
        signature, first_line, files, full_error = _result_error(last_result)
        _append_event(project, "build", f"Attempt {attempt} failed: {first_line}")
        if signature == previous_signature or attempt == MAX_ATTEMPTS:
            break
        previous_signature = signature
        _append_event(project, "fix", f"Repairing {len(files)} affected file(s)")
        if not _fix_files(project.tenant_id, project.id, files, full_error):
            break
    _set_status(project, ProjectStatus.ERROR)
    maintenance = dict(project.maintenance or {})
    maintenance["last_error"] = dataclasses.asdict(last_result)
    project.maintenance = maintenance
    _append_event(project, "build", "Build failed after bounded repair attempts")
    return False


def _default_preview_hook(tenant_id: str, project_id: str, upstream_url: str) -> str:
    return upstream_url


on_preview_ready: Callable[[str, str, str], str] = _default_preview_hook
