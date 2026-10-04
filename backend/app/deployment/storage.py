"""Versioned storage for deployment packages (.tar.gz).

Objects live at {tenant_id}/{project_id}/{version}.tar.gz with a small
{version}.meta.json next to them holding the sha256 recorded at upload time.

Rules:
- Every call is scoped by tenant_id. Another tenant's package looks exactly
  like a missing one (ArtifactNotFound), so keys cannot be probed.
- Versions are immutable: uploading an existing version fails.
- Uploads must match the declared checksum, and downloads are verified against
  the stored one, so corruption or tampering is detected.
- Key parts are validated so they cannot contain slashes or "..".
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .artifact import sha256_file

SUFFIX = ".tar.gz"
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class StorageError(Exception):
    pass


class ArtifactNotFound(StorageError):
    pass


class ArtifactExists(StorageError):
    pass


class ChecksumMismatch(StorageError):
    pass


class InvalidKeyError(ValueError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    tenant_id: str
    project_id: str
    version: str
    key: str
    sha256: str
    size_bytes: int


class ArtifactStorage(Protocol):
    def upload(self, tenant_id: str, project_id: str, version: str,
               artifact_path: str | Path, sha256: str) -> StoredArtifact: ...

    def download(self, tenant_id: str, project_id: str, version: str,
                 dest_dir: str | Path) -> Path: ...

    def list_versions(self, tenant_id: str, project_id: str) -> list[str]: ...

    def delete(self, tenant_id: str, project_id: str, version: str) -> bool: ...


def _check_part(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE.match(value):
        raise InvalidKeyError(f"Invalid {label}")


def object_key(tenant_id: str, project_id: str, version: str) -> str:
    for value, label in ((tenant_id, "tenant_id"), (project_id, "project_id"), (version, "version")):
        _check_part(value, label)
    return f"{tenant_id}/{project_id}/{version}{SUFFIX}"


def _meta_name(version: str) -> str:
    return f"{version}.meta.json"


def _meta_bytes(sha256: str, size_bytes: int) -> bytes:
    return json.dumps({"sha256": sha256, "size_bytes": size_bytes}).encode("utf-8")


def _verify_declared(artifact_path: str | Path, sha256: str) -> None:
    if not _SHA.match(sha256 or ""):
        raise ValueError("sha256 must be 64 lowercase hex characters")
    if not Path(artifact_path).is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")
    if sha256_file(artifact_path) != sha256:
        raise ChecksumMismatch("Artifact does not match the declared checksum")


def _expected_sha(meta_bytes: bytes) -> str:
    try:
        sha = json.loads(meta_bytes.decode("utf-8"))["sha256"]
    except (ValueError, KeyError, TypeError):
        raise StorageError("Artifact metadata is corrupted") from None
    if not isinstance(sha, str) or not _SHA.match(sha):
        raise StorageError("Artifact metadata is corrupted")
    return sha


class LocalArtifactStorage:
    """Stores packages on local disk. For development and tests."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _locate(self, tenant_id: str, project_id: str, version: str) -> tuple[Path, Path]:
        archive = (self._root / object_key(tenant_id, project_id, version)).resolve()
        if not archive.is_relative_to(self._root):
            raise InvalidKeyError("Invalid key")
        return archive, archive.with_name(_meta_name(version))

    def upload(self, tenant_id, project_id, version, artifact_path, sha256) -> StoredArtifact:
        _verify_declared(artifact_path, sha256)
        archive, meta = self._locate(tenant_id, project_id, version)
        if archive.exists():
            raise ArtifactExists(f"Version {version} already exists")
        archive.parent.mkdir(parents=True, exist_ok=True)
        tmp = archive.with_name(archive.name + ".tmp")
        shutil.copyfile(artifact_path, tmp)
        os.replace(tmp, archive)
        size = archive.stat().st_size
        meta.write_bytes(_meta_bytes(sha256, size))
        return StoredArtifact(tenant_id, project_id, version,
                              object_key(tenant_id, project_id, version), sha256, size)

    def download(self, tenant_id, project_id, version, dest_dir) -> Path:
        archive, meta = self._locate(tenant_id, project_id, version)
        if not archive.is_file() or not meta.is_file():
            raise ArtifactNotFound(f"Version {version} not found")
        expected = _expected_sha(meta.read_bytes())
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{project_id}-{version}{SUFFIX}"
        shutil.copyfile(archive, dest)
        if sha256_file(dest) != expected:
            dest.unlink(missing_ok=True)
            raise ChecksumMismatch("Stored artifact failed checksum verification")
        return dest

    def list_versions(self, tenant_id, project_id) -> list[str]:
        _check_part(tenant_id, "tenant_id")
        _check_part(project_id, "project_id")
        folder = self._root / tenant_id / project_id
        if not folder.is_dir():
            return []
        return sorted(p.name[: -len(SUFFIX)] for p in folder.iterdir() if p.name.endswith(SUFFIX))

    def delete(self, tenant_id, project_id, version) -> bool:
        archive, meta = self._locate(tenant_id, project_id, version)
        existed = archive.exists()
        archive.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        return existed


class SupabaseArtifactStorage:
    """Stores packages in a PRIVATE Supabase Storage bucket.

    Use a supabase-py client created with the SERVICE ROLE key, server-side only.
    NOTE: not yet tested against a real Supabase project (only a fake client).
    """

    def __init__(self, client, bucket: str = "deployment-artifacts") -> None:
        self._bucket = client.storage.from_(bucket)

    def _names(self, tenant_id: str, project_id: str) -> set[str]:
        try:
            items = self._bucket.list(f"{tenant_id}/{project_id}")
        except Exception:
            raise StorageError("Could not list artifacts") from None
        return {item["name"] for item in (items or [])}

    def upload(self, tenant_id, project_id, version, artifact_path, sha256) -> StoredArtifact:
        key = object_key(tenant_id, project_id, version)
        _verify_declared(artifact_path, sha256)
        if f"{version}{SUFFIX}" in self._names(tenant_id, project_id):
            raise ArtifactExists(f"Version {version} already exists")
        data = Path(artifact_path).read_bytes()
        meta_key = f"{tenant_id}/{project_id}/{_meta_name(version)}"
        try:
            self._bucket.upload(key, data, {"content-type": "application/gzip", "upsert": "false"})
            self._bucket.upload(
                meta_key, _meta_bytes(sha256, len(data)),
                {"content-type": "application/json", "upsert": "false"},
            )
        except Exception:
            raise StorageError("Upload failed") from None
        return StoredArtifact(tenant_id, project_id, version, key, sha256, len(data))

    def download(self, tenant_id, project_id, version, dest_dir) -> Path:
        key = object_key(tenant_id, project_id, version)
        names = self._names(tenant_id, project_id)
        if f"{version}{SUFFIX}" not in names or _meta_name(version) not in names:
            raise ArtifactNotFound(f"Version {version} not found")
        try:
            data = self._bucket.download(key)
            meta = self._bucket.download(f"{tenant_id}/{project_id}/{_meta_name(version)}")
        except Exception:
            raise StorageError("Download failed") from None
        import hashlib

        if hashlib.sha256(data).hexdigest() != _expected_sha(meta):
            raise ChecksumMismatch("Stored artifact failed checksum verification")
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{project_id}-{version}{SUFFIX}"
        dest.write_bytes(data)
        return dest

    def list_versions(self, tenant_id, project_id) -> list[str]:
        _check_part(tenant_id, "tenant_id")
        _check_part(project_id, "project_id")
        return sorted(n[: -len(SUFFIX)] for n in self._names(tenant_id, project_id) if n.endswith(SUFFIX))

    def delete(self, tenant_id, project_id, version) -> bool:
        key = object_key(tenant_id, project_id, version)
        existed = f"{version}{SUFFIX}" in self._names(tenant_id, project_id)
        try:
            self._bucket.remove([key, f"{tenant_id}/{project_id}/{_meta_name(version)}"])
        except Exception:
            raise StorageError("Delete failed") from None
        return existed