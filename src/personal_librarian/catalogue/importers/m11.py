"""Import verified M11 dual-hash review evidence without merging identities."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from personal_librarian.catalogue.errors import EvidenceValidationError
from personal_librarian.catalogue.importers.common import (
    DEFAULT_BASELINES,
    StageReport,
    build_stage_report,
    completed_stage,
    fingerprint_files,
    get_or_create_analysis_run,
    iter_csv,
    parse_nonnegative_int,
    record_completed_stage,
    require_reconciliation,
    stable_key,
    stage_transaction,
    validate_input_file,
    validate_sha256,
)

STAGE_KEY = "m11-dualhash-review-v1"
RUN_KEY = "m11:dualhash-review:verified-20260820"
DUALHASH_HEADERS = (
    "SHA256", "PHash", "RepresentativePath", "Source", "Copies", "DHash",
    "DHashStatus", "DHashError",
)
PAIR_HEADERS = (
    "Distance", "SHA256_A", "SHA256_B", "PHash_A", "PHash_B", "Source_A",
    "Source_B", "Copies_A", "Copies_B", "RepresentativePath_A",
    "RepresentativePath_B", "DHash_A", "DHash_B", "DHashDistance",
)
GROUP_HEADERS = PAIR_HEADERS + ("GroupID",)
SUMMARY_HEADERS = (
    "GroupID", "UniqueContents", "CandidatePairs", "MinPHashDistance",
    "MaxPHashDistance", "MinDHashDistance", "MaxDHashDistance", "UniqueSources",
    "Sources",
)


def _perceptual_hash(value: str, field: str, ordinal: int) -> str:
    normalised = value.lower()
    if len(normalised) != 16 or any(character not in "0123456789abcdef" for character in normalised):
        raise EvidenceValidationError(
            f"Row {ordinal}: {field} is not a 64-bit hexadecimal perceptual hash."
        )
    return normalised


def _content_id(connection: sqlite3.Connection, sha256: str, ordinal: int) -> int:
    row = connection.execute(
        """
        SELECT content_identity_id FROM content_identity_hashes
        WHERE algorithm = 'SHA-256' AND hash_value = ?
        """,
        (sha256,),
    ).fetchone()
    if row is None:
        raise EvidenceValidationError(
            f"Row {ordinal}: SHA-256 {sha256} is absent from imported M10 evidence."
        )
    return int(row[0])


def _parse_pair(row: Mapping[str, str], ordinal: int) -> dict[str, object]:
    sha_a = validate_sha256(row["SHA256_A"], "SHA256_A", ordinal)
    sha_b = validate_sha256(row["SHA256_B"], "SHA256_B", ordinal)
    if sha_a == sha_b:
        raise EvidenceValidationError(f"Row {ordinal}: similarity pair repeats one SHA-256.")
    phash_a = _perceptual_hash(row["PHash_A"], "PHash_A", ordinal)
    phash_b = _perceptual_hash(row["PHash_B"], "PHash_B", ordinal)
    dhash_a = _perceptual_hash(row["DHash_A"], "DHash_A", ordinal)
    dhash_b = _perceptual_hash(row["DHash_B"], "DHash_B", ordinal)
    phash_distance = parse_nonnegative_int(row["Distance"], "Distance", ordinal)
    dhash_distance = parse_nonnegative_int(row["DHashDistance"], "DHashDistance", ordinal)
    if phash_distance > 4 or dhash_distance > 4:
        raise EvidenceValidationError(
            f"Row {ordinal}: pair exceeds the recorded M11 pHash/dHash distance limits."
        )
    if (int(phash_a, 16) ^ int(phash_b, 16)).bit_count() != phash_distance:
        raise EvidenceValidationError(f"Row {ordinal}: pHash distance is inconsistent.")
    if (int(dhash_a, 16) ^ int(dhash_b, 16)).bit_count() != dhash_distance:
        raise EvidenceValidationError(f"Row {ordinal}: dHash distance is inconsistent.")
    key = tuple(sorted((sha_a, sha_b)))
    return {
        "key": key,
        "sha_a": sha_a,
        "sha_b": sha_b,
        "phash_distance": phash_distance,
        "dhash_distance": dhash_distance,
        "signature": tuple(row[name] for name in PAIR_HEADERS),
    }


def import_m11(
    connection: sqlite3.Connection,
    dualhash_path: str | Path,
    pairs_path: str | Path,
    groups_path: str | Path,
    summary_path: str | Path,
    *,
    baseline: Mapping[str, Any] | None = None,
) -> StageReport:
    """Import M11 content hashes, candidate pairs, and review-only groups."""

    dualhash = validate_input_file(dualhash_path)
    pairs = validate_input_file(pairs_path)
    groups = validate_input_file(groups_path)
    summary = validate_input_file(summary_path)
    fingerprint = fingerprint_files(
        {"dualhash": dualhash, "pairs": pairs, "groups": groups, "summary": summary}
    )
    prior = completed_stage(connection, STAGE_KEY, fingerprint)
    if prior is not None:
        return prior
    expected = dict(DEFAULT_BASELINES["m11"] if baseline is None else baseline)

    dualhash_count = phashed_copies = dhash_coverage = pair_count = group_count = 0
    try:
        with stage_transaction(connection):
            run_id = get_or_create_analysis_run(
                connection,
                run_key=RUN_KEY,
                analysis_kind="perceptual_similarity_review",
                algorithm="pHash+dHash",
                algorithm_version="M11",
                parameters={
                    "import_stage": STAGE_KEY,
                    "phash_max_distance": 4,
                    "dhash_max_distance": 4,
                    "effect": "review_only_no_identity_merge",
                },
            )

            dualhash_values: dict[str, tuple[str, str]] = {}
            for ordinal, row in iter_csv(dualhash, DUALHASH_HEADERS):
                sha256 = validate_sha256(row["SHA256"], "SHA256", ordinal)
                if sha256 in dualhash_values:
                    raise EvidenceValidationError(f"M11 dualhash row {ordinal}: duplicate SHA-256.")
                content_id = _content_id(connection, sha256, ordinal)
                phash = _perceptual_hash(row["PHash"], "PHash", ordinal)
                copies = parse_nonnegative_int(row["Copies"], "Copies", ordinal)
                if copies < 1:
                    raise EvidenceValidationError(f"M11 dualhash row {ordinal}: Copies must be positive.")
                dhash_status = row["DHashStatus"]
                dhash = None
                if dhash_status == "Hashed":
                    dhash = _perceptual_hash(row["DHash"], "DHash", ordinal)
                    dhash_coverage += 1
                elif row["DHash"]:
                    raise EvidenceValidationError(
                        f"M11 dualhash row {ordinal}: non-Hashed row contains DHash."
                    )
                connection.execute(
                    """
                    INSERT INTO content_hash_observations(
                        observation_key, content_identity_id, analysis_run_id, algorithm,
                        algorithm_version, hash_value, status, error, representative_path,
                        representative_source, reported_copies
                    ) VALUES (?, ?, ?, 'pHash', 'M11', ?, 'Hashed', NULL, ?, ?, ?)
                    """,
                    (
                        stable_key("m11-content-hash-v1", sha256, "pHash"), content_id,
                        run_id, phash, row["RepresentativePath"], row["Source"], copies,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO content_hash_observations(
                        observation_key, content_identity_id, analysis_run_id, algorithm,
                        algorithm_version, hash_value, status, error, representative_path,
                        representative_source, reported_copies
                    ) VALUES (?, ?, ?, 'dHash', 'M11', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_key("m11-content-hash-v1", sha256, "dHash"), content_id,
                        run_id, dhash, dhash_status, row["DHashError"] or None,
                        row["RepresentativePath"], row["Source"], copies,
                    ),
                )
                dualhash_values[sha256] = (phash, dhash or "")
                dualhash_count += 1
                phashed_copies += copies

            pair_rows: dict[tuple[str, str], dict[str, object]] = {}
            relationship_ids: dict[tuple[str, str], int] = {}
            for ordinal, row in iter_csv(pairs, PAIR_HEADERS):
                parsed = _parse_pair(row, ordinal)
                key = parsed["key"]
                assert isinstance(key, tuple)
                if key in pair_rows:
                    raise EvidenceValidationError(f"M11 pairs row {ordinal}: duplicate pair.")
                sha_a = str(parsed["sha_a"])
                sha_b = str(parsed["sha_b"])
                expected_a = dualhash_values.get(sha_a)
                expected_b = dualhash_values.get(sha_b)
                if expected_a is None or expected_b is None:
                    raise EvidenceValidationError(
                        f"M11 pairs row {ordinal}: pair content is absent from dualhash evidence."
                    )
                if (row["PHash_A"].lower(), row["DHash_A"].lower()) != expected_a or (
                    row["PHash_B"].lower(), row["DHash_B"].lower()
                ) != expected_b:
                    raise EvidenceValidationError(
                        f"M11 pairs row {ordinal}: hashes differ from dualhash evidence."
                    )
                left, right = sorted(
                    (_content_id(connection, sha_a, ordinal), _content_id(connection, sha_b, ordinal))
                )
                relationship_key = stable_key("m11-similarity-pair-v1", *key)
                connection.execute(
                    """
                    INSERT INTO similarity_relationships(
                        relationship_key, left_content_identity_id, right_content_identity_id,
                        analysis_run_id, relationship_type, phash_distance, dhash_distance,
                        review_tier
                    ) VALUES (?, ?, ?, ?, 'perceptual_similarity', ?, ?, 'review_only')
                    """,
                    (
                        relationship_key, left, right, run_id,
                        parsed["phash_distance"], parsed["dhash_distance"],
                    ),
                )
                relationship_ids[key] = int(
                    connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                )
                pair_rows[key] = parsed
                pair_count += 1

            summary_values: dict[str, dict[str, object]] = {}
            group_db_ids: dict[str, int] = {}
            for ordinal, row in iter_csv(summary, SUMMARY_HEADERS):
                group_id = row["GroupID"]
                if not group_id or group_id in summary_values:
                    raise EvidenceValidationError(
                        f"M11 summary row {ordinal}: GroupID is missing or duplicated."
                    )
                values: dict[str, object] = {
                    "unique_contents": parse_nonnegative_int(
                        row["UniqueContents"], "UniqueContents", ordinal
                    ),
                    "candidate_pairs": parse_nonnegative_int(
                        row["CandidatePairs"], "CandidatePairs", ordinal
                    ),
                    "min_phash": parse_nonnegative_int(
                        row["MinPHashDistance"], "MinPHashDistance", ordinal
                    ),
                    "max_phash": parse_nonnegative_int(
                        row["MaxPHashDistance"], "MaxPHashDistance", ordinal
                    ),
                    "min_dhash": parse_nonnegative_int(
                        row["MinDHashDistance"], "MinDHashDistance", ordinal
                    ),
                    "max_dhash": parse_nonnegative_int(
                        row["MaxDHashDistance"], "MaxDHashDistance", ordinal
                    ),
                    "unique_sources": parse_nonnegative_int(
                        row["UniqueSources"], "UniqueSources", ordinal
                    ),
                    "sources": row["Sources"],
                }
                unique_contents = int(values["unique_contents"])
                if unique_contents < 2 or int(values["candidate_pairs"]) < 1:
                    raise EvidenceValidationError(
                        f"M11 summary row {ordinal}: group must contain contents and pairs."
                    )
                is_large = unique_contents > 20
                review_tier = "large_ambiguous_review_only" if is_large else "review_only"
                connection.execute(
                    """
                    INSERT INTO similarity_groups(
                        group_key, analysis_run_id, external_group_id, unique_contents,
                        candidate_pairs, min_phash_distance, max_phash_distance,
                        min_dhash_distance, max_dhash_distance, unique_sources, sources_text,
                        review_tier, is_large_ambiguous
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_key("m11-similarity-group-v1", group_id), run_id, group_id,
                        unique_contents, values["candidate_pairs"], values["min_phash"],
                        values["max_phash"], values["min_dhash"], values["max_dhash"],
                        values["unique_sources"], values["sources"], review_tier, int(is_large),
                    ),
                )
                group_db_ids[group_id] = int(
                    connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                )
                summary_values[group_id] = values
                group_count += 1

            group_members: dict[str, set[str]] = defaultdict(set)
            group_distances: dict[str, list[tuple[int, int]]] = defaultdict(list)
            seen_group_pairs: set[tuple[str, str]] = set()
            for ordinal, row in iter_csv(groups, GROUP_HEADERS):
                parsed = _parse_pair(row, ordinal)
                key = parsed["key"]
                assert isinstance(key, tuple)
                existing = pair_rows.get(key)
                if existing is None or existing["signature"] != tuple(row[name] for name in PAIR_HEADERS):
                    raise EvidenceValidationError(
                        f"M11 groups row {ordinal}: pair differs from candidate-pair evidence."
                    )
                if key in seen_group_pairs:
                    raise EvidenceValidationError(
                        f"M11 groups row {ordinal}: pair belongs to more than one group."
                    )
                external_group_id = row["GroupID"]
                database_group_id = group_db_ids.get(external_group_id)
                if database_group_id is None:
                    raise EvidenceValidationError(
                        f"M11 groups row {ordinal}: GroupID is absent from summary."
                    )
                connection.execute(
                    """
                    INSERT INTO similarity_group_relationships(
                        similarity_group_id, similarity_relationship_id
                    ) VALUES (?, ?)
                    """,
                    (database_group_id, relationship_ids[key]),
                )
                for sha256 in key:
                    group_members[external_group_id].add(sha256)
                group_distances[external_group_id].append(
                    (int(parsed["phash_distance"]), int(parsed["dhash_distance"]))
                )
                seen_group_pairs.add(key)

            if seen_group_pairs != set(pair_rows):
                raise EvidenceValidationError(
                    "M11 group rows do not account for every candidate pair exactly once."
                )

            for external_group_id, values in summary_values.items():
                members = group_members[external_group_id]
                distances = group_distances[external_group_id]
                phash_distances = [item[0] for item in distances]
                dhash_distances = [item[1] for item in distances]
                derived = {
                    "unique_contents": len(members),
                    "candidate_pairs": len(distances),
                    "min_phash": min(phash_distances),
                    "max_phash": max(phash_distances),
                    "min_dhash": min(dhash_distances),
                    "max_dhash": max(dhash_distances),
                }
                if any(derived[name] != values[name] for name in derived):
                    raise EvidenceValidationError(
                        f"M11 group {external_group_id}: summary differs from group rows."
                    )
                database_group_id = group_db_ids[external_group_id]
                for sha256 in sorted(members):
                    connection.execute(
                        """
                        INSERT INTO similarity_group_memberships(
                            similarity_group_id, content_identity_id
                        ) VALUES (?, ?)
                        """,
                        (database_group_id, _content_id(connection, sha256, 0)),
                    )

            group_sizes = [int(values["unique_contents"]) for values in summary_values.values()]
            actual: dict[str, object] = {
                "unique_dualhash_contents": dualhash_count,
                "phashed_physical_copies": phashed_copies,
                "dhash_coverage": dhash_coverage,
                "similarity_pairs": pair_count,
                "review_groups": group_count,
                "unique_group_contents": int(connection.execute(
                    "SELECT COUNT(DISTINCT content_identity_id) FROM similarity_group_memberships"
                ).fetchone()[0]),
                "largest_group": max(group_sizes, default=0),
                "groups_over_20": sum(size > 20 for size in group_sizes),
                "groups_over_50": sum(size > 50 for size in group_sizes),
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
        raise EvidenceValidationError(f"M11 import failed: {exc}") from exc

    return report
