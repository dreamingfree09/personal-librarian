"""Historical M9/M10 baseline reconciliation from catalogue state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.safety import PathSafetyPolicy

HISTORICAL_BASELINE: dict[str, object] = {
    "inventory_rows": 69_444,
    "inventory_bytes": 122_312_861_984,
    "source_counts": {
        "OneDrive": 23_538,
        "GooglePhotos": 4_287,
        "Dropbox": 837,
        "HDD_Disk2": 40_782,
    },
    "hash_successes": 69_444,
    "distinct_sha256": 56_127,
    "exact_duplicate_groups": 7_707,
    "duplicate_memberships": 21_024,
    "redundant_copies": 13_317,
    "reclaimable_bytes": 25_488_473_284,
}


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    metrics: dict[str, object]
    expected: dict[str, object]
    matches: dict[str, bool]

    @property
    def matches_baseline(self) -> bool:
        return all(self.matches.values())

    def to_json(self) -> str:
        return json.dumps(
            {
                "matches_baseline": self.matches_baseline,
                "metrics": self.metrics,
                "expected": self.expected,
                "matches": self.matches,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def format_human(self) -> str:
        lines = [f"historical_baseline: {'MATCH' if self.matches_baseline else 'DIFFER'}"]
        for name, value in self.metrics.items():
            marker = "MATCH" if self.matches[name] else "DIFFER"
            lines.append(f"{name}: {value} {marker}")
        return "\n".join(lines)


def reconcile_historical_baseline(
    database_path: str | Path,
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> ReconciliationReport:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        inventory = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM physical_instances"
        ).fetchone()
        source_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                """
                SELECT s.display_name, COUNT(*) FROM physical_instances AS pi
                JOIN sources AS s ON s.source_id = pi.source_id
                GROUP BY s.display_name ORDER BY s.display_name
                """
            )
        }
        hash_counts = connection.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT cih.hash_value)
            FROM physical_instances AS pi
            JOIN content_identity_hashes AS cih
              ON cih.content_identity_id = pi.content_identity_id
             AND cih.algorithm = 'SHA-256'
            """
        ).fetchone()
        exact = connection.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(copies), 0),
                   COALESCE(SUM(copies - 1), 0),
                   COALESCE(SUM((copies - 1) * size_bytes), 0)
            FROM (
                SELECT pi.content_identity_id, COUNT(*) AS copies,
                       MIN(pi.size_bytes) AS size_bytes
                FROM physical_instances AS pi
                WHERE pi.content_identity_id IS NOT NULL
                GROUP BY pi.content_identity_id HAVING COUNT(*) >= 2
            )
            """
        ).fetchone()
        metrics: dict[str, object] = {
            "inventory_rows": int(inventory[0]),
            "inventory_bytes": int(inventory[1]),
            "source_counts": source_counts,
            "hash_successes": int(hash_counts[0]),
            "distinct_sha256": int(hash_counts[1]),
            "exact_duplicate_groups": int(exact[0]),
            "duplicate_memberships": int(exact[1]),
            "redundant_copies": int(exact[2]),
            "reclaimable_bytes": int(exact[3]),
        }
        expected = dict(HISTORICAL_BASELINE)
        matches = {name: metrics[name] == expected[name] for name in expected}
        return ReconciliationReport(metrics, expected, matches)
    finally:
        connection.close()
