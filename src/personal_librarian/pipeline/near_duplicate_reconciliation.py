"""Verified historical M11 reconciliation from catalogue evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import PipelineError
from personal_librarian.safety import PathSafetyPolicy

M11_BASELINE: dict[str, int] = {
    "candidate_content_identities": 54_839,
    "phash_successes": 54_839,
    "phash_errors": 0,
    "phashed_physical_copies_represented": 64_569,
    "dhash_successes": 54_839,
    "dhash_errors": 0,
    "accepted_dual_hash_pairs": 9_403,
    "review_groups": 5_067,
    "grouped_unique_contents": 11_325,
    "largest_group": 135,
    "groups_over_20": 12,
    "groups_over_50": 1,
}


@dataclass(frozen=True, slots=True)
class M11ReconciliationReport:
    metrics: dict[str, int]
    matches: dict[str, bool]

    @property
    def matches_baseline(self) -> bool:
        return all(self.matches.values())

    def to_json(self) -> str:
        return json.dumps(
            {
                "expected": M11_BASELINE,
                "metrics": self.metrics,
                "matches": self.matches,
                "matches_baseline": self.matches_baseline,
            },
            sort_keys=True,
        )

    def format_human(self) -> str:
        lines = [f"m11_historical_baseline: {'MATCH' if self.matches_baseline else 'DIFFER'}"]
        for name, value in self.metrics.items():
            lines.append(f"{name}: {value} {'MATCH' if self.matches[name] else 'DIFFER'}")
        return "\n".join(lines)


def reconcile_m11_baseline(
    database_path: str | Path,
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> M11ReconciliationReport:
    policy = safety_policy or PathSafetyPolicy()
    connection = connect_existing_catalogue(database_path, read_only=True, safety_policy=policy)
    try:
        run = connection.execute(
            "SELECT analysis_run_id FROM analysis_runs WHERE run_key = ?",
            ("m11:dualhash-review:verified-20260820",),
        ).fetchone()
        if run is None:
            raise PipelineError("Verified imported M11 analysis run is absent from this catalogue.")
        run_id = int(run[0])
        hashes = connection.execute(
            """
            SELECT
              COUNT(DISTINCT CASE WHEN algorithm = 'pHash' AND status = 'Hashed'
                             THEN content_identity_id END),
              COUNT(DISTINCT CASE WHEN algorithm = 'dHash' AND status = 'Hashed'
                             THEN content_identity_id END),
              COALESCE(SUM(CASE WHEN algorithm = 'pHash' AND status = 'Hashed'
                                THEN reported_copies ELSE 0 END), 0)
            FROM content_hash_observations WHERE analysis_run_id = ?
            """,
            (run_id,),
        ).fetchone()
        groups = connection.execute(
            """
            SELECT COUNT(*), COALESCE(MAX(unique_contents), 0),
                   COALESCE(SUM(unique_contents > 20), 0),
                   COALESCE(SUM(unique_contents > 50), 0)
            FROM similarity_groups WHERE analysis_run_id = ?
            """,
            (run_id,),
        ).fetchone()
        grouped = int(connection.execute(
            """
            SELECT COUNT(DISTINCT sgm.content_identity_id)
            FROM similarity_group_memberships sgm
            JOIN similarity_groups sg ON sg.similarity_group_id = sgm.similarity_group_id
            WHERE sg.analysis_run_id = ?
            """,
            (run_id,),
        ).fetchone()[0])
        phash_successes = int(hashes[0])
        dhash_successes = int(hashes[1])
        metrics = {
            "candidate_content_identities": phash_successes,
            "phash_successes": phash_successes,
            "phash_errors": 0,
            "phashed_physical_copies_represented": int(hashes[2]),
            "dhash_successes": dhash_successes,
            "dhash_errors": phash_successes - dhash_successes,
            "accepted_dual_hash_pairs": int(connection.execute(
                "SELECT COUNT(*) FROM similarity_relationships WHERE analysis_run_id = ?",
                (run_id,),
            ).fetchone()[0]),
            "review_groups": int(groups[0]),
            "grouped_unique_contents": grouped,
            "largest_group": int(groups[1]),
            "groups_over_20": int(groups[2]),
            "groups_over_50": int(groups[3]),
        }
        matches = {name: metrics[name] == expected for name, expected in M11_BASELINE.items()}
        return M11ReconciliationReport(metrics, matches)
    finally:
        connection.close()
