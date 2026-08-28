"""Import the verified M10 SHA-256 and exact-duplicate evidence."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from personal_librarian.catalogue.errors import EvidenceValidationError
from personal_librarian.catalogue.models import windows_path_comparison_key
from personal_librarian.catalogue.importers.common import (
    DEFAULT_BASELINES,
    StageReport,
    build_stage_report,
    completed_stage,
    fingerprint_files,
    get_or_create_analysis_run,
    get_or_create_batch,
    get_or_create_source,
    iter_csv,
    parse_nonnegative_int,
    parse_timestamp,
    record_completed_stage,
    require_reconciliation,
    stable_key,
    stage_transaction,
    validate_input_file,
    validate_sha256,
)

STAGE_KEY = "m10-sha256-exact-duplicates-v1"
RUN_KEY = "m10:sha256-exact-duplicates:verified-20260819"
MANIFEST_HEADERS = (
    "Source", "RelativePath", "AbsolutePath", "Extension", "SizeBytes", "ModTime",
    "SHA256", "HashStatus",
)
GROUP_HEADERS = (
    "SHA256", "Copies", "UniqueSources", "SourcePattern", "SizeBytes",
    "RedundantCopies", "ReclaimableBytes",
)
ROW_HEADERS = ("SHA256", "Copies", "Source", "RelativePath", "SizeBytes")


def _content_identity(connection: sqlite3.Connection, sha256: str, run_id: int) -> int:
    identity_key = f"sha256:{sha256}"
    connection.execute(
        """
        INSERT INTO content_identities(identity_key, created_by_analysis_run_id)
        VALUES (?, ?) ON CONFLICT(identity_key) DO NOTHING
        """,
        (identity_key, run_id),
    )
    row = connection.execute(
        "SELECT content_identity_id FROM content_identities WHERE identity_key = ?",
        (identity_key,),
    ).fetchone()
    assert row is not None
    content_id = int(row[0])
    connection.execute(
        """
        INSERT INTO content_identity_hashes(
            content_identity_id, algorithm, hash_value, analysis_run_id
        ) VALUES (?, 'SHA-256', ?, ?)
        ON CONFLICT(content_identity_id, algorithm, hash_value) DO NOTHING
        """,
        (content_id, sha256, run_id),
    )
    return content_id


def import_m10(
    connection: sqlite3.Connection,
    manifest_path: str | Path,
    groups_path: str | Path,
    rows_path: str | Path,
    *,
    baseline: Mapping[str, Any] | None = None,
) -> StageReport:
    """Import M10 evidence and create authoritative physical-instance records."""

    manifest = validate_input_file(manifest_path)
    groups = validate_input_file(groups_path)
    duplicate_rows = validate_input_file(rows_path)
    fingerprint = fingerprint_files(
        {"manifest": manifest, "groups": groups, "rows": duplicate_rows}
    )
    prior = completed_stage(connection, STAGE_KEY, fingerprint)
    if prior is not None:
        return prior
    expected = dict(DEFAULT_BASELINES["m10"] if baseline is None else baseline)

    manifest_rows = valid_sha256 = invalid_sha256 = 0
    exact_links = unique_metadata_links = 0
    group_count = membership_count = redundant_copies = reclaimable_bytes = 0

    try:
        with stage_transaction(connection):
            run_id = get_or_create_analysis_run(
                connection,
                run_key=RUN_KEY,
                analysis_kind="cryptographic_hash_and_exact_duplicates",
                algorithm="SHA-256",
                algorithm_version="M10",
                parameters={"import_stage": STAGE_KEY, "hash_status_required": "Hashed"},
            )

            inventory_exact: dict[tuple[int, str], int] = {}
            inventory_metadata: dict[tuple[int, int, str, str | None], list[int]] = defaultdict(list)
            for item in connection.execute(
                """
                SELECT inventory_observation_id, source_id, raw_relative_path,
                       size_bytes, extension, observed_modified_at
                FROM inventory_observations
                """
            ):
                inventory_id, source_id, raw_path, size, extension, mod_time = item
                inventory_exact[(int(source_id), str(raw_path))] = int(inventory_id)
                inventory_metadata[(int(source_id), int(size), str(extension or ""), mod_time)].append(
                    int(inventory_id)
                )

            manifest_metadata: Counter[tuple[int, int, str, str | None]] = Counter()
            unmatched: list[tuple[int, tuple[int, int, str, str | None]]] = []
            instances: dict[tuple[int, str], tuple[int, int, int]] = {}

            for ordinal, row in iter_csv(manifest, MANIFEST_HEADERS):
                source_label = row["Source"]
                relative_path = row["RelativePath"]
                if not source_label or not relative_path:
                    raise EvidenceValidationError(
                        f"Row {ordinal}: Source and RelativePath are required."
                    )
                size = parse_nonnegative_int(row["SizeBytes"], "SizeBytes", ordinal)
                mod_time, timestamp_state = parse_timestamp(row["ModTime"], "ModTime", ordinal)
                if row["HashStatus"] != "Hashed":
                    invalid_sha256 += 1
                    raise EvidenceValidationError(
                        f"Row {ordinal}: HashStatus must be 'Hashed', found {row['HashStatus']!r}."
                    )
                sha256 = validate_sha256(row["SHA256"], "SHA256", ordinal)
                valid_sha256 += 1
                source_id = get_or_create_source(connection, source_label)
                batch_id = get_or_create_batch(connection, source_id, "m10")
                content_id = _content_identity(connection, sha256, run_id)
                instance_key = stable_key("m10-physical-instance-v1", source_label, relative_path)
                connection.execute(
                    """
                    INSERT INTO physical_instances(
                        instance_key, source_id, acquisition_batch_id, content_identity_id,
                        raw_relative_path, display_path, relative_path_comparison_key,
                        path_comparison_key_version, current_observed_path, size_bytes,
                        extension, observed_modified_at, first_observed_analysis_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'windows-casefold-v1', ?, ?, ?, ?, ?)
                    """,
                    (
                        instance_key, source_id, batch_id, content_id, relative_path,
                        relative_path, windows_path_comparison_key(relative_path),
                        row["AbsolutePath"] or None, size, row["Extension"], mod_time, run_id,
                    ),
                )
                instance_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO hash_observations(
                        physical_instance_id, analysis_run_id, algorithm, algorithm_version,
                        hash_value
                    ) VALUES (?, ?, 'SHA-256', 'M10', ?)
                    """,
                    (instance_id, run_id, sha256),
                )
                connection.execute(
                    """
                    INSERT INTO instance_path_observations(
                        observation_key, physical_instance_id, analysis_run_id, evidence_layer,
                        raw_relative_path, absolute_path, relative_path_comparison_key,
                        path_comparison_key_version, observed_modified_at, timestamp_state,
                        is_authoritative_current
                    ) VALUES (?, ?, ?, 'M10', ?, ?, ?, 'windows-casefold-v1', ?, ?, 1)
                    """,
                    (
                        stable_key("m10-path-observation-v1", source_label, relative_path),
                        instance_id, run_id, relative_path, row["AbsolutePath"] or None,
                        windows_path_comparison_key(relative_path), mod_time, timestamp_state,
                    ),
                )
                instances[(source_id, relative_path)] = (instance_id, content_id, size)

                metadata_key = (source_id, size, row["Extension"], mod_time)
                manifest_metadata[metadata_key] += 1
                inventory_id = inventory_exact.get((source_id, relative_path))
                if inventory_id is not None:
                    connection.execute(
                        """
                        UPDATE inventory_observations
                        SET matched_physical_instance_id = ?, match_method = 'exact_path'
                        WHERE inventory_observation_id = ?
                        """,
                        (instance_id, inventory_id),
                    )
                    exact_links += 1
                else:
                    unmatched.append((instance_id, metadata_key))
                manifest_rows += 1

            for instance_id, metadata_key in unmatched:
                candidates = inventory_metadata.get(metadata_key, [])
                if len(candidates) == 1 and manifest_metadata[metadata_key] == 1:
                    cursor = connection.execute(
                        """
                        UPDATE inventory_observations
                        SET matched_physical_instance_id = ?, match_method = 'unique_metadata'
                        WHERE inventory_observation_id = ? AND matched_physical_instance_id IS NULL
                        """,
                        (instance_id, candidates[0]),
                    )
                    if cursor.rowcount == 1:
                        unique_metadata_links += 1

            group_ids: dict[str, tuple[int, int]] = {}
            for ordinal, row in iter_csv(groups, GROUP_HEADERS):
                sha256 = validate_sha256(row["SHA256"], "SHA256", ordinal)
                identity = connection.execute(
                    """SELECT content_identity_id FROM content_identity_hashes
                       WHERE algorithm = 'SHA-256' AND hash_value = ?""",
                    (sha256,),
                ).fetchone()
                if identity is None:
                    raise EvidenceValidationError(
                        f"M10 groups row {ordinal}: SHA-256 is absent from the manifest."
                    )
                copies = parse_nonnegative_int(row["Copies"], "Copies", ordinal)
                unique_sources = parse_nonnegative_int(
                    row["UniqueSources"], "UniqueSources", ordinal
                )
                size = parse_nonnegative_int(row["SizeBytes"], "SizeBytes", ordinal)
                redundant = parse_nonnegative_int(
                    row["RedundantCopies"], "RedundantCopies", ordinal
                )
                reclaimable = parse_nonnegative_int(
                    row["ReclaimableBytes"], "ReclaimableBytes", ordinal
                )
                if copies < 2 or redundant != copies - 1 or reclaimable != redundant * size:
                    raise EvidenceValidationError(
                        f"M10 groups row {ordinal}: duplicate aggregate is inconsistent."
                    )
                connection.execute(
                    """
                    INSERT INTO exact_duplicate_groups(
                        group_key, content_identity_id, analysis_run_id, copies,
                        unique_sources, source_pattern, size_bytes, redundant_copies,
                        reclaimable_bytes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"sha256:{sha256}", int(identity[0]), run_id, copies,
                        unique_sources, row["SourcePattern"], size, redundant, reclaimable,
                    ),
                )
                group_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
                group_ids[sha256] = (group_id, copies)
                group_count += 1
                redundant_copies += redundant
                reclaimable_bytes += reclaimable

            membership_tallies: Counter[str] = Counter()
            for ordinal, row in iter_csv(duplicate_rows, ROW_HEADERS):
                sha256 = validate_sha256(row["SHA256"], "SHA256", ordinal)
                group = group_ids.get(sha256)
                if group is None:
                    raise EvidenceValidationError(
                        f"M10 duplicate rows row {ordinal}: group is absent."
                    )
                source_id = get_or_create_source(connection, row["Source"])
                instance = instances.get((source_id, row["RelativePath"]))
                copies = parse_nonnegative_int(row["Copies"], "Copies", ordinal)
                size = parse_nonnegative_int(row["SizeBytes"], "SizeBytes", ordinal)
                if instance is None or copies != group[1] or size != instance[2]:
                    raise EvidenceValidationError(
                        f"M10 duplicate rows row {ordinal}: membership does not match manifest/group."
                    )
                manifest_sha = connection.execute(
                    """
                    SELECT hash_value FROM content_identity_hashes
                    WHERE content_identity_id = ? AND algorithm = 'SHA-256'
                    """,
                    (instance[1],),
                ).fetchone()
                if manifest_sha is None or manifest_sha[0] != sha256:
                    raise EvidenceValidationError(
                        f"M10 duplicate rows row {ordinal}: SHA-256 does not match manifest."
                    )
                connection.execute(
                    """
                    INSERT INTO exact_duplicate_memberships(
                        exact_duplicate_group_id, physical_instance_id, reported_copies
                    ) VALUES (?, ?, ?)
                    """,
                    (group[0], instance[0], copies),
                )
                membership_tallies[sha256] += 1
                membership_count += 1

            for sha256, (_, copies) in group_ids.items():
                if membership_tallies[sha256] != copies:
                    raise EvidenceValidationError(
                        f"M10 group {sha256} reports {copies} copies but has "
                        f"{membership_tallies[sha256]} membership rows."
                    )

            actual: dict[str, object] = {
                "manifest_rows": manifest_rows,
                "valid_sha256": valid_sha256,
                "invalid_sha256": invalid_sha256,
                "physical_instances_mapped": len(instances),
                "distinct_content_identities": int(connection.execute(
                    "SELECT COUNT(DISTINCT content_identity_id) FROM physical_instances"
                ).fetchone()[0]),
                "exact_duplicate_groups": group_count,
                "duplicate_memberships": membership_count,
                "redundant_copies": redundant_copies,
                "reclaimable_bytes": reclaimable_bytes,
                "m9_exact_path_links": exact_links,
                "m9_unique_metadata_links": unique_metadata_links,
                "m9_unlinked_observations": int(connection.execute(
                    "SELECT COUNT(*) FROM inventory_observations "
                    "WHERE matched_physical_instance_id IS NULL"
                ).fetchone()[0]),
            }
            report = build_stage_report(STAGE_KEY, actual, expected)
            require_reconciliation(report)
            record_completed_stage(
                connection,
                stage_key=STAGE_KEY,
                importer_name=__name__,
                analysis_run_id=run_id,
                fingerprint=fingerprint,
                report=report,
            )
    except sqlite3.Error as exc:
        raise EvidenceValidationError(f"M10 import failed: {exc}") from exc

    return report
