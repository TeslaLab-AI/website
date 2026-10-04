import json
import tarfile

import pytest

from app.deployment.artifact import create_artifact, sha256_file, verify_artifact


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "app"
    files = {
        "package.json": '{"name": "sample"}',
        "src/page.tsx": "export default function Page() { return null }",
        ".next/server/app.js": "built output",
        ".next/cache/huge.bin": "cache that should be excluded",
        "node_modules/lib/index.js": "dependency",
        ".git/config": "git internals",
        ".env": "STRIPE_KEY=sk_live_REAL_SECRET",
        ".env.local": "ANOTHER=secret",
        ".env.example": "STRIPE_KEY=",
        "certs/server.pem": "private key",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def members(path):
    with tarfile.open(path) as tar:
        return set(tar.getnames())


def test_includes_source_and_build_output(project, tmp_path):
    art = create_artifact(project, tmp_path / "out", "proj1", "1.0.0")
    names = members(art.path)
    assert {"package.json", "src/page.tsx", ".next/server/app.js", ".env.example"} <= names


def test_excludes_deps_cache_git_and_secret_files(project, tmp_path):
    art = create_artifact(project, tmp_path / "out", "proj1", "1.0.0")
    names = members(art.path)
    assert not any(n.startswith(("node_modules", ".git/", ".next/cache")) for n in names)
    assert ".env" not in names and ".env.local" not in names
    assert "certs/server.pem" not in names


def test_secret_values_never_in_archive_bytes(project, tmp_path):
    art = create_artifact(project, tmp_path / "out", "proj1", "1.0.0")
    with tarfile.open(art.path) as tar:
        blob = b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile())
    assert b"sk_live_REAL_SECRET" not in blob


def test_checksum_matches_and_manifest_written(project, tmp_path):
    out = tmp_path / "out"
    art = create_artifact(project, out, "proj1", "1.0.0")
    assert art.sha256 == sha256_file(art.path)
    assert verify_artifact(art.path, art.sha256)
    manifest = json.loads((out / "proj1-1.0.0.manifest.json").read_text())
    assert manifest["sha256"] == art.sha256
    assert manifest["version"] == "1.0.0"
    assert manifest["file_count"] == art.file_count


def test_checksum_is_reproducible_for_same_content(project, tmp_path):
    first = create_artifact(project, tmp_path / "out1", "proj1", "1.0.0")
    second = create_artifact(project, tmp_path / "out2", "proj1", "1.0.0")
    assert first.sha256 == second.sha256


def test_checksum_changes_when_content_changes(project, tmp_path):
    first = create_artifact(project, tmp_path / "out1", "proj1", "1.0.0")
    (project / "src/page.tsx").write_text("changed")
    second = create_artifact(project, tmp_path / "out2", "proj1", "1.0.0")
    assert first.sha256 != second.sha256


def test_tampering_is_detected(project, tmp_path):
    art = create_artifact(project, tmp_path / "out", "proj1", "1.0.0")
    with open(art.path, "ab") as f:
        f.write(b"tamper")
    assert not verify_artifact(art.path, art.sha256)


def test_rejects_bad_inputs(project, tmp_path):
    with pytest.raises(FileNotFoundError):
        create_artifact(tmp_path / "missing", tmp_path / "out", "p", "1")
    with pytest.raises(ValueError):
        create_artifact(project, tmp_path / "out", "../evil", "1.0.0")
    with pytest.raises(ValueError):
        create_artifact(project, tmp_path / "out", "p", "")


# -- extra_files (used to embed deploy.json) -----------------------------
def test_extra_files_are_added_and_counted(project, tmp_path):
    plain = create_artifact(project, tmp_path / "o1", "proj1", "1.0.0")
    extra = create_artifact(project, tmp_path / "o2", "proj1", "1.0.0",
                            extra_files={"deploy.json": b"{}"})
    assert "deploy.json" in members(extra.path)
    assert extra.file_count == plain.file_count + 1


def test_extra_file_replaces_same_named_file_on_disk(project, tmp_path):
    (project / "deploy.json").write_text("from disk")
    art = create_artifact(project, tmp_path / "out", "proj1", "1.0.0",
                          extra_files={"deploy.json": b"from memory"})
    with tarfile.open(art.path) as tar:
        names = [m.name for m in tar.getmembers()]
        assert names.count("deploy.json") == 1
        assert tar.extractfile("deploy.json").read() == b"from memory"


def test_extra_files_keep_checksum_reproducible(project, tmp_path):
    first = create_artifact(project, tmp_path / "o1", "p", "1", extra_files={"deploy.json": b"{}"})
    second = create_artifact(project, tmp_path / "o2", "p", "1", extra_files={"deploy.json": b"{}"})
    assert first.sha256 == second.sha256


@pytest.mark.parametrize("bad", ["../x", "/abs", ".env", "a\\b", ""])
def test_bad_extra_file_names_are_rejected(project, tmp_path, bad):
    with pytest.raises(ValueError):
        create_artifact(project, tmp_path / "out", "p", "1", extra_files={bad: b"x"})
