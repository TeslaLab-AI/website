import hashlib

import pytest

from app.deployment.storage import (
    ArtifactExists,
    ArtifactNotFound,
    ChecksumMismatch,
    InvalidKeyError,
    LocalArtifactStorage,
    StorageError,
    SupabaseArtifactStorage,
    object_key,
)

A, B = "tenant-a", "tenant-b"
CONTENT = b"fake archive bytes"
SHA = hashlib.sha256(CONTENT).hexdigest()


# -- a fake Supabase client (mimics storage.from_(bucket).upload/download/list/remove) --
class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.fail_uploads = False

    def upload(self, path, file, file_options=None):
        if self.fail_uploads:
            raise RuntimeError("boom: secret-connection-detail")
        if path in self.objects and (file_options or {}).get("upsert") != "true":
            raise RuntimeError("Duplicate")
        self.objects[path] = bytes(file)

    def download(self, path):
        if path not in self.objects:
            raise RuntimeError("Not found")
        return self.objects[path]

    def list(self, path=""):
        prefix = path.rstrip("/") + "/"
        names = {k[len(prefix):] for k in self.objects if k.startswith(prefix) and "/" not in k[len(prefix):]}
        return [{"name": n} for n in sorted(names)]

    def remove(self, paths):
        removed = [p for p in paths if self.objects.pop(p, None) is not None]
        return [{"name": p} for p in removed]


class FakeClient:
    def __init__(self):
        self.bucket = FakeBucket()
        self.storage = self

    def from_(self, name):
        return self.bucket


class Harness:
    """Wraps one storage implementation plus a way to tamper with stored bytes."""

    def __init__(self, storage, tamper):
        self.storage = storage
        self.tamper = tamper


@pytest.fixture(params=["local", "supabase"])
def harness(request, tmp_path):
    if request.param == "local":
        root = tmp_path / "store"
        storage = LocalArtifactStorage(root)

        def tamper(tenant, project, version):
            with open(root / tenant / project / f"{version}.tar.gz", "ab") as f:
                f.write(b"tampered")

        return Harness(storage, tamper)

    client = FakeClient()

    def tamper(tenant, project, version):
        client.bucket.objects[f"{tenant}/{project}/{version}.tar.gz"] += b"tampered"

    harness = Harness(SupabaseArtifactStorage(client), tamper)
    harness.client = client
    return harness


@pytest.fixture
def artifact_file(tmp_path):
    path = tmp_path / "src.tar.gz"
    path.write_bytes(CONTENT)
    return path


def upload(h, artifact_file, tenant=A, project="proj1", version="1.0.0", sha=SHA):
    return h.storage.upload(tenant, project, version, artifact_file, sha)


# -- behaviour shared by both implementations ----------------------------
def test_upload_and_download_round_trip(harness, artifact_file, tmp_path):
    stored = upload(harness, artifact_file)
    assert stored.key == "tenant-a/proj1/1.0.0.tar.gz"
    assert stored.sha256 == SHA and stored.size_bytes == len(CONTENT)
    path = harness.storage.download(A, "proj1", "1.0.0", tmp_path / "dl")
    assert path.read_bytes() == CONTENT


def test_upload_rejects_wrong_or_malformed_checksum(harness, artifact_file):
    with pytest.raises(ChecksumMismatch):
        upload(harness, artifact_file, sha="0" * 64)
    with pytest.raises(ValueError):
        upload(harness, artifact_file, sha="not-a-sha")


def test_versions_are_immutable(harness, artifact_file):
    upload(harness, artifact_file)
    with pytest.raises(ArtifactExists):
        upload(harness, artifact_file)


def test_other_tenant_cannot_download_list_or_delete(harness, artifact_file, tmp_path):
    upload(harness, artifact_file)
    with pytest.raises(ArtifactNotFound):
        harness.storage.download(B, "proj1", "1.0.0", tmp_path / "dl")
    assert harness.storage.list_versions(B, "proj1") == []
    assert harness.storage.delete(B, "proj1", "1.0.0") is False
    assert harness.storage.list_versions(A, "proj1") == ["1.0.0"]


def test_same_version_can_exist_for_different_tenants(harness, artifact_file):
    upload(harness, artifact_file, tenant=A)
    upload(harness, artifact_file, tenant=B)
    assert harness.storage.list_versions(A, "proj1") == ["1.0.0"]
    assert harness.storage.list_versions(B, "proj1") == ["1.0.0"]


def test_projects_are_isolated(harness, artifact_file, tmp_path):
    upload(harness, artifact_file, project="proj1")
    with pytest.raises(ArtifactNotFound):
        harness.storage.download(A, "proj2", "1.0.0", tmp_path / "dl")


def test_tampered_storage_is_detected_on_download(harness, artifact_file, tmp_path):
    upload(harness, artifact_file)
    harness.tamper(A, "proj1", "1.0.0")
    with pytest.raises(ChecksumMismatch):
        harness.storage.download(A, "proj1", "1.0.0", tmp_path / "dl")
    assert not (tmp_path / "dl" / "proj1-1.0.0.tar.gz").exists()


def test_download_missing_version(harness, tmp_path):
    with pytest.raises(ArtifactNotFound):
        harness.storage.download(A, "proj1", "9.9.9", tmp_path / "dl")


@pytest.mark.parametrize(
    "tenant,project,version",
    [("../x", "p", "1"), ("a/b", "p", "1"), ("", "p", "1"), (".hidden", "p", "1"),
     (A, "p/../q", "1"), (A, "p", "../../etc"), (A, "p", "1 0")],
)
def test_invalid_key_parts_are_rejected(harness, artifact_file, tmp_path, tenant, project, version):
    with pytest.raises(InvalidKeyError):
        harness.storage.upload(tenant, project, version, artifact_file, SHA)
    with pytest.raises(InvalidKeyError):
        harness.storage.download(tenant, project, version, tmp_path / "dl")


def test_list_versions_sorted_and_delete(harness, artifact_file, tmp_path):
    for version in ("1.0.1", "1.0.0", "2.0.0"):
        upload(harness, artifact_file, version=version)
    assert harness.storage.list_versions(A, "proj1") == ["1.0.0", "1.0.1", "2.0.0"]
    assert harness.storage.delete(A, "proj1", "1.0.1") is True
    assert harness.storage.delete(A, "proj1", "1.0.1") is False
    assert harness.storage.list_versions(A, "proj1") == ["1.0.0", "2.0.0"]
    with pytest.raises(ArtifactNotFound):
        harness.storage.download(A, "proj1", "1.0.1", tmp_path / "dl")


def test_object_key_format():
    assert object_key("t1", "p1", "1.2.3") == "t1/p1/1.2.3.tar.gz"


# -- Supabase-specific -----------------------------------------------------
def test_supabase_upload_failure_is_wrapped_without_leaking_details(artifact_file):
    client = FakeClient()
    client.bucket.fail_uploads = True
    storage = SupabaseArtifactStorage(client)
    with pytest.raises(StorageError) as exc:
        storage.upload(A, "proj1", "1.0.0", artifact_file, SHA)
    assert "secret-connection-detail" not in str(exc.value)


def test_key_parts_and_checksums_with_trailing_newline_are_rejected(harness, artifact_file, tmp_path):
    with pytest.raises(InvalidKeyError):
        harness.storage.upload(A, "proj1", "1.0.0\n", artifact_file, SHA)
    with pytest.raises(InvalidKeyError):
        harness.storage.upload("tenant-a\n", "proj1", "1.0.0", artifact_file, SHA)
    with pytest.raises(ValueError):
        harness.storage.upload(A, "proj1", "1.0.0", artifact_file, SHA + "\n")
