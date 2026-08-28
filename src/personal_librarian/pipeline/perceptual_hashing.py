"""Content-identity-scoped pHash/dHash generation with explicit provenance."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.catalogue.importers.common import stable_key
from personal_librarian.pipeline.checkpoints import (
    finish_similarity_job,
    mark_similarity_interrupted,
    record_similarity_item,
    similarity_item_exists,
    similarity_outcomes,
    start_or_resume_similarity_job,
)
from personal_librarian.pipeline.common import PipelineInterrupted, PipelineReport
from personal_librarian.safety import PathIntent, PathSafetyPolicy

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
SUPPORTED_PIL_FORMATS = frozenset({"JPEG", "PNG", "GIF", "WEBP"})
DEFAULT_HASH_SUITE_VERSION = "m16-imagehash-compatible-v1"
PHASH_ALGORITHM = "pHash"
DHASH_ALGORITHM = "dHash"


@lru_cache(maxsize=4)
def _dct_matrix(size: int) -> np.ndarray:
    rows = np.arange(size, dtype=np.float64)[:, None]
    columns = np.arange(size, dtype=np.float64)[None, :]
    return 2.0 * np.cos(math.pi * rows * (2.0 * columns + 1.0) / (2.0 * size))


def _bits_to_hex(bits: np.ndarray) -> str:
    text = "".join("1" if bool(value) else "0" for value in bits.ravel())
    return f"{int(text, 2):0{len(text) // 4}x}"


def calculate_phash(image: Image.Image) -> str:
    """Return ImageHash-compatible 64-bit pHash (8x8, high-frequency factor 4)."""

    pixels = np.asarray(
        image.convert("L").resize((32, 32), Image.Resampling.LANCZOS),
        dtype=np.float64,
    )
    transform = _dct_matrix(32)
    dct = transform @ pixels @ transform.T
    low_frequency = dct[:8, :8]
    return _bits_to_hex(low_frequency > np.median(low_frequency))


def calculate_dhash(image: Image.Image) -> str:
    """Return ImageHash-compatible horizontal 64-bit dHash."""

    pixels = np.asarray(
        image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    )
    return _bits_to_hex(pixels[:, 1:] > pixels[:, :-1])


def hamming_distance(left: str, right: str) -> int:
    if len(left) != 16 or len(right) != 16:
        raise ValueError("Perceptual hashes must be 16 hexadecimal characters.")
    return (int(left, 16) ^ int(right, 16)).bit_count()


def run_perceptual_hashing(
    *,
    database_path: str | Path,
    job_id: str,
    limit: int | None = None,
    hash_suite_version: str = DEFAULT_HASH_SUITE_VERSION,
    safety_policy: PathSafetyPolicy | None = None,
    interrupt_after: int | None = None,
) -> PipelineReport:
    """Hash one readable representation per exact SHA-256 content identity."""

    if limit is not None and limit < 1:
        raise PipelineError("limit must be positive when supplied.")
    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(database_path, read_only=False, safety_policy=policy)
    try:
        phash_version = f"{hash_suite_version}:phash-8x8-hf4-lanczos"
        dhash_version = f"{hash_suite_version}:dhash-8x8-horizontal-lanczos"
        config = {
            "hash_suite_version": hash_suite_version,
            "phash_version": phash_version,
            "dhash_version": dhash_version,
            "image_extensions": sorted(IMAGE_EXTENSIONS),
            "limit": limit,
            "selection": "one-readable-physical-per-sha256-content-v1",
        }
        job = start_or_resume_similarity_job(
            connection,
            job_id=job_id,
            job_kind="perceptual_hash",
            config=config,
            algorithm="pHash+dHash",
            algorithm_version=hash_suite_version,
        )
        if job.completed:
            return _hash_report(connection, job_id, job.analysis_run_id)

        candidates: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in connection.execute(
            """
            SELECT ci.content_identity_id, ci.identity_key, cih.hash_value AS sha256,
                   pi.physical_instance_id, pi.current_observed_path,
                   pi.raw_relative_path, lower(pi.extension) AS extension,
                   pi.size_bytes, s.display_name,
                   (SELECT COUNT(*) FROM physical_instances copies
                    WHERE copies.content_identity_id = ci.content_identity_id) AS copies
            FROM content_identities AS ci
            JOIN content_identity_hashes AS cih
              ON cih.content_identity_id = ci.content_identity_id
             AND cih.algorithm = 'SHA-256'
            JOIN physical_instances AS pi
              ON pi.content_identity_id = ci.content_identity_id
            JOIN sources AS s ON s.source_id = pi.source_id
            WHERE lower(pi.extension) IN ('.jpg', '.jpeg', '.png', '.gif', '.webp')
            ORDER BY ci.identity_key, pi.physical_instance_id
            """
        ):
            candidates[int(row[0])].append(row)
        identity_ids = sorted(candidates, key=lambda value: str(candidates[value][0][1]))
        if limit is not None:
            identity_ids = identity_ids[:limit]

        processed = 0
        for content_id in identity_ids:
            rows = candidates[content_id]
            identity_key = str(rows[0][1])
            item_key = stable_key("m16-perceptual-item-v1", identity_key)
            if similarity_item_exists(connection, job_id, item_key):
                continue

            cached = _cached_hashes(
                connection,
                content_id=content_id,
                phash_version=phash_version,
                dhash_version=dhash_version,
            )
            if cached is not None:
                phash_row, dhash_row = cached
                physical_id = int(phash_row[2])
                physical = connection.execute(
                    """
                    SELECT current_observed_path, raw_relative_path, s.display_name
                    FROM physical_instances pi JOIN sources s ON s.source_id = pi.source_id
                    WHERE physical_instance_id = ?
                    """,
                    (physical_id,),
                ).fetchone()
                assert physical is not None
                copies = int(rows[0][9])
                _insert_hash_observation(
                    connection, job_id, job.analysis_run_id, content_id, physical_id,
                    PHASH_ALGORITHM, phash_version, str(phash_row[1]), "reused", None,
                    str(physical[1]), str(physical[2]), copies,
                )
                _insert_hash_observation(
                    connection, job_id, job.analysis_run_id, content_id, physical_id,
                    DHASH_ALGORITHM, dhash_version, str(dhash_row[1]), "reused", None,
                    str(physical[1]), str(physical[2]), copies,
                )
                record_similarity_item(
                    connection,
                    job_id=job_id,
                    item_key=item_key,
                    content_identity_id=content_id,
                    physical_instance_id=physical_id,
                    outcome="reused",
                    payload={"phash": str(phash_row[1]), "dhash": str(dhash_row[1])},
                )
            else:
                _calculate_identity_hashes(
                    connection,
                    job_id=job_id,
                    run_id=job.analysis_run_id,
                    content_id=content_id,
                    identity_key=identity_key,
                    rows=rows,
                    phash_version=phash_version,
                    dhash_version=dhash_version,
                    policy=policy,
                )
            processed += 1
            if interrupt_after is not None and processed >= interrupt_after:
                mark_similarity_interrupted(connection, job_id)
                raise PipelineInterrupted(
                    f"Perceptual-hash job {job_id!r} interrupted after checkpoint."
                )

        finish_similarity_job(connection, job)
        return _hash_report(connection, job_id, job.analysis_run_id)
    finally:
        connection.close()


def _cached_hashes(
    connection: sqlite3.Connection,
    *,
    content_id: int,
    phash_version: str,
    dhash_version: str,
) -> tuple[sqlite3.Row, sqlite3.Row] | None:
    rows = connection.execute(
        """
        SELECT algorithm, hash_value, physical_instance_id
        FROM content_hash_observations
        WHERE content_identity_id = ? AND status IN ('success', 'reused')
          AND ((algorithm = 'pHash' AND algorithm_version = ?)
            OR (algorithm = 'dHash' AND algorithm_version = ?))
          AND hash_value IS NOT NULL AND physical_instance_id IS NOT NULL
        ORDER BY content_hash_observation_id DESC
        """,
        (content_id, phash_version, dhash_version),
    ).fetchall()
    by_algorithm: dict[str, sqlite3.Row] = {}
    for row in rows:
        by_algorithm.setdefault(str(row[0]), row)
    if PHASH_ALGORITHM in by_algorithm and DHASH_ALGORITHM in by_algorithm:
        phash_row = by_algorithm[PHASH_ALGORITHM]
        dhash_row = by_algorithm[DHASH_ALGORITHM]
        if int(phash_row[2]) == int(dhash_row[2]):
            return phash_row, dhash_row
    return None


def _calculate_identity_hashes(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    run_id: int,
    content_id: int,
    identity_key: str,
    rows: list[sqlite3.Row],
    phash_version: str,
    dhash_version: str,
    policy: PathSafetyPolicy,
) -> None:
    final_outcome = "missing"
    final_error = "No catalogued physical representation was readable."
    attempted_physical_id: int | None = None
    attempted_path = str(rows[0][5])
    attempted_source = str(rows[0][8])
    copies = int(rows[0][9])

    for row in rows:
        physical_id = int(row[3])
        attempted_physical_id = physical_id
        attempted_path = str(row[5])
        attempted_source = str(row[8])
        absolute = row[4]
        if absolute is None:
            final_outcome = "missing"
            final_error = "Physical representation has no current observed path."
            continue
        path = Path(str(absolute))
        safety = policy.check_path(path, intent=PathIntent.READ)
        if not safety.allowed:
            raise PipelineError(
                f"Unsafe catalogued image path ({safety.code}): {safety.reason}"
            )
        if int(row[7] or 0) == 0:
            final_outcome = "zero_byte"
            final_error = "Zero-byte image content cannot be perceptually decoded."
            continue
        try:
            with Image.open(path) as image:
                if image.format not in SUPPORTED_PIL_FORMATS:
                    final_outcome = "unsupported_format"
                    final_error = f"Decoded format {image.format!r} is outside the M16 policy."
                    continue
                image.load()
                phash = calculate_phash(image)
                dhash = calculate_dhash(image)
        except FileNotFoundError as exc:
            final_outcome, final_error = "missing", str(exc)
            continue
        except PermissionError as exc:
            final_outcome, final_error = "unreadable", str(exc)
            continue
        except (UnidentifiedImageError, SyntaxError, ValueError) as exc:
            final_outcome, final_error = "decode_error", str(exc)
            continue
        except OSError as exc:
            final_outcome, final_error = "decode_error", str(exc)
            continue

        _insert_hash_observation(
            connection, job_id, run_id, content_id, physical_id, PHASH_ALGORITHM,
            phash_version, phash, "success", None, str(row[5]), str(row[8]), copies,
        )
        _insert_hash_observation(
            connection, job_id, run_id, content_id, physical_id, DHASH_ALGORITHM,
            dhash_version, dhash, "success", None, str(row[5]), str(row[8]), copies,
        )
        record_similarity_item(
            connection,
            job_id=job_id,
            item_key=stable_key("m16-perceptual-item-v1", identity_key),
            content_identity_id=content_id,
            physical_instance_id=physical_id,
            outcome="success",
            payload={"phash": phash, "dhash": dhash},
        )
        return

    for algorithm, version in (
        (PHASH_ALGORITHM, phash_version),
        (DHASH_ALGORITHM, dhash_version),
    ):
        _insert_hash_observation(
            connection, job_id, run_id, content_id, attempted_physical_id,
            algorithm, version, None, final_outcome, final_error,
            attempted_path, attempted_source, copies,
        )
    record_similarity_item(
        connection,
        job_id=job_id,
        item_key=stable_key("m16-perceptual-item-v1", identity_key),
        content_identity_id=content_id,
        physical_instance_id=attempted_physical_id,
        outcome=final_outcome,
        error=final_error,
    )


def _insert_hash_observation(
    connection: sqlite3.Connection,
    job_id: str,
    run_id: int,
    content_id: int,
    physical_id: int | None,
    algorithm: str,
    algorithm_version: str,
    value: str | None,
    status: str,
    error: str | None,
    representative_path: str,
    representative_source: str,
    copies: int,
) -> None:
    connection.execute(
        """
        INSERT INTO content_hash_observations(
            observation_key, content_identity_id, analysis_run_id, algorithm,
            algorithm_version, hash_value, status, error, representative_path,
            representative_source, reported_copies, physical_instance_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stable_key("m16-content-hash-v1", job_id, content_id, algorithm),
            content_id,
            run_id,
            algorithm,
            algorithm_version,
            value,
            status,
            error,
            representative_path,
            representative_source,
            copies,
            physical_id,
        ),
    )


def _hash_report(
    connection: sqlite3.Connection,
    job_id: str,
    run_id: int,
) -> PipelineReport:
    outcomes = similarity_outcomes(connection, job_id)
    row = connection.execute(
        """
        SELECT
          COUNT(DISTINCT CASE WHEN algorithm = 'pHash' AND status IN ('success','reused')
                         THEN content_identity_id END),
          COUNT(DISTINCT CASE WHEN algorithm = 'dHash' AND status IN ('success','reused')
                         THEN content_identity_id END),
          COALESCE(SUM(CASE WHEN algorithm = 'pHash' AND status IN ('success','reused')
                            THEN reported_copies ELSE 0 END), 0)
        FROM content_hash_observations WHERE analysis_run_id = ?
        """,
        (run_id,),
    ).fetchone()
    candidate_count = int(connection.execute(
        "SELECT COUNT(*) FROM similarity_pipeline_items WHERE job_id = ?", (job_id,)
    ).fetchone()[0])
    phash_successes = int(row[0])
    dhash_successes = int(row[1])
    return PipelineReport(
        job_id,
        "perceptual_hash",
        "completed",
        {
            "candidate_content_identities": candidate_count,
            "phash_successes": phash_successes,
            "phash_errors": candidate_count - phash_successes,
            "dhash_successes": dhash_successes,
            "dhash_errors": candidate_count - dhash_successes,
            "phashed_physical_copies_represented": int(row[2]),
            "outcomes": outcomes,
        },
    )
