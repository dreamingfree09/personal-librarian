"""Production catalogue bootstrap, backup, health, and recovery controls."""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import sqlite3
import sys
import time
import uuid
from contextlib import ExitStack
from functools import wraps
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from personal_librarian import __version__
from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import ProductionError
from personal_librarian.catalogue.importers import import_verified_evidence
from personal_librarian.catalogue.migrations import CURRENT_SCHEMA_VERSION, read_schema_version
from personal_librarian.catalogue.maintenance import (
    catalogue_maintenance, exclusive_file, publish_no_replace, stream_sha256,
)
from personal_librarian.safety import PathIntent, PathSafetyPolicy, assess_write_destination


MANIFEST_VERSION = 2
SUPPORTED_MANIFEST_VERSIONS = frozenset({1, 2})
DEFAULT_RETENTION_COUNT = 10
DEFAULT_BACKUP_WARNING_AGE_SECONDS = 7 * 24 * 60 * 60
CATALOGUE_FILENAME = "personal_librarian.sqlite3"
BACKUP_CLASSES = frozenset({"operational-local", "independent-local"})


@dataclass(frozen=True, slots=True)
class ApplicationDataLayout:
    root: Path
    catalogue_dir: Path
    catalogue_path: Path
    backup_root: Path
    logs_root: Path
    exports_root: Path
    state_root: Path
    recovery_root: Path

    def as_dict(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in self.__slots__}


@dataclass(frozen=True, slots=True)
class ProductionReport:
    values: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return self.values

    def to_json(self) -> str:
        return json.dumps(self.values, ensure_ascii=False, sort_keys=True)

    def format_human(self) -> str:
        return "\n".join(f"{key}: {value}" for key, value in self.values.items())


def application_data_layout(
    app_data_root: str | os.PathLike[str],
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> ApplicationDataLayout:
    root = _validate_absolute_root(app_data_root, safety_policy or PathSafetyPolicy())
    return ApplicationDataLayout(
        root=root,
        catalogue_dir=root / "catalogue",
        catalogue_path=root / "catalogue" / CATALOGUE_FILENAME,
        backup_root=root / "backups" / "catalogue",
        logs_root=root / "logs",
        exports_root=root / "exports",
        state_root=root / "state",
        recovery_root=root / "state" / "recovery",
    )


def _exclusive_operation(function):
    @wraps(function)
    def run(**kwargs):
        policy = kwargs.get('safety_policy') or PathSafetyPolicy()
        layout = application_data_layout(kwargs['app_data_root'], safety_policy=policy)
        if function.__name__ == 'bootstrap_production':
            if layout.catalogue_path.exists():
                raise ProductionError('A catalogue already exists; bootstrap refuses overwrite.')
            _create_layout(layout, policy)
        else:
            if not kwargs.get('confirm_restore_catalogue') or not str(kwargs.get('actor', '')).strip():
                raise ProductionError('Recovery requires an actor and --confirm-restore-catalogue.')
            _require_layout_catalogue(layout)
        with catalogue_maintenance(layout.catalogue_dir, function.__name__) as lease:
            return function(**kwargs, _maintenance_state=lease)
    return run


@_exclusive_operation
def bootstrap_production(
    *,
    app_data_root: str | os.PathLike[str],
    m9_path: str | os.PathLike[str],
    m10_manifest_path: str | os.PathLike[str],
    m10_groups_path: str | os.PathLike[str],
    m10_rows_path: str | os.PathLike[str],
    m11_dualhash_path: str | os.PathLike[str],
    m11_pairs_path: str | os.PathLike[str],
    m11_groups_path: str | os.PathLike[str],
    m11_summary_path: str | os.PathLike[str],
    baselines: Mapping[str, Mapping[str, Any]] | None = None,
    safety_policy: PathSafetyPolicy | None = None,
    _maintenance_state: dict | None = None,
) -> ProductionReport:
    """Build a verified production catalogue in-root and atomically promote it."""

    policy = safety_policy or PathSafetyPolicy()
    layout = application_data_layout(app_data_root, safety_policy=policy)
    if layout.catalogue_path.exists():
        raise ProductionError("A catalogue already exists at the production path; bootstrap refuses overwrite.")
    _create_layout(layout, policy)
    if layout.catalogue_path.exists():
        raise ProductionError("A catalogue appeared at the production path; bootstrap refuses overwrite.")

    started = time.perf_counter()
    assert _maintenance_state is not None
    staging = layout.catalogue_dir / f".bootstrap-{_maintenance_state['attempt_id']}.sqlite3"
    identity = str(uuid.uuid4())
    created_at = _utc_now()
    evidence = {
        "m9": str(m9_path),
        "m10_manifest": str(m10_manifest_path),
        "m10_groups": str(m10_groups_path),
        "m10_rows": str(m10_rows_path),
        "m11_dualhash": str(m11_dualhash_path),
        "m11_pairs": str(m11_pairs_path),
        "m11_groups": str(m11_groups_path),
        "m11_summary": str(m11_summary_path),
    }
    try:
        initialise_catalogue(staging, safety_policy=policy)
        connection = connect_existing_catalogue(staging, read_only=False, safety_policy=policy)
        try:
            _configure_production_connection(connection)
            connection.execute(
                """
                INSERT INTO catalogue_identity(
                    singleton_id, catalogue_uuid, created_at, application_version,
                    schema_version_at_bootstrap, catalogue_role, app_data_root_fingerprint,
                    bootstrap_provenance_json
                ) VALUES (1, ?, ?, ?, ?, 'non-production', ?, ?)
                """,
                (
                    identity,
                    created_at,
                    __version__,
                    CURRENT_SCHEMA_VERSION,
                    _root_fingerprint(layout.root),
                    json.dumps({"source": "verified-m9-m10-m11-evidence", "paths": evidence}, sort_keys=True),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        imported = import_verified_evidence(
            database_path=staging,
            m9_path=m9_path,
            m10_manifest_path=m10_manifest_path,
            m10_groups_path=m10_groups_path,
            m10_rows_path=m10_rows_path,
            m11_dualhash_path=m11_dualhash_path,
            m11_pairs_path=m11_pairs_path,
            m11_groups_path=m11_groups_path,
            m11_summary_path=m11_summary_path,
            baselines=baselines,
            safety_policy=policy,
        )
        if not imported.matches_baselines:
            raise ProductionError("Bootstrap evidence reconciliation DIFFER; production was not marked.")
        check = _verify_database(staging, expected_uuid=identity, require_production=False, policy=policy)
        if not check["accepted"]:
            raise ProductionError(f"Bootstrap verification failed: {check['errors']}")
        connection = connect_existing_catalogue(staging, read_only=False, safety_policy=policy)
        try:
            connection.execute(
                "UPDATE catalogue_identity SET catalogue_role = 'production', production_marked_at = ? WHERE singleton_id = 1",
                (_utc_now(),),
            )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
        final_check = _verify_database(staging, expected_uuid=identity, require_production=True, policy=policy)
        if not final_check["accepted"]:
            raise ProductionError(f"Final bootstrap verification failed: {final_check['errors']}")
        _remove_empty_sqlite_sidecars(staging)
        with exclusive_file(staging) as staged_stream:
            if any(Path(f'{layout.catalogue_path}{suffix}').exists() for suffix in ('-wal', '-shm')):
                raise ProductionError('Bootstrap refuses pre-existing destination SQLite sidecars.')
            publish_no_replace(staging, layout.catalogue_path)
            if any(Path(f'{layout.catalogue_path}{suffix}').exists() for suffix in ('-wal', '-shm')):
                # Preserve the foreign sidecars and our own staged catalogue.
                assert _maintenance_state is not None
                _maintenance_state['retain'] = True
                if layout.catalogue_path.stat().st_ino != os.fstat(staged_stream.fileno()).st_ino:
                    raise ProductionError('Bootstrap publication identity changed; offline review required.')
                publish_no_replace(layout.catalogue_path, staging)
                _maintenance_state['retain'] = False
                raise ProductionError('Bootstrap destination SQLite sidecars appeared during publication.')
        return ProductionReport(
            {
                "result": "PASS",
                "catalogue_path": str(layout.catalogue_path),
                "catalogue_uuid": identity,
                "schema_version": CURRENT_SCHEMA_VERSION,
                "role": "production",
                "baseline_reconciliation": "MATCH",
                "stages": [stage.as_dict() for stage in imported.stages],
                "integrity_check": final_check["integrity_check"],
                "foreign_key_violations": final_check["foreign_key_violations"],
                "catalogue_size_bytes": layout.catalogue_path.stat().st_size,
                "duration_seconds": round(time.perf_counter() - started, 6),
            }
        )
    except BaseException:
        # Failed staging (including genuine WAL/SHM) is retained for diagnosis.
        raise


def create_backup(
    *,
    app_data_root: str | os.PathLike[str],
    backup_root: str | os.PathLike[str] | None = None,
    backup_class: str = "operational-local",
    reason: str = "manual",
    safety_policy: PathSafetyPolicy | None = None,
) -> ProductionReport:
    policy = safety_policy or PathSafetyPolicy()
    if backup_class not in BACKUP_CLASSES:
        raise ProductionError(f"Unsupported backup class: {backup_class!r}.")
    layout = application_data_layout(app_data_root, safety_policy=policy)
    _require_layout_catalogue(layout)
    if backup_class == "independent-local" and backup_root is None:
        raise ProductionError("Independent backup creation requires an explicit backup root.")
    approved_backup_root = (
        layout.backup_root if backup_root is None else _validate_absolute_root(backup_root, policy)
    )
    if backup_class == "independent-local":
        if not approved_backup_root.exists():
            raise ProductionError("The explicit independent backup root must already exist.")
        _validate_existing_directory(approved_backup_root, policy)
        destination_root = approved_backup_root / "backups" / "catalogue"
        if _windows_path_within(destination_root, layout.root):
            raise ProductionError("Independent backup destination must be outside production app data.")
        _create_validated_directory(destination_root, policy, approved_root=approved_backup_root)
        source_device = _physical_device_identity(layout.root)
        destination_device = _physical_device_identity(approved_backup_root)
        if source_device is None or destination_device is None:
            raise ProductionError("Physical-device independence could not be established.")
        if source_device == destination_device:
            raise ProductionError("Independent backup root is on the same physical device as production.")
        device_independence = "confirmed"
    else:
        destination_root = approved_backup_root
        _create_validated_directory(destination_root, policy)
        source_device = _physical_device_identity(layout.root)
        destination_device = _physical_device_identity(approved_backup_root)
        device_independence = "not-required"
    if _same_path(destination_root, layout.catalogue_path):
        raise ProductionError("Backup destination must not be the production database path.")
    source_identity = _read_identity(layout.catalogue_path, policy)
    if source_identity["catalogue_role"] != "production":
        raise ProductionError("Backup source is not identified as a production catalogue.")

    backup_id = str(uuid.uuid4())
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    basename = f"catalogue-{stamp}-{backup_id}"
    final_db = destination_root / f"{basename}.sqlite3"
    final_manifest = destination_root / f"{basename}.manifest.json"
    partial_db = destination_root / f".{basename}.incomplete.sqlite3"
    if final_db.exists() or final_manifest.exists() or partial_db.exists():
        raise ProductionError("Backup artefact collision; no file was overwritten.")

    started = time.perf_counter()
    try:
        source = connect_existing_catalogue(layout.catalogue_path, read_only=True, safety_policy=policy)
        target = sqlite3.connect(partial_db)
        try:
            source_schema_version = read_schema_version(source)
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        check = _verify_database(
            partial_db,
            expected_uuid=str(source_identity["catalogue_uuid"]),
            require_production=True,
            policy=policy,
            immutable=True,
            expected_schema_version=source_schema_version,
        )
        if not check["accepted"]:
            raise ProductionError(f"Backup verification failed: {check['errors']}")
        hash_started = time.perf_counter()
        digest = _sha256_file(partial_db)
        hash_seconds = time.perf_counter() - hash_started
        os.replace(partial_db, final_db)
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "status": "accepted",
            "backup_id": backup_id,
            "backup_class": backup_class,
            "source_catalogue_uuid": source_identity["catalogue_uuid"],
            "source_schema_version": check["schema_version"],
            "created_at": _utc_now(),
            "source_database_path": str(layout.catalogue_path),
            "source_database_size_bytes": layout.catalogue_path.stat().st_size,
            "backup_database_filename": final_db.name,
            "backup_database_size_bytes": final_db.stat().st_size,
            "backup_sha256": digest,
            "integrity_check": check["integrity_check"],
            "foreign_key_violations": check["foreign_key_violations"],
            "application_version": __version__,
            "backup_reason": reason,
            "approved_backup_root": str(approved_backup_root),
            "backup_directory": str(destination_root),
            "destination_root_fingerprint": _root_fingerprint(approved_backup_root),
            "source_device_identity": source_device,
            "destination_device_identity": destination_device,
            "device_independence": device_independence,
            "catalogue_counts": check["catalogue_counts"],
            "verification_status": "accepted-at-creation",
            "backup_duration_seconds": round(time.perf_counter() - started, 6),
            "sha256_duration_seconds": round(hash_seconds, 6),
        }
        _write_json_exclusive(final_manifest, manifest)
        return ProductionReport({**manifest, "database_path": str(final_db), "manifest_path": str(final_manifest)})
    except Exception:
        _remove_file_if_present(partial_db)
        if final_db.exists() and not final_manifest.exists():
            _remove_file_if_present(final_db)
        raise


def list_backups(
    *, app_data_root: str | os.PathLike[str], backup_root: str | os.PathLike[str] | None = None,
    backup_class: str | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> ProductionReport:
    policy = safety_policy or PathSafetyPolicy()
    if backup_class is not None and backup_class not in BACKUP_CLASSES:
        raise ProductionError(f"Unsupported backup class: {backup_class!r}.")
    layout = application_data_layout(app_data_root, safety_policy=policy)
    approved_root = layout.backup_root if backup_root is None else _validate_absolute_root(backup_root, policy)
    root = (
        approved_root / "backups" / "catalogue"
        if backup_class == "independent-local"
        else approved_root
    )
    if not root.exists():
        return ProductionReport(
            {"backup_root": str(root), "backup_class": backup_class, "count": 0, "backups": []}
        )
    _validate_existing_directory(root, policy)
    backups: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("catalogue-*.manifest.json")):
        try:
            manifest = _read_manifest(manifest_path)
        except ProductionError:
            continue
        manifest_class = _manifest_backup_class(manifest)
        if manifest.get("status") == "accepted" and (
            backup_class is None or manifest_class == backup_class
        ):
            backups.append(
                {**manifest, "backup_class": manifest_class, "manifest_path": str(manifest_path)}
            )
    backups.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("backup_id", ""))), reverse=True)
    return ProductionReport(
        {"backup_root": str(root), "backup_class": backup_class, "count": len(backups), "backups": backups}
    )


def verify_backup(
    manifest_path: str | os.PathLike[str], *, expected_catalogue_uuid: str | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> ProductionReport:
    policy = safety_policy or PathSafetyPolicy()
    path = _validate_absolute_file(manifest_path, policy)
    manifest = _read_manifest(path)
    errors: list[str] = []
    if manifest.get("manifest_version") not in SUPPORTED_MANIFEST_VERSIONS:
        errors.append("unsupported manifest version")
    if manifest.get("status") != "accepted":
        errors.append("manifest is not accepted")
    manifest_class = _manifest_backup_class(manifest)
    if manifest.get("manifest_version") == 2:
        if manifest.get("backup_class") not in BACKUP_CLASSES:
            errors.append("manifest backup class is invalid")
        if manifest_class == "independent-local" and (
            manifest.get("device_independence") != "confirmed"
            or not manifest.get("source_device_identity")
            or not manifest.get("destination_device_identity")
            or manifest.get("source_device_identity") == manifest.get("destination_device_identity")
            or not manifest.get("destination_root_fingerprint")
        ):
            errors.append("independent backup device metadata is invalid")
    filename = manifest.get("backup_database_filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        errors.append("unsafe backup database filename")
        database = path.parent / "invalid"
    else:
        database = path.parent / filename
    if not errors and not database.is_file():
        errors.append("backup database is missing")
    digest = None
    check: dict[str, Any] = {"accepted": False, "integrity_check": "not run", "foreign_key_violations": -1}
    if not errors:
        digest = _sha256_file(database)
        if digest != manifest.get("backup_sha256"):
            errors.append("backup SHA-256 mismatch")
        manifest_uuid = str(manifest.get("source_catalogue_uuid", ""))
        expected = expected_catalogue_uuid or manifest_uuid
        if expected_catalogue_uuid is not None and manifest_uuid != expected_catalogue_uuid:
            errors.append("manifest catalogue UUID mismatch")
        check = _verify_database(
            database,
            expected_uuid=expected,
            require_production=True,
            policy=policy,
            immutable=True,
            expected_schema_version=(
                int(manifest["source_schema_version"])
                if isinstance(manifest.get("source_schema_version"), int)
                and 1 <= int(manifest["source_schema_version"]) <= CURRENT_SCHEMA_VERSION
                else CURRENT_SCHEMA_VERSION
            ),
        )
        errors.extend(str(item) for item in check["errors"])
        if check.get("identity") is not None and check["identity"]["catalogue_uuid"] != manifest_uuid:
            errors.append("backup database and manifest catalogue UUID mismatch")
        if check.get("schema_version") != manifest.get("source_schema_version"):
            errors.append("manifest schema version mismatch")
        manifest_counts = manifest.get("catalogue_counts")
        if manifest_counts is not None and manifest_counts != check["catalogue_counts"]:
            errors.append("manifest catalogue counts mismatch")
    return ProductionReport(
        {
            "result": "ACCEPTED" if not errors else "REJECTED",
            "manifest_path": str(path),
            "database_path": str(database),
            "backup_id": manifest.get("backup_id"),
            "backup_class": manifest_class,
            "manifest_version": manifest.get("manifest_version"),
            "source_catalogue_uuid": manifest.get("source_catalogue_uuid"),
            "source_schema_version": manifest.get("source_schema_version"),
            "sha256": digest,
            "integrity_check": check["integrity_check"],
            "foreign_key_violations": check["foreign_key_violations"],
            "catalogue_counts": check.get("catalogue_counts", {}),
            "errors": errors,
        }
    )


def retention_report(
    *, app_data_root: str | os.PathLike[str], keep_latest: int = DEFAULT_RETENTION_COUNT,
    backup_root: str | os.PathLike[str] | None = None, safety_policy: PathSafetyPolicy | None = None,
    backup_class: str | None = None,
) -> ProductionReport:
    if keep_latest < 1:
        raise ProductionError("Retention keep_latest must be at least 1.")
    listing = list_backups(
        app_data_root=app_data_root,
        backup_root=backup_root,
        backup_class=backup_class,
        safety_policy=safety_policy,
    ).values
    recognised = listing["backups"]
    candidates = [item["manifest_path"] for item in recognised[keep_latest:]]
    return ProductionReport(
        {
            "mode": "report-only",
            "keep_latest": keep_latest,
            "backup_class": backup_class,
            "recognised_successful_backups": len(recognised),
            "retention_candidates": candidates,
            "deleted": [],
            "unknown_files": "ignored",
        }
    )


def production_health(
    *, app_data_root: str | os.PathLike[str],
    independent_backup_root: str | os.PathLike[str] | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> ProductionReport:
    policy = safety_policy or PathSafetyPolicy()
    layout = application_data_layout(app_data_root, safety_policy=policy)
    warnings: list[str] = []
    failures: list[str] = []
    if not layout.catalogue_path.is_file():
        return ProductionReport({"summary": "FAIL", "catalogue_path": str(layout.catalogue_path), "failures": ["production catalogue is missing"]})
    try:
        check = _verify_database(layout.catalogue_path, expected_uuid=None, require_production=True, policy=policy)
        failures.extend(check["errors"])
        identity = _read_identity(layout.catalogue_path, policy)
        connection = connect_existing_catalogue(layout.catalogue_path, read_only=True, safety_policy=policy)
        try:
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
            counts = _health_counts(connection)
        finally:
            connection.close()
        backups = list_backups(app_data_root=layout.root, safety_policy=policy).values["backups"]
        latest = backups[0] if backups else None
        age_seconds = None
        if latest:
            age_seconds = max(0.0, (datetime.now(UTC) - _parse_utc(str(latest["created_at"]))).total_seconds())
            if age_seconds > DEFAULT_BACKUP_WARNING_AGE_SECONDS:
                warnings.append(
                    "latest accepted backup is older than the seven-day operational threshold"
                )
        else:
            warnings.append("no accepted backup exists")
        if counts["recovery_required_executions"]:
            warnings.append("one or more quarantine executions require recovery")
        summary = "FAIL" if failures else ("WARN" if warnings else "PASS")
        values: dict[str, Any] = {
                "summary": summary,
                "catalogue_path": str(layout.catalogue_path),
                "catalogue_uuid": identity["catalogue_uuid"],
                "role": identity["catalogue_role"],
                "schema_version": check["schema_version"],
                "file_size_bytes": layout.catalogue_path.stat().st_size,
                "journal_mode": journal_mode,
                "integrity_check": check["integrity_check"],
                "foreign_key_violations": check["foreign_key_violations"],
                "latest_successful_backup": None if latest is None else latest["backup_id"],
                "backup_age_seconds": age_seconds,
                "backup_warning_age_seconds": DEFAULT_BACKUP_WARNING_AGE_SECONDS,
                "backup_count": len(backups),
                **counts,
                "warnings": warnings,
                "failures": failures,
        }
        if independent_backup_root is not None:
            values["disaster_recovery"] = independent_backup_readiness(
                app_data_root=layout.root,
                independent_backup_root=independent_backup_root,
                safety_policy=policy,
            ).values
        else:
            values["disaster_recovery"] = {"summary": "NOT_ASSESSED"}
        return ProductionReport(values)
    except Exception as exc:
        return ProductionReport({"summary": "FAIL", "catalogue_path": str(layout.catalogue_path), "failures": [str(exc)]})


def independent_backup_readiness(
    *,
    app_data_root: str | os.PathLike[str],
    independent_backup_root: str | os.PathLike[str],
    safety_policy: PathSafetyPolicy | None = None,
) -> ProductionReport:
    """Assess independent catalogue DR readiness without changing catalogue health."""

    policy = safety_policy or PathSafetyPolicy()
    layout = application_data_layout(app_data_root, safety_policy=policy)
    try:
        root = _validate_absolute_root(independent_backup_root, policy)
        if not root.exists():
            return ProductionReport(
                {
                    "summary": "WARN",
                    "connected": False,
                    "independent_backup_root": str(root),
                    "reason": "independent backup root is unavailable",
                }
            )
        _validate_existing_directory(root, policy)
        listing = list_backups(
            app_data_root=layout.root,
            backup_root=root,
            backup_class="independent-local",
            safety_policy=policy,
        ).values
        backups = listing["backups"]
        if not backups:
            return ProductionReport(
                {
                    "summary": "WARN",
                    "connected": True,
                    "independent_backup_root": str(root),
                    "valid_independent_backup_count": 0,
                    "reason": "no accepted independent backup exists",
                }
            )
        identity = _read_identity(layout.catalogue_path, policy)
        verified_backups: list[tuple[dict[str, Any], dict[str, Any]]] = []
        rejected: list[dict[str, Any]] = []
        for backup in backups:
            verification = verify_backup(
                backup["manifest_path"],
                expected_catalogue_uuid=str(identity["catalogue_uuid"]),
                safety_policy=policy,
            ).values
            if verification["result"] == "ACCEPTED":
                verified_backups.append((backup, verification))
            else:
                rejected.append(verification)
        if not verified_backups:
            return ProductionReport(
                {
                    "summary": "FAIL",
                    "connected": True,
                    "independent_backup_root": str(root),
                    "valid_independent_backup_count": 0,
                    "rejected_backup_count": len(rejected),
                    "reason": "no independently verified backup is usable",
                }
            )
        latest, verified = verified_backups[0]
        age_seconds = max(
            0.0,
            (datetime.now(UTC) - _parse_utc(str(latest["created_at"]))).total_seconds(),
        )
        reasons: list[str] = []
        readiness = "PASS"
        if rejected:
            readiness = "WARN"
            reasons.append("one or more independent backup manifests were rejected")
        if age_seconds > DEFAULT_BACKUP_WARNING_AGE_SECONDS:
            readiness = "WARN"
            reasons.append("latest independent backup is older than seven days")
        return ProductionReport(
            {
                "summary": readiness,
                "connected": True,
                "independent_backup_root": str(root),
                "valid_independent_backup_count": len(verified_backups),
                "rejected_backup_count": len(rejected),
                "latest_backup_id": latest["backup_id"],
                "latest_manifest_path": latest["manifest_path"],
                "latest_database_filename": latest["backup_database_filename"],
                "latest_size_bytes": latest["backup_database_size_bytes"],
                "latest_sha256": latest["backup_sha256"],
                "latest_catalogue_uuid": latest["source_catalogue_uuid"],
                "latest_schema_version": latest["source_schema_version"],
                "latest_verification": verified["result"],
                "backup_age_seconds": age_seconds,
                "backup_warning_age_seconds": DEFAULT_BACKUP_WARNING_AGE_SECONDS,
                "reasons": reasons,
            }
        )
    except Exception as exc:
        return ProductionReport(
            {
                "summary": "WARN",
                "connected": False,
                "independent_backup_root": str(independent_backup_root),
                "reason": str(exc),
            }
        )


@_exclusive_operation
def recover_production(
    *, app_data_root: str | os.PathLike[str], manifest_path: str | os.PathLike[str],
    actor: str, confirm_restore_catalogue: bool,
    safety_policy: PathSafetyPolicy | None = None,
    _maintenance_state: dict | None = None,
) -> ProductionReport:
    if not confirm_restore_catalogue:
        raise ProductionError("Recovery requires --confirm-restore-catalogue.")
    if not actor.strip():
        raise ProductionError("Recovery actor must be explicit.")
    policy = safety_policy or PathSafetyPolicy()
    layout = application_data_layout(app_data_root, safety_policy=policy)
    _require_layout_catalogue(layout)
    current = _read_identity(layout.catalogue_path, policy)
    verification = verify_backup(
        manifest_path, expected_catalogue_uuid=str(current["catalogue_uuid"]), safety_policy=policy
    ).values
    if verification["result"] != "ACCEPTED":
        raise ProductionError(f"Recovery candidate rejected: {verification['errors']}")

    _create_validated_directory(layout.recovery_root, policy)
    assert _maintenance_state is not None
    attempt_id = str(_maintenance_state['attempt_id'])
    journal_path = layout.recovery_root / f"recovery-{attempt_id}.json"
    staged = layout.catalogue_dir / f".recovery-{attempt_id}.sqlite3"
    safeguarded = layout.catalogue_dir / f"pre-recovery-{attempt_id}.sqlite3"
    source_backup = Path(str(verification["database_path"]))
    journal: dict[str, Any] = {
        "journal_version": 2,
        "recovery_attempt_id": attempt_id,
        "timestamp": _utc_now(),
        "actor": actor,
        "source_backup": str(source_backup),
        "source_hash": verification["sha256"],
        "production_path": str(layout.catalogue_path),
        "staging_path": str(staged),
        "safeguarded_old_production_path": str(safeguarded),
        "result": "started",
    }
    _write_json_exclusive(journal_path, journal)
    started = time.perf_counter()
    try:
        safety_backup = create_backup(app_data_root=layout.root, reason=f"pre-recovery:{attempt_id}", safety_policy=policy)
        journal["pre_recovery_backup"] = safety_backup.values["manifest_path"]
        # Copy the validated immutable snapshot byte-for-byte. SQLite backup() can
        # change page metadata; exact bytes let us verify the promoted file while
        # keeping its Windows exclusion handle open throughout verification.
        with source_backup.open('rb') as source, staged.open('xb') as target:
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if _sha256_file(staged) != verification['sha256']:
            raise ProductionError('Recovery snapshot changed after backup verification.')
        staged_check = _verify_database(
            staged, expected_uuid=str(current['catalogue_uuid']),
            require_production=True, policy=policy, immutable=True,
        )
        if not staged_check['accepted']:
            raise ProductionError(f"Staged recovery verification failed: {staged_check['errors']}")
        selected_logical = _snapshot_logical_digest(source_backup, policy)
        if _snapshot_logical_digest(staged, policy) != selected_logical:
            raise ProductionError('Staged recovery does not match the selected logical snapshot.')
        journal['selected_logical_sha256'] = selected_logical
        with ExitStack() as locks:
            originals = []
            for suffix in ('', '-wal', '-shm'):
                old = Path(f'{layout.catalogue_path}{suffix}')
                if old.exists():
                    stream = locks.enter_context(exclusive_file(old))
                    originals.append((old, Path(f'{safeguarded}{suffix}'), stream))
            replacement = locks.enter_context(exclusive_file(staged))
            if stream_sha256(replacement) != verification['sha256']:
                raise ProductionError('Staged snapshot changed before exclusive promotion.')
            journal['original_files'] = [
                {'original': str(old), 'preserved': str(saved), 'sha256': stream_sha256(stream)}
                for old, saved, stream in originals
            ]
            journal['old_production_sha256'] = journal['original_files'][0]['sha256']
            moved = []
            promoted = False
            try:
                for old, saved, stream in originals:
                    journal['phase'] = f'preserving:{old.name}'
                    _replace_json(journal_path, journal)
                    publish_no_replace(old, saved)
                    moved.append((old, saved, stream))
                journal['phase'] = 'promoting-selected-snapshot'
                _replace_json(journal_path, journal)
                publish_no_replace(staged, layout.catalogue_path)
                promoted = True
                _verify_promoted_snapshot(layout.catalogue_path, replacement, verification['sha256'])
                # Exact final bytes, no live sidecars, and the staged logical
                # comparison establish equality to the selected snapshot rather
                # than merely an internally consistent but incorrect database.
                journal.update({
                    'result': 'succeeded', 'phase': 'verified', 'finished_at': _utc_now(),
                    'integrity_check': staged_check['integrity_check'],
                    'foreign_key_violations': staged_check['foreign_key_violations'],
                    'final_snapshot_sha256': verification['sha256'],
                    'final_logical_sha256': selected_logical,
                    'recovery_staging_seconds': round(time.perf_counter() - started, 6),
                })
                _replace_json(journal_path, journal)
            except BaseException:
                try:
                    if promoted:
                        if layout.catalogue_path.stat().st_ino != os.fstat(replacement.fileno()).st_ino:
                            raise ProductionError('Replacement identity changed; automatic rollback refused.')
                        publish_no_replace(layout.catalogue_path, layout.catalogue_dir / f'failed-recovery-{attempt_id}.sqlite3')
                    # Restore sidecars before the main file; never overwrite an
                    # intervening file. Original handles still exclude SQLite.
                    for old, saved, stream in reversed(moved):
                        publish_no_replace(saved, old)
                        if stream_sha256(stream) != next(item['sha256'] for item in journal['original_files'] if item['original'] == str(old)):
                            raise ProductionError('Rollback evidence hash mismatch.')
                    journal['rollback'] = 'restored-original-file-set'
                except BaseException as rollback_error:
                    assert _maintenance_state is not None
                    _maintenance_state['retain'] = True
                    journal['rollback'] = 'offline-recovery-required'
                    journal['rollback_error'] = str(rollback_error)
                raise
        return ProductionReport({**journal, 'journal_path': str(journal_path)})
    except BaseException as exc:
        journal.update({'result': 'failed', 'finished_at': _utc_now(), 'error': str(exc)})
        _replace_json(journal_path, journal)
        # Staging, failed replacement and old DB/WAL/SHM evidence are retained.
        raise


def _snapshot_logical_digest(path: Path, policy: PathSafetyPolicy) -> str:
    connection = _connect_immutable_snapshot(path, policy)
    try:
        digest = hashlib.sha256()
        for statement in connection.iterdump():
            digest.update(statement.encode('utf-8'))
            digest.update(b'\n')
        return digest.hexdigest()
    finally:
        connection.close()


def _verify_promoted_snapshot(path: Path, stream, expected_sha256: str) -> None:
    if path.stat().st_ino != os.fstat(stream.fileno()).st_ino:
        raise ProductionError('Final snapshot file identity mismatch.')
    if any(Path(f'{path}{suffix}').exists() for suffix in ('-wal', '-shm')):
        raise ProductionError('Unexpected live SQLite sidecar during final verification.')
    if stream_sha256(stream) != expected_sha256:
        raise ProductionError('Final catalogue differs from the selected snapshot.')


def _verify_database(
    path: Path, *, expected_uuid: str | None, require_production: bool,
    policy: PathSafetyPolicy, immutable: bool = False,
    expected_schema_version: int = CURRENT_SCHEMA_VERSION,
) -> dict[str, Any]:
    errors: list[str] = []
    integrity = "not run"
    violations = -1
    schema: int | None = None
    identity: dict[str, Any] | None = None
    catalogue_counts: dict[str, int] = {}
    try:
        connection = (
            _connect_immutable_snapshot(path, policy)
            if immutable
            else connect_existing_catalogue(path, read_only=True, safety_policy=policy)
        )
        try:
            schema = read_schema_version(connection)
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
            row = connection.execute("SELECT * FROM catalogue_identity WHERE singleton_id = 1").fetchone()
            if row is None:
                errors.append("catalogue identity is missing")
            else:
                identity = dict(row)
            catalogue_counts = _catalogue_baseline_counts(connection)
        finally:
            connection.close()
    except Exception as exc:
        errors.append(str(exc))
    if schema != expected_schema_version:
        errors.append(
            f"schema version {schema} does not match expected version {expected_schema_version}"
        )
    if integrity != "ok":
        errors.append(f"integrity_check returned {integrity}")
    if violations != 0:
        errors.append(f"foreign_key_check returned {violations} row(s)")
    if identity is not None:
        if expected_uuid is not None and identity["catalogue_uuid"] != expected_uuid:
            errors.append("catalogue UUID mismatch")
        if require_production and identity["catalogue_role"] != "production":
            errors.append("catalogue role is not production")
    return {
        "accepted": not errors,
        "errors": errors,
        "schema_version": schema,
        "integrity_check": integrity,
        "foreign_key_violations": violations,
        "identity": identity,
        "catalogue_counts": catalogue_counts,
    }


def _configure_production_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
    if mode != "wal":
        raise ProductionError(f"Could not enable production WAL journal mode (found {mode}).")
    connection.execute("PRAGMA synchronous = FULL")


def _connect_immutable_snapshot(path: Path, policy: PathSafetyPolicy) -> sqlite3.Connection:
    """Open a completed static snapshot without creating WAL/SHM runtime files."""

    result = policy.check_path(str(path), intent=PathIntent.READ)
    if not result.allowed:
        raise ProductionError(f"Unsafe snapshot path ({result.code}): {result.reason}")
    if not path.is_file():
        raise ProductionError(f"Snapshot database does not exist: {path}")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro&immutable=1", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        read_schema_version(connection)
        return connection
    except (OSError, sqlite3.Error, ValueError) as exc:
        if connection is not None:
            connection.close()
        raise ProductionError(f"Cannot open immutable snapshot '{path}': {exc}") from exc


def _read_identity(path: Path, policy: PathSafetyPolicy) -> dict[str, Any]:
    connection = connect_existing_catalogue(path, read_only=True, safety_policy=policy)
    try:
        row = connection.execute("SELECT * FROM catalogue_identity WHERE singleton_id = 1").fetchone()
        if row is None:
            raise ProductionError("Catalogue has no production identity metadata.")
        return dict(row)
    finally:
        connection.close()


def _health_counts(connection: sqlite3.Connection) -> dict[str, int]:
    def count(table: str, where: str = "") -> int:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}" {where}').fetchone()[0])
    return {
        "decision_event_count": count("decision_events"),
        "action_plan_count": count("action_plans"),
        "action_execution_count": count("action_executions"),
        "action_execution_event_count": count("action_execution_events"),
        "recovery_required_executions": count("action_executions", "WHERE status = 'recovery_required'"),
    }


def _catalogue_baseline_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "inventory_observations",
        "physical_instances",
        "content_identities",
        "exact_duplicate_groups",
        "similarity_relationships",
        "similarity_groups",
    )
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def _create_layout(layout: ApplicationDataLayout, policy: PathSafetyPolicy) -> None:
    _create_validated_directory(layout.root, policy)
    for path in (
        layout.catalogue_dir, layout.backup_root, layout.logs_root,
        layout.exports_root, layout.state_root, layout.recovery_root,
    ):
        _create_validated_directory(path, policy, approved_root=layout.root)


def _create_validated_directory(
    path: Path, policy: PathSafetyPolicy, *, approved_root: Path | None = None,
) -> None:
    root = approved_root or path
    if path.exists():
        _validate_existing_directory(path, policy)
        if approved_root is not None:
            result = assess_write_destination(approved_root, path / "boundary-check", safety_policy=policy)
            if not result.allowed:
                raise ProductionError(f"Unsafe application-data directory ({result.code}): {result.reason}")
        return
    parent = path.parent
    if not parent.exists():
        if approved_root is None:
            raise ProductionError(
                f"Parent of the explicit root must already exist; refusing to create outside it: {parent}"
            )
        _create_validated_directory(parent, policy, approved_root=approved_root)
    boundary_root = approved_root or parent
    result = assess_write_destination(boundary_root, path, safety_policy=policy)
    if not result.allowed:
        raise ProductionError(f"Unsafe directory creation ({result.code}): {result.reason}")
    path.mkdir()
    _validate_existing_directory(path, policy)


def _validate_existing_directory(path: Path, policy: PathSafetyPolicy) -> None:
    result = policy.check_path(str(path), intent=PathIntent.WRITE)
    if not result.allowed:
        raise ProductionError(f"Unsafe directory ({result.code}): {result.reason}")
    if not path.is_dir() or path.is_symlink():
        raise ProductionError(f"Expected an ordinary directory: {path}")
    boundary = assess_write_destination(path, path / "boundary-check", safety_policy=policy)
    if not boundary.allowed:
        raise ProductionError(f"Unsafe resolved directory ({boundary.code}): {boundary.reason}")


def _validate_absolute_root(raw: str | os.PathLike[str], policy: PathSafetyPolicy) -> Path:
    text = os.fspath(raw)
    if not isinstance(text, str) or not text.strip():
        raise ProductionError("Application-data/backup root must be explicit and non-empty.")
    result = policy.check_path(text, intent=PathIntent.WRITE)
    if not result.allowed:
        raise ProductionError(f"Unsafe root ({result.code}): {result.reason}")
    candidate = text.replace("/", "\\")
    drive, tail = ntpath.splitdrive(candidate)
    if not ((len(drive) == 2 and drive[1] == ":" and tail.startswith("\\")) or (candidate.startswith("\\\\") and bool(drive))):
        raise ProductionError("Application-data/backup root must be an absolute Windows drive or UNC path.")
    if ".." in tail.split("\\"):
        raise ProductionError("Application-data/backup root must not contain parent traversal.")
    return Path(text)


def _validate_absolute_file(raw: str | os.PathLike[str], policy: PathSafetyPolicy) -> Path:
    path = _validate_absolute_root(raw, policy)
    if not path.is_file():
        raise ProductionError(f"File does not exist: {path}")
    return path


def _require_layout_catalogue(layout: ApplicationDataLayout) -> None:
    if not layout.catalogue_path.is_file():
        raise ProductionError(f"Production catalogue does not exist: {layout.catalogue_path}")


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionError(f"Cannot read backup manifest '{path}': {exc}") from exc
    if not isinstance(value, dict):
        raise ProductionError("Backup manifest must be a JSON object.")
    return value


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ProductionError(f"Cannot create journal/manifest '{path}': {exc}") from exc


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
    _write_json_exclusive(temporary, value)
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _root_fingerprint(root: Path) -> str:
    normalised = ntpath.normcase(ntpath.normpath(str(root).replace("/", "\\")))
    return hashlib.sha256(f"app-data-root-v1\0{normalised}".encode("utf-8")).hexdigest()


def _same_path(left: Path, right: Path) -> bool:
    return ntpath.normcase(ntpath.normpath(str(left))) == ntpath.normcase(ntpath.normpath(str(right)))


def _windows_path_within(path: Path, root: Path) -> bool:
    try:
        return ntpath.commonpath(
            [ntpath.normcase(ntpath.normpath(str(path))), ntpath.normcase(ntpath.normpath(str(root)))]
        ) == ntpath.normcase(ntpath.normpath(str(root)))
    except ValueError:
        return False


def _manifest_backup_class(manifest: Mapping[str, Any]) -> str:
    value = manifest.get("backup_class")
    return str(value) if value in BACKUP_CLASSES else "operational-local"


def _physical_device_identity(path: Path) -> str | None:
    """Return a stable host device number when measurable, without enumerating other storage."""

    if sys.platform != "win32":
        try:
            return f"volume-device:{path.stat().st_dev}"
        except OSError:
            return None
    drive, _ = ntpath.splitdrive(str(path))
    if len(drive) != 2 or drive[1] != ":":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class StorageDeviceNumber(ctypes.Structure):
            _fields_ = (
                ("device_type", wintypes.DWORD),
                ("device_number", wintypes.DWORD),
                ("partition_number", wintypes.DWORD),
            )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateFileW(
            f"\\\\.\\{drive}",
            0,
            0x00000001 | 0x00000002,
            None,
            3,
            0,
            None,
        )
        invalid_handle = wintypes.HANDLE(-1).value
        if handle == invalid_handle:
            return None
        try:
            number = StorageDeviceNumber()
            returned = wintypes.DWORD()
            ok = kernel32.DeviceIoControl(
                handle,
                0x002D1080,
                None,
                0,
                ctypes.byref(number),
                ctypes.sizeof(number),
                ctypes.byref(returned),
                None,
            )
            if not ok:
                return None
            return f"windows-storage-device:{number.device_number}"
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _remove_file_if_present(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _remove_empty_sqlite_sidecars(path: Path) -> None:
    """Remove only closed, generated staging sidecars after a successful checkpoint."""

    wal = Path(f"{path}-wal")
    shm = Path(f"{path}-shm")
    if wal.exists() and wal.stat().st_size != 0:
        raise ProductionError(f"Refusing promotion while staging WAL contains data: {wal}")
    for sidecar in (wal, shm):
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            raise ProductionError(f"Cannot remove generated staging sidecar '{sidecar}': {exc}") from exc
