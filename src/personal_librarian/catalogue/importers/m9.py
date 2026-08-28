"""Import the verified M9 global inventory evidence."""

from __future__ import annotations

import sqlite3
from collections import Counter
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
)

STAGE_KEY = "m9-inventory-v1"
RUN_KEY = "m9:global-media-inventory:verified-20260819"
HEADERS = ("Source", "RelativePath", "Extension", "SizeBytes", "ModTime")


def import_m9(
    connection: sqlite3.Connection,
    inventory_path: str | Path,
    *,
    baseline: Mapping[str, Any] | None = None,
) -> StageReport:
    """Import M9 inventory observations without creating physical instances."""

    path = validate_input_file(inventory_path)
    fingerprint = fingerprint_files({"inventory": path})
    prior = completed_stage(connection, STAGE_KEY, fingerprint)
    if prior is not None:
        return prior

    expected = dict(DEFAULT_BASELINES["m9"] if baseline is None else baseline)
    rows = 0
    total_bytes = 0
    source_counts: Counter[str] = Counter()

    try:
        with stage_transaction(connection):
            run_id = get_or_create_analysis_run(
                connection,
                run_key=RUN_KEY,
                analysis_kind="inventory",
                algorithm="filesystem-metadata-inventory",
                algorithm_version="M9",
                parameters={"format": "global_media_inventory.csv", "import_stage": STAGE_KEY},
            )

            for row_number, row in iter_csv(path, HEADERS):
                source_label = row["Source"]
                relative_path = row["RelativePath"]
                if not source_label or not relative_path:
                    raise EvidenceValidationError(
                        f"{path}: row {row_number}: Source and RelativePath are required"
                    )

                size_bytes = parse_nonnegative_int(
                    row["SizeBytes"], field="SizeBytes", ordinal=row_number
                )
                timestamp, timestamp_state = parse_timestamp(
                    row["ModTime"], field="ModTime", ordinal=row_number
                )
                source_id = get_or_create_source(connection, source_label)
                batch_id = get_or_create_batch(
                    connection,
                    source_id=source_id,
                    stage="m9",
                )
                observation_key = stable_key(
                    "m9-inventory-observation-v1", source_label, relative_path
                )
                connection.execute(
                    """
                    INSERT INTO inventory_observations (
                        observation_key, analysis_run_id, source_id, acquisition_batch_id,
                        row_ordinal, raw_relative_path, relative_path_comparison_key,
                        path_comparison_key_version, extension, size_bytes,
                        observed_modified_at, timestamp_state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation_key,
                        run_id,
                        source_id,
                        batch_id,
                        row_number,
                        relative_path,
                        windows_path_comparison_key(relative_path),
                        "windows-casefold-v1",
                        row["Extension"],
                        size_bytes,
                        timestamp,
                        timestamp_state,
                    ),
                )
                rows += 1
                total_bytes += size_bytes
                source_counts[source_label] += 1

            actual = {
                "rows": rows,
                "bytes": total_bytes,
                "source_counts": dict(sorted(source_counts.items())),
            }
            report = build_stage_report(
                stage=STAGE_KEY,
                metrics=actual,
                expected=expected,
            )
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
        raise EvidenceValidationError(f"M9 import failed: {exc}") from exc

    return report
