from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    initialise_catalogue,
)
from personal_librarian.catalogue.errors import CataloguePathError, DecisionError
from personal_librarian.cli import main
from personal_librarian.decisions import (
    abstain,
    approve,
    current_decisions,
    decision_history,
    derive_context_state,
    nominate,
    reject,
    supersede,
)
from personal_librarian.review import (
    list_exact_reviews,
    list_similar_reviews,
    show_exact_review,
    show_similar_review,
)


class ReviewDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.database = self.base / "catalogue.sqlite3"
        self.media = self.base / "media"
        self.media.mkdir()
        initialise_catalogue(self.database)
        self._populate()

    def connection(self):
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.addCleanup(connection.close)
        return connection

    def _populate(self) -> None:
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            run_id = int(connection.execute(
                "INSERT INTO analysis_runs(run_key, analysis_kind, algorithm, algorithm_version) "
                "VALUES ('review-fixture', 'test', 'dual hash', 'fixture-v1')"
            ).lastrowid)
            source_a = int(connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) "
                "VALUES ('a', 'Alpha', 'test')"
            ).lastrowid)
            source_b = int(connection.execute(
                "INSERT INTO sources(source_key, display_name, source_type) "
                "VALUES ('b', 'Beta', 'test')"
            ).lastrowid)
            self.contents: list[int] = []
            self.instances: dict[int, list[int]] = {}
            for content_index in range(3):
                content_id = int(connection.execute(
                    "INSERT INTO content_identities(identity_key, created_by_analysis_run_id) "
                    "VALUES (?, ?)",
                    (f"sha256:{content_index:064x}", run_id),
                ).lastrowid)
                self.contents.append(content_id)
                connection.execute(
                    "INSERT INTO content_identity_hashes("
                    "content_identity_id, algorithm, hash_value, analysis_run_id) "
                    "VALUES (?, 'SHA-256', ?, ?)",
                    (content_id, f"{content_index:064x}", run_id),
                )
                copies = 2 if content_index < 2 else 1
                ids = []
                for copy_index in range(copies):
                    path = self.media / f"c{content_index}-{copy_index}.jpg"
                    path.write_bytes(f"fixture-{content_index}-{copy_index}".encode())
                    source_id = source_a if copy_index == 0 else source_b
                    instance_id = int(connection.execute(
                        """
                        INSERT INTO physical_instances(
                            instance_key, source_id, content_identity_id,
                            raw_relative_path, current_observed_path, size_bytes,
                            extension, observed_created_at, observed_modified_at
                        ) VALUES (?, ?, ?, ?, ?, ?, '.jpg', ?, ?)
                        """,
                        (
                            f"instance-{content_index}-{copy_index}", source_id, content_id,
                            path.name, str(path), path.stat().st_size,
                            "2026-01-01T00:00:00Z", f"2026-01-0{copy_index + 1}T00:00:00Z",
                        ),
                    ).lastrowid)
                    ids.append(instance_id)
                self.instances[content_id] = ids
                if copies == 2:
                    group_id = int(connection.execute(
                        """
                        INSERT INTO exact_duplicate_groups(
                            group_key, content_identity_id, analysis_run_id, copies,
                            unique_sources, source_pattern, size_bytes, redundant_copies,
                            reclaimable_bytes
                        ) VALUES (?, ?, ?, 2, 2, 'Alpha + Beta', ?, 1, ?)
                        """,
                        (
                            f"exact-{content_index}", content_id, run_id,
                            (self.media / f"c{content_index}-0.jpg").stat().st_size,
                            (self.media / f"c{content_index}-0.jpg").stat().st_size,
                        ),
                    ).lastrowid)
                    for instance_id in ids:
                        connection.execute(
                            "INSERT INTO exact_duplicate_memberships VALUES (?, ?, 2)",
                            (group_id, instance_id),
                        )

            left, right = self.contents[:2]
            relationship_id = int(connection.execute(
                """
                INSERT INTO similarity_relationships(
                    relationship_key, left_content_identity_id,
                    right_content_identity_id, analysis_run_id, relationship_type,
                    phash_distance, dhash_distance, review_tier
                ) VALUES ('relationship', ?, ?, ?, 'dual_hash_review', 2, 3, 'review_only')
                """,
                (min(left, right), max(left, right), run_id),
            ).lastrowid)
            self.similarity_group = int(connection.execute(
                """
                INSERT INTO similarity_groups(
                    group_key, analysis_run_id, external_group_id, unique_contents,
                    candidate_pairs, min_phash_distance, max_phash_distance,
                    min_dhash_distance, max_dhash_distance, unique_sources,
                    sources_text, review_tier, is_large_ambiguous
                ) VALUES (
                    'similar-large', ?, 'M17-SYNTHETIC', 51, 1, 2, 2, 3, 3, 2,
                    'Alpha + Beta', 'very_large_low_confidence_review_only', 1
                )
                """,
                (run_id,),
            ).lastrowid)
            for content_id in (left, right):
                connection.execute(
                    "INSERT INTO similarity_group_memberships VALUES (?, ?)",
                    (self.similarity_group, content_id),
                )
            connection.execute(
                "INSERT INTO similarity_group_relationships VALUES (?, ?)",
                (self.similarity_group, relationship_id),
            )
            connection.commit()
        finally:
            connection.close()

    def _nominate(self, event: str, physical: int, scope: str = "archival"):
        return nominate(
            database_path=self.database,
            event_id=event,
            context_type="exact",
            context_id=self.contents[0],
            physical_instance_id=physical,
            canonical_scope=scope,
            owner="owner@example",
        )

    def test_exact_queue_is_deterministic_filterable_and_paginated(self) -> None:
        first = list_exact_reviews(database_path=self.database, limit=1)
        second = list_exact_reviews(database_path=self.database, limit=1)
        self.assertEqual(first, second)
        self.assertEqual(first["total_matching"], 2)
        self.assertEqual(len(first["items"]), 1)
        next_page = list_exact_reviews(database_path=self.database, limit=1, offset=1)
        self.assertNotEqual(first["items"][0]["context_id"], next_page["items"][0]["context_id"])

        context_id = self.contents[0]
        detail = show_exact_review(database_path=self.database, context_id=context_id)
        self.assertEqual(detail["group_size"], 2)
        self.assertEqual(detail["sources"], ["Alpha", "Beta"])
        self.assertEqual(len(detail["physical_instances"]), 2)
        self.assertIn("sha256", detail["physical_instances"][0])
        untouched_state = current_decisions(
            database_path=self.database, context_type="exact", context_id=context_id
        )
        self.assertEqual(len(untouched_state), 2)
        self.assertTrue(all(item["status"] == "pending" for item in untouched_state))

        self._nominate("pending-nomination", self.instances[context_id][0])
        pending = list_exact_reviews(database_path=self.database, status="pending")
        reviewed = list_exact_reviews(database_path=self.database, status="reviewed")
        self.assertEqual(pending["total_matching"], 1)
        self.assertEqual(reviewed["total_matching"], 1)

    def test_similarity_queue_retains_relationships_and_large_group_evidence(self) -> None:
        queue = list_similar_reviews(database_path=self.database)
        self.assertEqual(queue["total_matching"], 1)
        item = queue["items"][0]
        self.assertTrue(item["is_large_ambiguous"])
        self.assertTrue(item["is_over_50"])
        detail = show_similar_review(
            database_path=self.database, context_id=self.similarity_group
        )
        self.assertEqual(detail["review_tier"], "very_large_low_confidence_review_only")
        self.assertEqual(detail["relationships"][0]["phash_distance"], 2)
        self.assertEqual(detail["relationships"][0]["dhash_distance"], 3)
        self.assertEqual(len(detail["content_identity_ids"]), 2)
        large_only = list_similar_reviews(database_path=self.database, large_only=True)
        self.assertEqual(large_only["total_matching"], 1)
        self.assertTrue(large_only["large_only"])

    def test_nomination_approval_independent_scopes_and_supersession(self) -> None:
        first, second = self.instances[self.contents[0]]
        nominated = self._nominate("nom-a", first)
        archival = nominated["current_state"]["scopes"]["archival"]
        self.assertEqual(archival["status"], "pending")
        self.assertIsNone(archival["approved"])

        approve(
            database_path=self.database, event_id="approve-a",
            nomination_id="nom-a", physical_instance_id=first,
            canonical_scope="archival", owner="owner@example", reason=None,
        )
        self._nominate("nom-display-a", first, "display_export")
        approve(
            database_path=self.database, event_id="approve-display-a",
            nomination_id="nom-display-a", physical_instance_id=first,
            canonical_scope="display_export", owner="owner@example", reason=None,
        )
        state = current_decisions(
            database_path=self.database, context_type="exact", context_id=self.contents[0]
        )
        self.assertEqual(
            {item["canonical_scope"]: item["approved"]["physical_instance_id"] for item in state},
            {"archival": first, "display_export": first},
        )

        self._nominate("nom-b", second)
        with self.assertRaisesRegex(DecisionError, "explicit supersession"):
            approve(
                database_path=self.database, event_id="invalid-second-approval",
                nomination_id="nom-b", physical_instance_id=second,
                canonical_scope="archival", owner="owner@example", reason=None,
            )
        supersede(
            database_path=self.database, event_id="supersede-a-with-b",
            nomination_id="nom-b", prior_approval_id="approve-a",
            physical_instance_id=second, canonical_scope="archival",
            owner="owner@example", reason="Owner selected another representation",
        )
        state = current_decisions(
            database_path=self.database, context_type="exact", context_id=self.contents[0]
        )
        winners = {item["canonical_scope"]: item["approved"]["physical_instance_id"] for item in state}
        self.assertEqual(winners, {"archival": second, "display_export": first})

        abstained = abstain(
            database_path=self.database, event_id="withdraw-display-approval",
            context_type="exact", context_id=self.contents[0],
            content_identity_id=self.contents[0], canonical_scope="display_export",
            owner="owner@example", reason="Return to no selection",
            prior_approval_id="approve-display-a",
        )
        display_state = abstained["current_state"]["scopes"]["display_export"]
        self.assertEqual(display_state["status"], "abstained")
        self.assertIsNone(display_state["approved"])
        self.assertEqual(abstained["current_state"]["review_status"], "decided")
        history = decision_history(
            database_path=self.database, context_type="exact", context_id=self.contents[0]
        )
        self.assertEqual([item["sequence"] for item in history], sorted(item["sequence"] for item in history))
        self.assertEqual(len(history), 7)

    def test_rejection_abstention_and_cross_context_validation(self) -> None:
        physical = self.instances[self.contents[1]][0]
        nominate(
            database_path=self.database, event_id="near-nomination",
            context_type="similar", context_id=self.similarity_group,
            physical_instance_id=physical, canonical_scope="archival",
            owner="owner@example",
        )
        reject(
            database_path=self.database, event_id="near-rejection",
            nomination_id="near-nomination", physical_instance_id=physical,
            canonical_scope="archival", owner="owner@example", reason="Not selected",
        )
        abstained = abstain(
            database_path=self.database, event_id="near-abstention",
            context_type="similar", context_id=self.similarity_group,
            content_identity_id=self.contents[0], canonical_scope="display_export",
            owner="owner@example", reason="Needs later review",
        )
        self.assertEqual(
            abstained["current_state"]["scopes"]["display_export"]["status"],
            "abstained",
        )
        with self.assertRaisesRegex(DecisionError, "not a member"):
            abstain(
                database_path=self.database, event_id="invalid-abstention",
                context_type="similar", context_id=self.similarity_group,
                content_identity_id=self.contents[2], canonical_scope="display_export",
                owner="owner@example",
            )
        with self.assertRaisesRegex(DecisionError, "not a member"):
            nominate(
                database_path=self.database, event_id="cross-context",
                context_type="exact", context_id=self.contents[0],
                physical_instance_id=physical, canonical_scope="archival",
                owner="owner@example",
            )
        connection = self.connection()
        relationship = connection.execute(
            "SELECT left_content_identity_id, right_content_identity_id FROM similarity_relationships"
        ).fetchone()
        self.assertNotEqual(relationship[0], relationship[1])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM content_identities").fetchone()[0], 3)

    def test_history_is_append_only_and_state_is_rebuilt_from_events(self) -> None:
        physical = self.instances[self.contents[0]][0]
        self._nominate("nomination", physical)
        approve(
            database_path=self.database, event_id="approval", nomination_id="nomination",
            physical_instance_id=physical, canonical_scope="archival",
            owner="owner@example", reason=None,
        )
        connection = self.connection()
        derived_once = derive_context_state(connection, "exact", self.contents[0])
        derived_twice = derive_context_state(connection, "exact", self.contents[0])
        self.assertEqual(derived_once, derived_twice)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            connection.execute(
                "UPDATE decision_events SET reason = 'mutated' WHERE decision_key = 'approval'"
            )
        connection.rollback()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            connection.execute("DELETE FROM decision_events WHERE decision_key = 'approval'")

    def test_review_does_not_touch_media_and_z_database_is_rejected(self) -> None:
        states = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.media.iterdir()
        }
        list_exact_reviews(database_path=self.database)
        list_similar_reviews(database_path=self.database)
        show_exact_review(database_path=self.database, context_id=self.contents[0])
        show_similar_review(database_path=self.database, context_id=self.similarity_group)
        for path, state in states.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)
        with self.assertRaises(CataloguePathError):
            list_exact_reviews(database_path=r"Z:\never-access.sqlite3")

    def test_cli_json_review_and_decision_smoke(self) -> None:
        def call(arguments: list[str]) -> tuple[int, str]:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = main(arguments)
            return code, stdout.getvalue()

        code, output = call([
            "review", "exact", "list", "--database", str(self.database),
            "--limit", "1", "--format", "json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(output)["items"]), 1)
        physical = self.instances[self.contents[0]][0]
        code, output = call([
            "decision", "nominate", "--database", str(self.database),
            "--event-id", "cli-nomination", "--context-type", "exact",
            "--context-id", str(self.contents[0]),
            "--physical-instance-id", str(physical), "--scope", "archival",
            "--owner", "owner@example", "--format", "json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["action"], "nominate")


if __name__ == "__main__":
    unittest.main()
