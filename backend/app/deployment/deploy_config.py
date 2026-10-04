"""Generate and validate deploy.json (how to install, build and run a project).

deploy.json is read by other engines, so it is strictly validated:
- Commands are built from fixed templates. Only script NAMES are used, never
  the text of package.json scripts, so a malicious script cannot reach a shell
  through this file.
- The output directory must be a safe relative path.
- Only environment variable NAMES are stored, never values.

CLI:  python -m app.deployment.deploy_config <project_dir> [--write]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from .env_detector import detect_env_vars

SCHEMA_VERSION = 1
FRAMEWORK_NEXTJS = "nextjs"

# Verify these against your sandbox image and Vercel's supported runtimes.
SUPPORTED_NODE_MAJORS = ("20", "22", "24")
DEFAULT_NODE_MAJOR = "22"

ALLOWED_INSTALL = {
    "npm ci",
    "npm install",
    "pnpm install --frozen-lockfile",
    "yarn install --frozen-lockfile",
}
_RUN_COMMAND = re.compile(r"^((npm|pnpm) run|yarn) [A-Za-z0-9:_-]+$|^npx next (build|start)$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIELDS = (
    "schema_version", "framework", "node_version", "install_command",
    "build_command", "start_command", "output_directory", "required_env", "database",
)

SUPABASE_ENV = ("NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY")


class DeployConfigError(Exception):
    """deploy.json could not be generated or is invalid."""


class UnsupportedFrameworkError(DeployConfigError):
    """Only Next.js projects are supported in Stage 1."""


def _safe_relative_dir(path: str) -> bool:
    if not path or "\\" in path or re.match(r"^[A-Za-z]:", path):
        return False
    parts = PurePosixPath(path).parts
    return not path.startswith("/") and ".." not in parts and len(parts) > 0


@dataclass(frozen=True)
class DeployConfig:
    framework: str
    node_version: str
    install_command: str
    build_command: str
    start_command: str  # "" for static exports (nothing to start)
    output_directory: str
    required_env: tuple[str, ...]
    database: bool
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise DeployConfigError(f"Unsupported schema_version: {self.schema_version}")
        if self.framework != FRAMEWORK_NEXTJS:
            raise UnsupportedFrameworkError(f"Unsupported framework: {self.framework}")
        if self.node_version not in SUPPORTED_NODE_MAJORS:
            raise DeployConfigError(f"Unsupported node_version: {self.node_version}")
        if self.install_command not in ALLOWED_INSTALL:
            raise DeployConfigError("install_command is not an allowed command")
        if not _RUN_COMMAND.match(self.build_command):
            raise DeployConfigError("build_command is not an allowed command")
        if self.start_command and not _RUN_COMMAND.match(self.start_command):
            raise DeployConfigError("start_command is not an allowed command")
        if not _safe_relative_dir(self.output_directory):
            raise DeployConfigError("output_directory must be a safe relative path")
        if not isinstance(self.database, bool):
            raise DeployConfigError("database must be true or false")
        if len(set(self.required_env)) != len(self.required_env):
            raise DeployConfigError("required_env contains duplicates")
        for name in self.required_env:
            if not isinstance(name, str) or not _ENV_NAME.match(name):
                raise DeployConfigError("required_env contains an invalid variable name")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["required_env"] = list(self.required_env)
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class GenerationResult:
    config: DeployConfig
    warnings: tuple[str, ...]


def parse_deploy_config(data: Mapping) -> DeployConfig:
    """Strictly validate data loaded from a deploy.json file."""
    if not isinstance(data, Mapping):
        raise DeployConfigError("deploy.json must contain a JSON object")
    unknown = set(data) - set(_FIELDS)
    missing = set(_FIELDS) - set(data)
    if unknown:
        raise DeployConfigError(f"Unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise DeployConfigError(f"Missing fields: {', '.join(sorted(missing))}")
    env = data["required_env"]
    if not isinstance(env, list):
        raise DeployConfigError("required_env must be a list")
    for key in ("framework", "node_version", "install_command", "build_command",
                "start_command", "output_directory"):
        if not isinstance(data[key], str):
            raise DeployConfigError(f"{key} must be a string")
    return DeployConfig(**{**data, "required_env": tuple(env)})


def load_deploy_json(path: str | Path) -> DeployConfig:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployConfigError(f"Cannot read deploy.json: {exc.__class__.__name__}") from None
    return parse_deploy_config(data)


def write_deploy_json(project_dir: str | Path, config: DeployConfig) -> Path:
    path = Path(project_dir) / "deploy.json"
    path.write_text(config.to_json(), encoding="utf-8")
    return path


# -- generation ----------------------------------------------------------
def _read_package_json(project_dir: Path) -> dict:
    path = project_dir / "package.json"
    if not path.is_file():
        raise DeployConfigError("package.json not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise DeployConfigError("package.json is not valid JSON") from None
    if not isinstance(data, dict):
        raise DeployConfigError("package.json must contain a JSON object")
    return data


def _package_manager(project_dir: Path) -> str:
    if (project_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project_dir / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _install_command(manager: str, project_dir: Path) -> str:
    if manager == "pnpm":
        return "pnpm install --frozen-lockfile"
    if manager == "yarn":
        return "yarn install --frozen-lockfile"
    return "npm ci" if (project_dir / "package-lock.json").exists() else "npm install"


def _run_prefix(manager: str) -> str:
    return {"npm": "npm run", "pnpm": "pnpm run", "yarn": "yarn"}[manager]


def _node_version(pkg: dict, warnings: list[str]) -> str:
    spec = (pkg.get("engines") or {}).get("node") if isinstance(pkg.get("engines"), dict) else None
    if not isinstance(spec, str):
        warnings.append(f"No engines.node in package.json; using Node {DEFAULT_NODE_MAJOR}")
        return DEFAULT_NODE_MAJOR
    match = re.search(r"\d+", spec)
    if match and match.group(0) in SUPPORTED_NODE_MAJORS:
        return match.group(0)
    warnings.append(
        f"engines.node '{spec}' is not supported; using Node {DEFAULT_NODE_MAJOR}"
    )
    return DEFAULT_NODE_MAJOR


def _read_next_config(project_dir: Path) -> str:
    for name in ("next.config.ts", "next.config.mjs", "next.config.js", "next.config.cjs"):
        path = project_dir / name
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def database_env_names(detected: set[str]) -> set[str]:
    """Variables a project with a database needs (names only)."""
    if any(n.startswith(("SUPABASE_", "NEXT_PUBLIC_SUPABASE_")) for n in detected):
        return set(SUPABASE_ENV)
    return {"DATABASE_URL"}


def hints_from_plan(plan: Mapping | None) -> tuple[bool, list[str]]:
    """Read database and env hints from the Plan JSON.

    PROVISIONAL: the Plan JSON schema is not frozen yet. Update the key names
    here when Intern 1 freezes schema v1. Returns (has_database, env_names).
    """
    if not plan:
        return False, []
    has_db = bool(plan.get("db", plan.get("database")))
    names: list[str] = []
    for item in plan.get("env") or plan.get("env_vars") or []:
        name = item if isinstance(item, str) else (item.get("name") if isinstance(item, dict) else None)
        if name:
            names.append(name)
    return has_db, names


def generate_deploy_config(project_dir: str | Path, plan: Mapping | None = None) -> GenerationResult:
    root = Path(project_dir)
    if not root.is_dir():
        raise DeployConfigError(f"Project directory not found: {project_dir}")
    pkg = _read_package_json(root)
    warnings: list[str] = []

    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if "next" not in deps:
        raise UnsupportedFrameworkError("Only Next.js projects are supported (no 'next' dependency)")

    manager = _package_manager(root)
    prefix = _run_prefix(manager)
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}

    # Only script NAMES are checked; script text is never copied into commands.
    if "build" in scripts:
        build_command = f"{prefix} build"
    else:
        build_command = "npx next build"
        warnings.append("No 'build' script in package.json; using 'npx next build'")

    next_config = _read_next_config(root)
    if re.search(r"""output\s*:\s*['"]export['"]""", next_config):
        output_directory, start_command = "out", ""
    else:
        match = re.search(r"""distDir\s*:\s*['"]([^'"]+)['"]""", next_config)
        output_directory = match.group(1) if match else ".next"
        if "start" in scripts:
            start_command = f"{prefix} start"
        else:
            start_command = "npx next start"
            warnings.append("No 'start' script in package.json; using 'npx next start'")

    detected = detect_env_vars(root)
    has_db, plan_env = hints_from_plan(plan)
    for name in plan_env:
        if not isinstance(name, str) or not _ENV_NAME.match(name):
            raise DeployConfigError("Plan contains an invalid environment variable name")
    required = detected | set(plan_env)
    if has_db:
        required |= database_env_names(detected)

    config = DeployConfig(
        framework=FRAMEWORK_NEXTJS,
        node_version=_node_version(pkg, warnings),
        install_command=_install_command(manager, root),
        build_command=build_command,
        start_command=start_command,
        output_directory=output_directory,
        required_env=tuple(sorted(required)),
        database=has_db,
    )
    return GenerationResult(config, tuple(warnings))


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    result = generate_deploy_config(argv[0])
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(result.config.to_json(), end="")
    if "--write" in argv[1:]:
        print(f"wrote {write_deploy_json(argv[0], result.config)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))