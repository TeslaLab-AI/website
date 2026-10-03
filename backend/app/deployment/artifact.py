"""Package a built project as a deployment artifact: .tar.gz + sha256 + version.

- Deterministic: the same files always give the same checksum (sorted entries,
  fixed timestamps and ownership), so a changed checksum means changed content.
- Excludes node_modules, .git, .next/cache and secret-like files (.env, keys).

CLI:  python -m app.deployment.artifact <project_dir> <output_dir> <project_id> <version>
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .github_service import _is_forbidden_path

EXCLUDED_DIRS = {"node_modules", ".git", "__pycache__", ".vercel"}
EXCLUDED_PATH_PREFIXES = (".next/cache",)


@dataclass(frozen=True)
class Artifact:
    project_id: str
    version: str
    path: str
    sha256: str
    size_bytes: int
    file_count: int
    created_at: str


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_files(project_dir: Path) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(project_dir):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in EXCLUDED_DIRS
            and not (Path(root) / d).relative_to(project_dir).as_posix().startswith(
                EXCLUDED_PATH_PREFIXES
            )
        )
        for name in sorted(names):
            rel = (Path(root) / name).relative_to(project_dir).as_posix()
            if _is_forbidden_path(rel) or rel.startswith(EXCLUDED_PATH_PREFIXES):
                continue
            files.append(Path(root) / name)
    return files


def create_artifact(
    project_dir: str | Path,
    output_dir: str | Path,
    project_id: str,
    version: str,
) -> Artifact:
    project_dir = Path(project_dir)
    output_dir = Path(output_dir)
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")
    if not project_id or not version:
        raise ValueError("project_id and version are required")
    for part in (project_id, version):
        if any(c in part for c in "/\\ "):
            raise ValueError("project_id and version must not contain slashes or spaces")
    output_dir.mkdir(parents=True, exist_ok=True)

    files = _collect_files(project_dir)
    if not files:
        raise ValueError("No files to package")

    archive_path = output_dir / f"{project_id}-{version}.tar.gz"
    buffer = io.BytesIO()
    # mtime=0 on gzip + fixed tar metadata => reproducible bytes.
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for file in files:
                info = tar.gettarinfo(str(file), arcname=file.relative_to(project_dir).as_posix())
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with open(file, "rb") as f:
                    tar.addfile(info, f)
    archive_path.write_bytes(buffer.getvalue())

    artifact = Artifact(
        project_id=project_id,
        version=version,
        path=str(archive_path),
        sha256=sha256_file(archive_path),
        size_bytes=archive_path.stat().st_size,
        file_count=len(files),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    manifest = output_dir / f"{project_id}-{version}.manifest.json"
    manifest.write_text(json.dumps(asdict(artifact), indent=2), encoding="utf-8")
    return artifact


def verify_artifact(path: str | Path, expected_sha256: str) -> bool:
    return sha256_file(path) == expected_sha256


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    artifact = create_artifact(*argv)
    print(json.dumps(asdict(artifact), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))