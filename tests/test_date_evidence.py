from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from personal_librarian.catalogue.database import connect_existing_catalogue, initialise_catalogue
from personal_librarian.catalogue.errors import DateEvidenceError, PipelineError
from personal_librarian.catalogue.migrations import MIGRATIONS
from personal_librarian.cli import main
from personal_librarian.date_evidence import (
    BasisRole,
    EvidenceInput,
    EvidenceType,
    PartialDate,
    PreferredStatus,
    compatible,
    evaluate_policy,
    get_preferred_date,
    list_date_evidence,
    list_owner_overrides,
    list_preferred_basis,
    list_preferred_identities,
    parse_allowlisted_filename,
    parse_partial_date,
    preferred_date_counts,
    record_evidence,
    replace_owner_preferred_date,
    resolve_preferred_date,
    same_calendar_date,
    same_instant,
    set_owner_preferred_date,
    timezone_adjacent,
)
from personal_librarian.pipeline.common import PipelineInterrupted
from personal_librarian.pipeline.date_evidence import (
    date_pipeline_config,
    run_date_evidence_pipeline,
)
from personal_librarian.pipeline.checkpoints import fingerprint_config


def evidence_row(identifier: int, evidence_type: EvidenceType, value: PartialDate) -> dict[str, object]:
    components = value.as_components()
    return {
        "date_evidence_id": identifier,
        "evidence_type": evidence_type.value,
        "date_year": components["year"], "date_month": components["month"],
        "date_day": components["day"], "time_hour": components["hour"],
        "time_minute": components["minute"], "time_second": components["second"],
        "time_fraction": components["fraction"],
        "utc_offset_minutes": components["utc_offset_minutes"],
    }


class PartialDateAndPolicyTests(unittest.TestCase):
    def test_partial_model_rendering_validation_and_compatibility(self) -> None:
        values = {
            "1987": PartialDate(1987),
            "1987-06": PartialDate(1987, 6),
            "1987-06-14": PartialDate(1987, 6, 14),
            "1987-06-14T15:43": PartialDate(1987, 6, 14, 15, 43),
            "1987-06-14T15:43:21": PartialDate(1987, 6, 14, 15, 43, 21),
            "1987-06-14T15:43:21.123+01:00": PartialDate(
                1987, 6, 14, 15, 43, 21, "123", 60
            ),
        }
        for rendered, value in values.items():
            self.assertEqual(value.render(), rendered)
            self.assertEqual(parse_partial_date(rendered), value)
        self.assertTrue(compatible(PartialDate(2019), PartialDate(2019, 8)))
        self.assertTrue(compatible(PartialDate(2019, 8), PartialDate(2019, 8, 14)))
        self.assertFalse(compatible(PartialDate(2019), PartialDate(2020, 1, 1)))
        with self.assertRaises(DateEvidenceError):
            PartialDate(2023, 2, 29)
        with self.assertRaises(DateEvidenceError):
            PartialDate(2024, 1, 1, 12, 0, fraction="1")

    def test_same_date_different_time_and_known_offset_same_instant(self) -> None:
        left = PartialDate(2019, 8, 14, 1, 2)
        right = PartialDate(2019, 8, 14, 22, 59, 58)
        self.assertTrue(same_calendar_date(left, right))
        self.assertTrue(compatible(left, right))
        utc = PartialDate(2019, 12, 31, 23, 30, 0, utc_offset_minutes=0)
        plus_one = PartialDate(2020, 1, 1, 0, 30, 0, utc_offset_minutes=60)
        self.assertTrue(same_instant(utc, plus_one))
        self.assertTrue(compatible(utc, plus_one))

    def test_strong_agreement_conflict_and_filesystem_policy(self) -> None:
        exif = evidence_row(1, EvidenceType.EXIF_DATETIME_ORIGINAL, PartialDate(2018, 6, 10))
        google_same = evidence_row(2, EvidenceType.GOOGLE_PHOTOS_TAKEOUT, PartialDate(2018, 6, 10))
        result = evaluate_policy([exif, google_same])
        self.assertEqual(result.status, PreferredStatus.RESOLVED)
        self.assertEqual(result.selected_evidence_id, 1)
        self.assertIn((2, BasisRole.CORROBORATING), result.basis)

        google_conflict = evidence_row(3, EvidenceType.GOOGLE_PHOTOS_TAKEOUT, PartialDate(2021, 4, 3))
        result = evaluate_policy([exif, google_conflict])
        self.assertEqual(result.status, PreferredStatus.NEEDS_REVIEW)
        self.assertEqual(result.reason, "strong_conflict")

        filesystem = evidence_row(4, EvidenceType.FILESYSTEM_MODIFIED, PartialDate(2024, 1, 1))
        weak = evaluate_policy([filesystem])
        self.assertEqual(weak.status, PreferredStatus.UNKNOWN)
        self.assertEqual(weak.reason, "weak_evidence_only")
        stronger = evaluate_policy([exif, filesystem])
        self.assertEqual(stronger.status, PreferredStatus.RESOLVED)
        self.assertEqual(stronger.selected_evidence_id, 1)

    def test_adjacent_day_rules_including_new_year(self) -> None:
        exif = evidence_row(
            1, EvidenceType.EXIF_DATETIME_ORIGINAL, PartialDate(2019, 12, 31, 23, 0)
        )
        google = evidence_row(
            2, EvidenceType.GOOGLE_PHOTOS_TAKEOUT, PartialDate(2020, 1, 1, 1, 0)
        )
        self.assertTrue(timezone_adjacent(
            PartialDate(2019, 12, 31, 23, 0), PartialDate(2020, 1, 1, 1, 0)
        ))
        result = evaluate_policy([exif, google])
        self.assertEqual(result.status, PreferredStatus.RESOLVED)
        self.assertEqual(result.selected_evidence_id, 1)
        self.assertIn((2, BasisRole.TIMEZONE_ADJACENT), result.basis)

        equal = evaluate_policy([
            exif,
            evidence_row(3, EvidenceType.EXIF_DATETIME_ORIGINAL, PartialDate(2020, 1, 1, 1, 0)),
        ])
        self.assertEqual(equal.status, PreferredStatus.NEEDS_REVIEW)
        date_only = evaluate_policy([
            evidence_row(4, EvidenceType.EXIF_DATETIME_ORIGINAL, PartialDate(2019, 12, 31)),
            evidence_row(5, EvidenceType.GOOGLE_PHOTOS_TAKEOUT, PartialDate(2020, 1, 1)),
        ])
        self.assertEqual(date_only.status, PreferredStatus.NEEDS_REVIEW)

    def test_filename_allowlist_is_exact_and_calendar_valid(self) -> None:
        examples = {
            "IMG_20240229_123456.jpg": "filename-img-yyyymmdd-hhmmss",
            "VID_20240229_123456.mp4": "filename-vid-yyyymmdd-hhmmss",
            "2024-02-29_12-34-56.jpeg": "filename-iso-date-time",
            "20240229_123456.png": "filename-yyyymmdd-hhmmss",
        }
        for filename, parser_id in examples.items():
            result = parse_allowlisted_filename(filename)
            self.assertEqual(result.status, "matched")
            self.assertEqual(result.parser_id, parser_id)
            self.assertEqual(result.value.render(), "2024-02-29T12:34:56")
        self.assertEqual(parse_allowlisted_filename("VID_20230229_123456.mp4").status, "invalid")
        self.assertEqual(parse_allowlisted_filename("holiday-20240229.jpg").status, "no_match")
        filename = evidence_row(1, EvidenceType.FILENAME_DERIVED, PartialDate(2024, 2, 29, 12, 34, 56))
        self.assertEqual(evaluate_policy([filename]).status, PreferredStatus.RESOLVED)
        self.assertEqual(evaluate_policy([]).status, PreferredStatus.UNKNOWN)


class DateServiceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database = Path(self.temporary_directory.name) / "catalogue.sqlite3"
        initialise_catalogue(self.database)
        connection = connect_existing_catalogue(self.database, read_only=False)
        self.source_id = int(connection.execute(
            "INSERT INTO sources(source_key,display_name,source_type) VALUES('s','S','test')"
        ).lastrowid)
        self.content_ids = []
        for number in range(1, 7):
            self.content_ids.append(int(connection.execute(
                "INSERT INTO content_identities(identity_key) VALUES(?)", (f"content-{number}",)
            ).lastrowid))
        connection.commit()
        connection.close()

    def add_instance(
        self, content_id: int, key: str, path: str, *, created: str | None = None,
        modified: str | None = None,
    ) -> int:
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            identifier = int(connection.execute(
                "INSERT INTO physical_instances(instance_key,source_id,content_identity_id,"
                "raw_relative_path,observed_created_at,observed_modified_at) VALUES(?,?,?,?,?,?)",
                (key, self.source_id, content_id, path, created, modified),
            ).lastrowid)
            connection.commit()
            return identifier
        finally:
            connection.close()

    def owner(self, content_id: int, value: str, action: str) -> dict[str, object]:
        return set_owner_preferred_date(
            database_path=self.database, content_identity_id=content_id, value=value,
            actor="owner", action_id=action, reason="test",
        )


class OwnerAndQueryTests(DateServiceCase):
    def test_owner_all_precisions_queries_and_no_manufactured_components(self) -> None:
        values = ("1987", "1987-06", "1987-06-14", "1987-06-14T15:43:21.25+01:00")
        for content_id, value in zip(self.content_ids[:4], values, strict=True):
            result = self.owner(content_id, value, f"action-{content_id}")
            self.assertTrue(result["changed"])
            preferred = get_preferred_date(
                database_path=self.database, content_identity_id=content_id
            )["preferred_date"]
            parsed = parse_partial_date(value)
            self.assertEqual(preferred["selected_precision"], parsed.precision.value)
            self.assertEqual(preferred["selected_month"], parsed.month)
            self.assertEqual(preferred["selected_day"], parsed.day)
        evidence = list_date_evidence(
            database_path=self.database, content_identity_id=self.content_ids[0], limit=1
        )
        self.assertEqual(evidence["total_matching"], 1)
        self.assertIsNone(evidence["evidence"][0]["date_month"])
        self.assertEqual(list_owner_overrides(database_path=self.database)["total_matching"], 4)
        self.assertEqual(preferred_date_counts(database_path=self.database)["without_preferred_record"], 2)

    def test_owner_retry_replacement_history_and_policy_preservation(self) -> None:
        content_id = self.content_ids[0]
        first = self.owner(content_id, "1999", "action-one")
        retry = self.owner(content_id, "1999", "action-one")
        replacement = replace_owner_preferred_date(
            database_path=self.database, content_identity_id=content_id,
            value="2001-02", actor="owner", action_id="action-two", reason="test",
        )
        self.assertTrue(first["changed"])
        self.assertFalse(retry["changed"])
        self.assertTrue(replacement["changed"])
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM content_date_evidence WHERE content_identity_id=?",
                (content_id,),
            ).fetchone()[0], 2)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM organisation_events WHERE content_identity_id=?",
                (content_id,),
            ).fetchone()[0], 2)
            run = int(connection.execute(
                "INSERT INTO analysis_runs(run_key,analysis_kind) VALUES('policy-run','date')"
            ).lastrowid)
            preserved = resolve_preferred_date(
                connection, content_identity_id=content_id, analysis_run_id=run
            )
            self.assertTrue(preserved["owner_override_preserved"])
            connection.commit()
        finally:
            connection.close()
        preferred = get_preferred_date(
            database_path=self.database, content_identity_id=content_id
        )["preferred_date"]
        self.assertEqual(preferred["selected_year"], 2001)
        basis = list_preferred_basis(
            database_path=self.database, content_identity_id=content_id
        )["basis"]
        self.assertEqual(sum(row["basis_state"] == "current" for row in basis), 1)

    def test_changed_extractor_and_policy_versions_are_auditable(self) -> None:
        content_id = self.content_ids[0]
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            run = int(connection.execute(
                "INSERT INTO analysis_runs(run_key,analysis_kind) VALUES('r','date')"
            ).lastrowid)
            base = dict(
                content_identity_id=content_id, evidence_type=EvidenceType.SPECIALIST_IMPORT,
                raw_value="2010", value=PartialDate(2010), actor_type="system",
                actor_identifier="test", provenance="test", analysis_run_id=run,
                extractor_name="specialist",
            )
            first = record_evidence(connection, EvidenceInput(**base, extractor_version="1"))
            reused = record_evidence(connection, EvidenceInput(**base, extractor_version="1"))
            changed = record_evidence(connection, EvidenceInput(**base, extractor_version="2"))
            self.assertTrue(first.created)
            self.assertFalse(reused.created)
            self.assertTrue(changed.created)
            resolve_preferred_date(
                connection, content_identity_id=content_id, analysis_run_id=run,
                policy_version="preferred-date-policy-v1",
            )
            event_count = connection.execute("SELECT COUNT(*) FROM organisation_events").fetchone()[0]
            resolve_preferred_date(
                connection, content_identity_id=content_id, analysis_run_id=run,
                policy_version="preferred-date-policy-v2-test",
            )
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM organisation_events"
            ).fetchone()[0], event_count + 1)
            connection.commit()
        finally:
            connection.close()

    def test_bounded_status_queries(self) -> None:
        self.owner(self.content_ids[0], "2000", "a")
        result = list_preferred_identities(
            database_path=self.database, status=PreferredStatus.NEEDS_REVIEW, limit=1
        )
        self.assertEqual(result["limit"], 1)
        self.assertEqual(result["items"], [])
        unknown = list_preferred_identities(
            database_path=self.database, status=PreferredStatus.UNKNOWN, limit=2
        )
        self.assertEqual(unknown["total_matching"], 5)
        self.assertEqual(len(unknown["items"]), 2)
        self.assertTrue(all(item["reason"] == "no_preferred_record" for item in unknown["items"]))


class PipelineAndCliTests(DateServiceCase):
    def add_explicit_instance(
        self, physical_instance_id: int, content_id: int, path: str,
    ) -> None:
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            connection.execute(
                "INSERT INTO physical_instances(physical_instance_id,instance_key,source_id,"
                "content_identity_id,raw_relative_path,observed_modified_at) "
                "VALUES(?,?,?,?,?,'2024-01-01T00:00:00Z')",
                (physical_instance_id, f"explicit-{physical_instance_id}", self.source_id,
                 content_id, path),
            )
            connection.commit()
        finally:
            connection.close()

    def job_physical_ids(self, job_id: str) -> list[int]:
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            return [int(row[0]) for row in connection.execute(
                "SELECT physical_instance_id FROM date_evidence_job_items "
                "WHERE job_id=? ORDER BY physical_instance_id", (job_id,),
            )]
        finally:
            connection.close()

    def test_first_batch_default_cursor_selects_first_five(self) -> None:
        for index in range(7):
            self.add_instance(
                self.content_ids[index % len(self.content_ids)], f"first-{index}",
                f"ordinary-{index}.jpg", modified="2024-01-01T00:00:00Z",
            )
        report = run_date_evidence_pipeline(
            database_path=self.database, job_id="first-five", limit=5,
        )
        self.assertEqual(self.job_physical_ids("first-five"), [1, 2, 3, 4, 5])
        self.assertEqual(report.metrics["requested_after_physical_instance_id"], 0)
        self.assertEqual(report.metrics["requested_limit"], 5)
        self.assertEqual(report.metrics["selected_count"], 5)
        self.assertEqual(
            date_pipeline_config(limit=5, policy_version="preferred-date-policy-v1"),
            date_pipeline_config(
                limit=5, after_physical_instance_id=0,
                policy_version="preferred-date-policy-v1",
            ),
        )

    def test_cursor_batches_are_gap_safe_non_overlapping_and_idempotent(self) -> None:
        physical_ids = (2, 5, 6, 10, 14, 15, 21)
        for index, physical_id in enumerate(physical_ids):
            self.add_explicit_instance(
                physical_id, self.content_ids[index % len(self.content_ids)],
                f"folder/IMG_20240{index + 1}01_010203.jpg",
            )

        first = run_date_evidence_pipeline(
            database_path=self.database, job_id="cursor-first", limit=3,
            after_physical_instance_id=0,
        )
        second = run_date_evidence_pipeline(
            database_path=self.database, job_id="cursor-second", limit=3,
            after_physical_instance_id=6,
        )
        self.assertEqual(self.job_physical_ids("cursor-first"), [2, 5, 6])
        self.assertEqual(self.job_physical_ids("cursor-second"), [10, 14, 15])
        self.assertFalse(set(self.job_physical_ids("cursor-first")) &
                         set(self.job_physical_ids("cursor-second")))
        self.assertEqual(first.metrics["first_selected_physical_instance_id"], 2)
        self.assertEqual(first.metrics["last_selected_physical_instance_id"], 6)
        self.assertEqual(first.metrics["next_cursor"], 6)
        self.assertEqual(second.metrics["first_selected_physical_instance_id"], 10)
        self.assertEqual(second.metrics["last_selected_physical_instance_id"], 15)
        self.assertNotEqual(
            first.metrics["config_fingerprint"], second.metrics["config_fingerprint"]
        )

        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            before = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_date_evidence),"
                "(SELECT COUNT(*) FROM content_preferred_dates),"
                "(SELECT COUNT(*) FROM preferred_date_basis),"
                "(SELECT COUNT(*) FROM organisation_events)"
            ).fetchone())
        finally:
            connection.close()
        repeated = run_date_evidence_pipeline(
            database_path=self.database, job_id="cursor-second", limit=3,
            after_physical_instance_id=6,
        )
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            after = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_date_evidence),"
                "(SELECT COUNT(*) FROM content_preferred_dates),"
                "(SELECT COUNT(*) FROM preferred_date_basis),"
                "(SELECT COUNT(*) FROM organisation_events)"
            ).fetchone())
        finally:
            connection.close()
        self.assertEqual(after, before)
        self.assertEqual(repeated.metrics["selected_count"], 3)
        with self.assertRaisesRegex(PipelineError, "different date pipeline configuration"):
            run_date_evidence_pipeline(
                database_path=self.database, job_id="cursor-second", limit=3,
                after_physical_instance_id=15,
            )

    def test_cursor_empty_batch_and_fingerprint_metadata(self) -> None:
        self.add_explicit_instance(4, self.content_ids[0], "ordinary.jpg")
        config_zero = date_pipeline_config(
            limit=5, after_physical_instance_id=0,
            policy_version="preferred-date-policy-v1",
        )
        config_next = date_pipeline_config(
            limit=5, after_physical_instance_id=5000,
            policy_version="preferred-date-policy-v1",
        )
        self.assertEqual(config_zero["selection_order"], "physical_instance_id ASC")
        self.assertEqual(config_zero["after_physical_instance_id"], 0)
        self.assertEqual(config_zero["limit"], 5)
        self.assertNotEqual(
            fingerprint_config(config_zero)[0], fingerprint_config(config_next)[0]
        )
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            before = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_date_evidence),"
                "(SELECT COUNT(*) FROM organisation_events)"
            ).fetchone())
        finally:
            connection.close()
        report = run_date_evidence_pipeline(
            database_path=self.database, job_id="empty-cursor", limit=5,
            after_physical_instance_id=4,
        )
        self.assertEqual(report.metrics["selected_count"], 0)
        self.assertIsNone(report.metrics["first_selected_physical_instance_id"])
        self.assertIsNone(report.metrics["last_selected_physical_instance_id"])
        self.assertIsNone(report.metrics["next_cursor"])
        self.assertTrue(report.metrics["end_of_catalogue"])
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            after = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_date_evidence),"
                "(SELECT COUNT(*) FROM organisation_events)"
            ).fetchone())
        finally:
            connection.close()
        self.assertEqual(after, before)

    def test_cursor_resume_retains_boundary(self) -> None:
        for physical_id in (3, 8, 9, 20):
            self.add_explicit_instance(
                physical_id, self.content_ids[physical_id % len(self.content_ids)],
                f"ordinary-{physical_id}.jpg",
            )
        with self.assertRaises(PipelineInterrupted):
            run_date_evidence_pipeline(
                database_path=self.database, job_id="cursor-resume", limit=2,
                after_physical_instance_id=8, interrupt_after=1,
            )
        report = run_date_evidence_pipeline(
            database_path=self.database, job_id="cursor-resume", limit=2,
            after_physical_instance_id=8,
        )
        self.assertEqual(self.job_physical_ids("cursor-resume"), [9, 20])
        self.assertEqual(report.metrics["requested_after_physical_instance_id"], 8)
        self.assertEqual(report.metrics["first_selected_physical_instance_id"], 9)
        self.assertEqual(report.metrics["last_selected_physical_instance_id"], 20)
        self.assertTrue(report.metrics["end_of_catalogue"])

    def test_cursor_and_limit_cli_validation_and_smoke(self) -> None:
        self.add_explicit_instance(4, self.content_ids[0], "IMG_20240102_030405.jpg")
        for arguments in (
            ("--after-physical-instance-id", "-1", "--limit", "1"),
            ("--after-physical-instance-id", "0", "--limit", "0"),
            ("--after-physical-instance-id", "0", "--limit", "5001"),
        ):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main([
                    "dates", "run", "--database", str(self.database),
                    "--job-id", "invalid-cli", *arguments, "--format", "json",
                ])
            self.assertEqual(code, 2)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "dates", "run", "--database", str(self.database),
                "--job-id", "cursor-cli", "--after-physical-instance-id", "3",
                "--limit", "1", "--format", "json",
            ])
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["metrics"]["requested_after_physical_instance_id"], 3)
        self.assertEqual(result["metrics"]["requested_limit"], 1)
        self.assertEqual(result["metrics"]["first_selected_physical_instance_id"], 4)

    def test_existing_legacy_job_without_selection_requires_new_job_id(self) -> None:
        self.add_explicit_instance(4, self.content_ids[0], "ordinary.jpg")
        legacy_config = {
            "pipeline_version": "m30c-v1",
            "normalisation_version": "partial-date-v1",
            "policy_version": "preferred-date-policy-v1",
            "max_items": 1,
            "extractors": {"catalogue_timestamps": "1", "filename_allowlist": "1"},
            "media_bytes_read": False,
        }
        legacy_fingerprint, legacy_json = fingerprint_config(legacy_config)
        connection = connect_existing_catalogue(self.database, read_only=False)
        try:
            analysis_run_id = int(connection.execute(
                "INSERT INTO analysis_runs(run_key,analysis_kind,algorithm,algorithm_version,"
                "parameters_json) VALUES('legacy-cursor-job','date_evidence',"
                "'catalogue-fields','m30c-v1',?)", (legacy_json,),
            ).lastrowid)
            connection.execute(
                "INSERT INTO date_evidence_jobs(job_id,pipeline_version,policy_name,"
                "policy_version,config_fingerprint,config_json,analysis_run_id,status) "
                "VALUES('legacy-first-page','m30c-v1','preferred-date-policy',"
                "'preferred-date-policy-v1',?,?,?,'completed')",
                (legacy_fingerprint, legacy_json, analysis_run_id),
            )
            connection.commit()
        finally:
            connection.close()
        # A historical completed flag with no retained selection/checkpoints cannot
        # authorise processing today's first page. Preserve, do not fabricate it.
        with self.assertRaisesRegex(PipelineError, "no provable original selection"):
            run_date_evidence_pipeline(
                database_path=self.database, job_id="legacy-first-page", limit=1,
                after_physical_instance_id=0,
            )
        self.assertEqual(self.job_physical_ids("legacy-first-page"), [])
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            job = connection.execute("SELECT * FROM date_evidence_jobs WHERE job_id='legacy-first-page'").fetchone()
            self.assertEqual(job["status"], "completed")
            self.assertEqual(job["config_fingerprint"], legacy_fingerprint)
            self.assertEqual(job["config_json"], legacy_json)
        finally:
            connection.close()

    def test_single_item_failure_is_checkpointed_and_next_item_continues(self) -> None:
        import personal_librarian.pipeline.date_evidence as pipeline_module

        self.add_instance(self.content_ids[0], "i1", "ordinary-one.jpg")
        self.add_instance(self.content_ids[1], "i2", "IMG_20200102_030405.jpg")
        original = pipeline_module._process_item
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("deliberate item failure")
            return original(*args, **kwargs)

        with patch.object(pipeline_module, "_process_item", side_effect=fail_once):
            report = run_date_evidence_pipeline(
                database_path=self.database, job_id="failure-job", max_items=2
            )
        self.assertEqual(report.metrics["job_errors"], 1)
        self.assertEqual(report.metrics["physical_items_checkpointed"], 2)
        self.assertEqual(report.metrics["resolved_count"], 1)

    def test_pipeline_idempotency_exact_copy_aggregation_and_no_media_access(self) -> None:
        content = self.content_ids[0]
        self.add_instance(content, "i1", r"missing\IMG_20200102_030405.jpg",
                          created="2022-01-01T00:00:00Z")
        self.add_instance(content, "i2", r"also-missing\20200102_030405.jpg",
                          modified="2023-01-01T00:00:00Z")
        first = run_date_evidence_pipeline(
            database_path=self.database, job_id="job-one", max_items=10
        )
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            counts = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_date_evidence),"
                "(SELECT COUNT(*) FROM content_preferred_dates),"
                "(SELECT COUNT(*) FROM organisation_events)"
            ).fetchone())
        finally:
            connection.close()
        second = run_date_evidence_pipeline(
            database_path=self.database, job_id="job-two", max_items=10
        )
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            self.assertEqual(tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM content_date_evidence),"
                "(SELECT COUNT(*) FROM content_preferred_dates),"
                "(SELECT COUNT(*) FROM organisation_events)"
            ).fetchone()), counts)
        finally:
            connection.close()
        self.assertEqual(first.metrics["resolved_count"], 1)
        self.assertEqual(first.metrics["content_candidates_considered"], 1)
        self.assertGreater(second.metrics["evidence_rows_reused"], 0)

    def test_pipeline_weak_unknown_invalid_item_resume_and_bound(self) -> None:
        self.add_instance(self.content_ids[0], "i1", "ordinary.jpg",
                          created="2020-01-01T00:00:00Z")
        self.add_instance(self.content_ids[1], "i2", "VID_20230229_123456.mp4",
                          created="not-a-date")
        self.add_instance(self.content_ids[2], "i3", "IMG_20200102_030405.jpg")
        with self.assertRaises(PipelineInterrupted):
            run_date_evidence_pipeline(
                database_path=self.database, job_id="resume", max_items=2,
                interrupt_after=1,
            )
        report = run_date_evidence_pipeline(
            database_path=self.database, job_id="resume", max_items=2
        )
        self.assertEqual(report.metrics["physical_items_checkpointed"], 2)
        self.assertEqual(report.metrics["physical_candidates_considered"], 2)
        self.assertEqual(report.metrics["weak_evidence_only_count"], 1)
        self.assertEqual(get_preferred_date(
            database_path=self.database, content_identity_id=self.content_ids[0]
        )["reason"], "weak_evidence_only")
        connection = connect_existing_catalogue(self.database, read_only=True)
        try:
            outcomes = {row[0] for row in connection.execute(
                "SELECT outcome FROM date_evidence_job_items WHERE job_id='resume'"
            )}
            self.assertIn("invalid_metadata", outcomes)
        finally:
            connection.close()

    def test_fingerprint_cli_smoke_and_confirmation(self) -> None:
        config = date_pipeline_config(max_items=10, policy_version="preferred-date-policy-v1")
        self.assertEqual(fingerprint_config(config), fingerprint_config(dict(reversed(list(config.items())))))
        content = self.content_ids[0]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main([
                "dates", "owner-set", str(content), "--database", str(self.database),
                "--value", "2005", "--actor", "owner", "--action-id", "cli-action",
                "--format", "json",
            ])
        self.assertEqual(code, 2)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "dates", "owner-set", str(content), "--database", str(self.database),
                "--value", "2005", "--actor", "owner", "--action-id", "cli-action",
                "--confirm-owner-date", "--format", "json",
            ])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["changed"])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "dates", "show", str(content), "--database", str(self.database),
                "--format", "json",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["preferred_date"]["selected_year"], 2005)
        self.add_instance(content, "cli-instance", "ordinary.jpg",
                          modified="2024-01-01T00:00:00Z")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "dates", "run", "--database", str(self.database), "--job-id", "cli-job",
                "--limit", "1", "--format", "json",
            ])
        self.assertEqual(code, 0)
        run_result = json.loads(stdout.getvalue())
        self.assertEqual(run_result["status"], "completed")
        self.assertEqual(run_result["metrics"]["owner_overrides_preserved"], 1)

    def test_schema9_is_rejected_without_migration(self) -> None:
        database = Path(self.temporary_directory.name) / "schema9.sqlite3"
        connection = sqlite3.connect(database)
        for migration in MIGRATIONS[:9]:
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations(version,name) VALUES(?,?)",
                (migration.version, migration.name),
            )
            connection.commit()
        connection.execute("INSERT INTO content_identities(identity_key) VALUES('old')")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(DateEvidenceError, "schema 10"):
            get_preferred_date(database_path=database, content_identity_id=1)


if __name__ == "__main__":
    unittest.main()
