"""Create the local, versioned Windows release candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

RELEASE_VERSION = "0.1.0rc7"
ARCHIVE_NAME = f"PersonalLibrarian-{RELEASE_VERSION}-win64.zip"
SCHEMA_VERSION = 10
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_FORBIDDEN_PARTS = {
    ".git",
    "__pycache__",
    "build",
    "release",
    "tests",
}
_FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def distribution_files(distribution: Path) -> list[Path]:
    """Return a deterministic, safety-checked list of distribution files."""

    if not distribution.is_dir():
        raise FileNotFoundError(f"Distribution is missing: {distribution}")
    files = sorted(
        (path for path in distribution.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(distribution).as_posix().casefold(),
    )
    if not files:
        raise ValueError("Distribution contains no files.")
    for path in files:
        relative = path.relative_to(distribution)
        lowered_parts = {part.casefold() for part in relative.parts}
        if lowered_parts & _FORBIDDEN_PARTS:
            raise ValueError(f"Forbidden distribution path: {relative}")
        if path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
            raise ValueError(f"Catalogue-like file found in distribution: {relative}")
        if path.name.casefold().startswith(".env") or "smoke-report" in path.name.casefold():
            raise ValueError(f"Private or temporary file found in distribution: {relative}")
    return files


def create_archive(distribution: Path, files: list[Path], archive: Path) -> None:
    """Create a ZIP with stable selection, order, paths, and entry timestamps."""

    if archive.exists():
        raise FileExistsError(f"Refusing to overwrite release archive: {archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as destination:
            for source in files:
                relative = source.relative_to(distribution).as_posix()
                info = zipfile.ZipInfo(f"PersonalLibrarian/{relative}", _ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if source.suffix.casefold() == ".exe" else 0o644) << 16
                with source.open("rb") as input_stream, destination.open(info, "w") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
    except Exception:
        archive.unlink(missing_ok=True)
        raise


def verify_version_metadata(repository: Path) -> None:
    pyproject = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    if pyproject["project"]["version"] != RELEASE_VERSION:
        raise ValueError("Python project version does not match the release version.")
    package_init = (repository / "src/personal_librarian/__init__.py").read_text(
        encoding="utf-8"
    )
    if not re.search(rf'__version__\s*=\s*"{re.escape(RELEASE_VERSION)}"', package_init):
        raise ValueError("Runtime version does not match the release version.")
    windows_metadata = (repository / "packaging/version_info.txt").read_text(
        encoding="utf-8"
    )
    for expected in (
        "filevers=(0, 1, 0, 7)",
        "prodvers=(0, 1, 0, 7)",
        f"StringStruct(u'FileVersion', u'{RELEASE_VERSION}')",
        f"StringStruct(u'ProductVersion', u'{RELEASE_VERSION}')",
    ):
        if expected not in windows_metadata:
            raise ValueError(f"Windows version metadata is inconsistent: {expected}")


def git_output(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def write_release_files(
    repository: Path,
    distribution: Path,
    output: Path,
    base_source_commit: str,
) -> dict[str, object]:
    repository = repository.resolve()
    distribution = distribution.resolve()
    output = output.resolve()
    expected_distribution = (repository / "dist/PersonalLibrarian").resolve()
    expected_output = (repository / "release").resolve()
    if distribution != expected_distribution:
        raise ValueError(f"Distribution must be {expected_distribution}")
    if output != expected_output:
        raise ValueError(f"Release output must be {expected_output}")
    verify_version_metadata(repository)

    executable = distribution / "PersonalLibrarian.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Packaged executable is missing: {executable}")
    files = distribution_files(distribution)
    archive = output / ARCHIVE_NAME
    manifest_path = output / f"PersonalLibrarian-{RELEASE_VERSION}-win64.manifest.json"
    checksums_path = output / f"PersonalLibrarian-{RELEASE_VERSION}-win64.sha256"
    file_manifest_path = output / f"PersonalLibrarian-{RELEASE_VERSION}-win64.files.sha256"
    for target in (manifest_path, checksums_path, file_manifest_path):
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite release output: {target}")

    create_archive(distribution, files, archive)
    archive_hash = sha256_file(archive)
    executable_hash = sha256_file(executable)
    source_commit = git_output(repository, "rev-parse", "HEAD")
    working_tree_status = git_output(repository, "status", "--porcelain=v1")
    manifest: dict[str, object] = {
        "release_version": RELEASE_VERSION,
        "release_status": "local unsigned release candidate",
        "build_timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "base_source_commit": base_source_commit,
        "source_commit": source_commit,
        "working_tree_dirty": bool(working_tree_status),
        "working_tree_statement": (
            "Built from the uncommitted release-validation working tree; "
            "this is not a clean tagged release."
        ),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "validated_target": "Windows 11 Pro 64-bit",
        },
        "executable_name": executable.name,
        "distribution_name": distribution.name,
        "archive_name": archive.name,
        "archive_size_bytes": archive.stat().st_size,
        "archive_sha256": archive_hash,
        "executable_size_bytes": executable.stat().st_size,
        "executable_sha256": executable_hash,
        "packaged_file_count": len(files),
        "application_version": RELEASE_VERSION,
        "runtime": f"Python {platform.python_version()} bundled by PyInstaller",
        "schema_compatibility": {
            "expected_schema_version": SCHEMA_VERSION,
            "migration_introduced": False,
        },
        "production_data_compatibility": (
            "Schema-10-compatible successor to RC6. No production catalogue or media is "
            "bundled or migrated by this release; desktop launch never auto-migrates."
        ),
        "signed": False,
        "installer": False,
        "build_tooling": {
            "pyinstaller": importlib.metadata.version("PyInstaller"),
            "python": platform.python_version(),
            "archive_writer": "Python zipfile (DEFLATE level 9; normalized entry timestamps)",
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    checksums_path.write_text(
        f"{archive_hash}  {archive.name}\n"
        f"{executable_hash}  PersonalLibrarian/PersonalLibrarian.exe\n",
        encoding="ascii",
    )
    file_manifest_path.write_text(
        "".join(
            f"{sha256_file(path)}  PersonalLibrarian/{path.relative_to(distribution).as_posix()}\n"
            for path in files
        ),
        encoding="utf-8",
    )
    return {
        "archive": str(archive),
        "manifest": str(manifest_path),
        "checksums": str(checksums_path),
        "file_manifest": str(file_manifest_path),
        **manifest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--base-source-commit", required=True)
    args = parser.parse_args(argv)
    result = write_release_files(
        args.repository_root,
        args.repository_root / "dist/PersonalLibrarian",
        args.repository_root / "release",
        args.base_source_commit,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
