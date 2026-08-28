"""Controlled import of verified M9, M10, and M11 CSV evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.importers.common import (
    EvidenceImportReport,
    catalogue_table_counts,
)
from personal_librarian.catalogue.importers.m10 import import_m10
from personal_librarian.catalogue.importers.m11 import import_m11
from personal_librarian.catalogue.importers.m9 import import_m9
from personal_librarian.safety import PathSafetyPolicy


def import_verified_evidence(
    *,
    database_path: str | Path,
    m9_path: str | Path,
    m10_manifest_path: str | Path,
    m10_groups_path: str | Path,
    m10_rows_path: str | Path,
    m11_dualhash_path: str | Path,
    m11_pairs_path: str | Path,
    m11_groups_path: str | Path,
    m11_summary_path: str | Path,
    baselines: Mapping[str, Mapping[str, Any]] | None = None,
    safety_policy: PathSafetyPolicy | None = None,
) -> EvidenceImportReport:
    """Initialise the explicit DB and import each milestone as an atomic stage."""

    policy = safety_policy or PathSafetyPolicy()
    initialise_catalogue(database_path, safety_policy=policy)
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=policy
    )
    try:
        stages = (
            import_m9(connection, m9_path, baseline=None if baselines is None else baselines["m9"]),
            import_m10(
                connection,
                m10_manifest_path,
                m10_groups_path,
                m10_rows_path,
                baseline=None if baselines is None else baselines["m10"],
            ),
            import_m11(
                connection,
                m11_dualhash_path,
                m11_pairs_path,
                m11_groups_path,
                m11_summary_path,
                baseline=None if baselines is None else baselines["m11"],
            ),
        )
        return EvidenceImportReport(stages=stages, table_counts=catalogue_table_counts(connection))
    finally:
        connection.close()


__all__ = ["EvidenceImportReport", "import_m9", "import_m10", "import_m11", "import_verified_evidence"]
