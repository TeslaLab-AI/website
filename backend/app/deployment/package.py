"""Deployment packages: build output + deploy.json + checksum + version.

build_package()   -> generate deploy.json, archive the project with it inside
publish_package() -> upload the archive to storage (tenant-scoped, immutable)
fetch_package()   -> download, verify the checksum, and read deploy.json back
"""

from __future__ import annotations

import json
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .artifact import Artifact, create_artifact
from .deploy_config import (
    DeployConfig,
    DeployConfigError,
    generate_deploy_config,
    parse_deploy_config,
)
from .storage import ArtifactStorage, StoredArtifact

CONFIG_NAME = "deploy.json"
MAX_CONFIG_BYTES = 1_000_000


@dataclass(frozen=True)
class Package:
    artifact: Artifact
    config: DeployConfig
    warnings: tuple[str, ...]


def build_package(
    project_dir: str | Path,
    output_dir: str | Path,
    project_id: str,
    version: str,
    plan: Mapping | None = None,
) -> Package:
    """Archive the project with a freshly generated deploy.json inside.

    Any deploy.json already on disk is ignored and replaced, so the archive can
    never carry a hand-edited (or malicious) config.
    """
    result = generate_deploy_config(project_dir, plan)
    artifact = create_artifact(
        project_dir, output_dir, project_id, version,
        extra_files={CONFIG_NAME: result.config.to_json().encode("utf-8")},
    )
    return Package(artifact, result.config, result.warnings)


def read_package_config(archive_path: str | Path) -> DeployConfig:
    """Read and validate deploy.json from an archive without extracting it."""
    try:
        with tarfile.open(archive_path) as tar:
            try:
                member = tar.getmember(CONFIG_NAME)
            except KeyError:
                raise DeployConfigError("Package has no deploy.json") from None
            if not member.isfile() or member.size > MAX_CONFIG_BYTES:
                raise DeployConfigError("deploy.json in the package is invalid")
            data = tar.extractfile(member).read()
    except (tarfile.TarError, OSError):
        raise DeployConfigError("Package is not a valid archive") from None
    try:
        parsed = json.loads(data)
    except ValueError:
        raise DeployConfigError("deploy.json in the package is not valid JSON") from None
    return parse_deploy_config(parsed)


def publish_package(storage: ArtifactStorage, tenant_id: str, package: Package) -> StoredArtifact:
    a = package.artifact
    return storage.upload(tenant_id, a.project_id, a.version, a.path, a.sha256)


def fetch_package(
    storage: ArtifactStorage,
    tenant_id: str,
    project_id: str,
    version: str,
    dest_dir: str | Path,
) -> tuple[Path, DeployConfig]:
    """Download a package (checksum verified) and return it with its config."""
    path = storage.download(tenant_id, project_id, version, dest_dir)
    return path, read_package_config(path)