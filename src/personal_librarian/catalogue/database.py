"""Safe SQLite connection and catalogue lifecycle management."""

from __future__ import annotations

import ntpath
import os
import sqlite3
from pathlib import Path

from personal_librarian.catalogue.errors import CatalogueError, CataloguePathError
from personal_librarian.catalogue.migrations import (
    CURRENT_SCHEMA_VERSION,
    apply_migrations,
    read_schema_version,
)
from personal_librarian.catalogue.models import CatalogueStatus
from personal_librarian.catalogue.maintenance import require_catalogue_available
from personal_librarian.safety import PathIntent, PathSafetyPolicy


def initialise_catalogue(
    database_path: str | os.PathLike[str],
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> CatalogueStatus:
    """Create or migrate only the explicitly supplied catalogue database."""

    policy = safety_policy or PathSafetyPolicy()
    path = _validate_database_path(database_path, PathIntent.WRITE, policy)
    connection = _connect(path, read_only=False)
    try:
        apply_migrations(connection)
        return _status(connection, path)
    finally:
        connection.close()


def get_catalogue_status(
    database_path: str | os.PathLike[str],
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> CatalogueStatus:
    """Inspect an existing catalogue without creating or migrating it."""

    policy = safety_policy or PathSafetyPolicy()
    path = _validate_database_path(database_path, PathIntent.READ, policy)
    connection = _connect(path, read_only=True)
    try:
        return _status(connection, path)
    finally:
        connection.close()


def connect_existing_catalogue(
    database_path: str | os.PathLike[str],
    *,
    read_only: bool = True,
    safety_policy: PathSafetyPolicy | None = None,
) -> sqlite3.Connection:
    """Open an already-initialised catalogue with foreign keys enabled."""

    policy = safety_policy or PathSafetyPolicy()
    intent = PathIntent.READ if read_only else PathIntent.WRITE
    path = _validate_database_path(database_path, intent, policy)
    require_catalogue_available(path)
    if not path.is_file():
        raise CatalogueError(f"Catalogue database does not exist: {path}")
    connection = _connect(path, read_only=read_only)
    try:
        read_schema_version(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _validate_database_path(
    database_path: str | os.PathLike[str],
    intent: PathIntent,
    policy: PathSafetyPolicy,
) -> Path:
    try:
        raw_path = os.fspath(database_path)
    except TypeError as exc:
        raise CataloguePathError("Catalogue path must be text or path-like.") from exc
    if not isinstance(raw_path, str) or not raw_path:
        raise CataloguePathError("Catalogue path must be a non-empty text path.")

    result = policy.check_path(raw_path, intent=intent)
    if not result.allowed:
        raise CataloguePathError(f"Unsafe catalogue path ({result.code}): {result.reason}")

    candidate = raw_path.replace("/", "\\")
    drive, tail = ntpath.splitdrive(candidate)
    is_drive_absolute = len(drive) == 2 and drive[1] == ":" and tail.startswith("\\")
    is_unc_absolute = candidate.startswith("\\\\") and bool(drive)
    if not (is_drive_absolute or is_unc_absolute):
        raise CataloguePathError("Catalogue path must be an explicit absolute drive or UNC path.")
    return Path(raw_path)


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    require_catalogue_available(path)
    try:
        if read_only:
            connection = sqlite3.connect(
                f"{path.as_uri()}?mode=ro",
                uri=True,
                timeout=5,
            )
        else:
            connection = sqlite3.connect(path, timeout=5)
    except (OSError, sqlite3.Error, ValueError) as exc:
        access = "read-only" if read_only else "read-write"
        raise CatalogueError(f"Cannot open catalogue '{path}' in {access} mode: {exc}") from exc

    try:
        require_catalogue_available(path)
    except BaseException:
        connection.close()
        raise
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    enabled = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if enabled != 1:
        connection.close()
        raise CatalogueError("SQLite foreign-key enforcement could not be enabled.")
    return connection


def _status(connection: sqlite3.Connection, path: Path) -> CatalogueStatus:
    version = read_schema_version(connection)
    tables = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )
    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    return CatalogueStatus(
        database_path=str(path),
        schema_version=version,
        current_schema_version=CURRENT_SCHEMA_VERSION,
        up_to_date=version == CURRENT_SCHEMA_VERSION,
        foreign_keys_enabled=foreign_keys_enabled,
        tables=tables,
    )
