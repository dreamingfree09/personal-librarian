"""Bounded reproducible M30 catalogue-only date evidence pipeline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from personal_librarian.catalogue.database import connect_existing_catalogue
from personal_librarian.catalogue.errors import DateEvidenceError, PipelineError
from personal_librarian.date_evidence import (
    EvidenceInput,
    EvidenceType,
    FILENAME_PARSER_VERSION,
    NORMALISATION_VERSION,
    PREFERRED_DATE_POLICY,
    parse_allowlisted_filename,
    parse_partial_date,
    record_evidence,
    resolve_preferred_date,
)
from personal_librarian.pipeline.checkpoints import fingerprint_config
from personal_librarian.pipeline.common import PipelineInterrupted
from personal_librarian.safety import PathSafetyPolicy

DATE_EVIDENCE_PIPELINE_VERSION = "m30c-v1"
CATALOGUE_TIMESTAMP_EXTRACTOR = "catalogue-observed-timestamp"
CATALOGUE_TIMESTAMP_EXTRACTOR_VERSION = "1"
MAX_BATCH_SIZE = 5000
MAX_PHYSICAL_INSTANCE_ID = 9_223_372_036_854_775_807


@dataclass(frozen=True, slots=True)
class DateEvidencePipelineReport:
    job_id: str
    status: str
    metrics: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {"job_id": self.job_id, "job_kind": "date_evidence",
                "status": self.status, "metrics": self.metrics}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)

    def format_human(self) -> str:
        lines = [f"job_id: {self.job_id}", "job_kind: date_evidence", f"status: {self.status}"]
        lines.extend(f"{key}: {value}" for key, value in self.metrics.items())
        return "\n".join(lines)


def date_pipeline_config(
    *, policy_version: str, limit: int | None = None,
    after_physical_instance_id: int | None = None, max_items: int | None = None,
) -> dict[str, object]:
    """Return the fingerprinted deterministic batch definition.

    ``max_items`` remains a compatibility alias for callers predating cursor batching.
    New callers should use ``limit``.
    """

    checked_limit = _validated_limit(limit=limit, max_items=max_items)
    cursor = _validated_cursor(after_physical_instance_id)
    return {
        "pipeline_version": DATE_EVIDENCE_PIPELINE_VERSION,
        "normalisation_version": NORMALISATION_VERSION,
        "policy_version": policy_version,
        "after_physical_instance_id": cursor,
        "limit": checked_limit,
        "selection_order": "physical_instance_id ASC",
        "extractors": {
            "catalogue_timestamps": CATALOGUE_TIMESTAMP_EXTRACTOR_VERSION,
            "filename_allowlist": FILENAME_PARSER_VERSION,
        },
        "media_bytes_read": False,
    }


def _legacy_date_pipeline_config(*, max_items: int, policy_version: str) -> dict[str, object]:
    """Reproduce the pre-cursor config solely for existing job compatibility."""

    return {
        "pipeline_version": DATE_EVIDENCE_PIPELINE_VERSION,
        "normalisation_version": NORMALISATION_VERSION,
        "policy_version": policy_version,
        "max_items": max_items,
        "extractors": {
            "catalogue_timestamps": CATALOGUE_TIMESTAMP_EXTRACTOR_VERSION,
            "filename_allowlist": FILENAME_PARSER_VERSION,
        },
        "media_bytes_read": False,
    }


def _validated_limit(*, limit: int | None, max_items: int | None) -> int:
    if limit is not None and max_items is not None and limit != max_items:
        raise PipelineError("limit and legacy max_items must match when both are supplied.")
    value = limit if limit is not None else max_items if max_items is not None else 1000
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_BATCH_SIZE:
        raise PipelineError(f"limit must be between 1 and {MAX_BATCH_SIZE}.")
    return value


def _validated_cursor(value: int | None) -> int:
    cursor = 0 if value is None else value
    if isinstance(cursor, bool) or not isinstance(cursor, int) or not 0 <= cursor <= MAX_PHYSICAL_INSTANCE_ID:
        raise PipelineError(
            "after_physical_instance_id must be between 0 and "
            f"{MAX_PHYSICAL_INSTANCE_ID}."
        )
    return cursor


def run_date_evidence_pipeline(
    *, database_path: str | Path, job_id: str, limit: int | None = None,
    after_physical_instance_id: int | None = None, max_items: int | None = None,
    policy_version: str = PREFERRED_DATE_POLICY,
    safety_policy: PathSafetyPolicy | None = None,
    interrupt_after: int | None = None,
) -> DateEvidencePipelineReport:
    """Extract only stored catalogue fields; never open or stat a media path."""

    if not isinstance(job_id, str) or not job_id.strip():
        raise PipelineError("Job ID must be explicit and non-empty.")
    checked_limit = _validated_limit(limit=limit, max_items=max_items)
    cursor = _validated_cursor(after_physical_instance_id)
    config = date_pipeline_config(
        limit=checked_limit, after_physical_instance_id=cursor,
        policy_version=policy_version,
    )
    fingerprint, config_json = fingerprint_config(config)
    compatible_configs: tuple[tuple[str, str], ...] = ()
    if cursor == 0:
        legacy_config = _legacy_date_pipeline_config(
            max_items=checked_limit, policy_version=policy_version
        )
        compatible_configs = (fingerprint_config(legacy_config),)
    connection = connect_existing_catalogue(
        database_path, read_only=False, safety_policy=safety_policy
    )
    try:
        job = _start_or_resume_job(
            connection, job_id=job_id.strip(), fingerprint=fingerprint,
            config_json=config_json, policy_version=policy_version,
            compatible_configs=compatible_configs,
        )
        candidates = connection.execute(
            """
            SELECT pi.physical_instance_id, pi.content_identity_id, pi.source_id,
                   pi.raw_relative_path, pi.observed_created_at, pi.observed_modified_at
            FROM physical_instances pi
            WHERE pi.content_identity_id IS NOT NULL
              AND pi.physical_instance_id > ?
            ORDER BY pi.physical_instance_id LIMIT ?
            """,
            (cursor, checked_limit),
        ).fetchall()
        selected_count = len(candidates)
        first_selected_id = (
            None if not candidates else int(candidates[0]["physical_instance_id"])
        )
        last_selected_id = (
            None if not candidates else int(candidates[-1]["physical_instance_id"])
        )
        has_more = False if last_selected_id is None else connection.execute(
            "SELECT 1 FROM physical_instances WHERE content_identity_id IS NOT NULL "
            "AND physical_instance_id > ? LIMIT 1", (last_selected_id,),
        ).fetchone() is not None
        selection = {
            "requested_after_physical_instance_id": cursor,
            "requested_limit": checked_limit,
            "selection_order": "physical_instance_id ASC",
            "selected_count": selected_count,
            "first_selected_physical_instance_id": first_selected_id,
            "last_selected_physical_instance_id": last_selected_id,
            "next_cursor": last_selected_id,
            "end_of_catalogue": not has_more,
        }
        processed_this_call = 0
        for row in candidates:
            item_key = f"physical:{int(row['physical_instance_id'])}"
            if connection.execute(
                "SELECT 1 FROM date_evidence_job_items WHERE job_id=? AND item_key=?",
                (job_id, item_key),
            ).fetchone() is not None:
                continue
            try:
                payload, outcome, evidence_count = _process_item(
                    connection, row=row, analysis_run_id=job["analysis_run_id"],
                    policy_version=policy_version,
                )
                connection.execute(
                    """
                    INSERT INTO date_evidence_job_items(
                        job_id,item_key,content_identity_id,physical_instance_id,outcome,
                        evidence_count,payload_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (job_id, item_key, int(row["content_identity_id"]),
                     int(row["physical_instance_id"]), outcome, evidence_count,
                     json.dumps(payload, ensure_ascii=False, sort_keys=True)),
                )
                connection.execute(
                    "UPDATE date_evidence_jobs SET status='running',updated_at="
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?", (job_id,),
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                error = str(exc)[:2000]
                try:
                    connection.execute(
                        "INSERT INTO date_evidence_job_items(job_id,item_key,content_identity_id,"
                        "physical_instance_id,outcome,evidence_count,error,payload_json) "
                        "VALUES(?,?,?,?, 'failed',0,?,?)",
                        (job_id, item_key, int(row["content_identity_id"]),
                         int(row["physical_instance_id"]), error,
                         json.dumps({"error": error}, ensure_ascii=False, sort_keys=True)),
                    )
                    connection.commit()
                except sqlite3.Error as checkpoint_error:
                    connection.rollback()
                    raise PipelineError(
                        f"Catalogue integrity prevented failure checkpoint: {checkpoint_error}"
                    ) from checkpoint_error
            processed_this_call += 1
            if interrupt_after is not None and processed_this_call >= interrupt_after:
                connection.execute(
                    "UPDATE date_evidence_jobs SET status='interrupted',updated_at="
                    "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?", (job_id,),
                )
                connection.commit()
                raise PipelineInterrupted(
                    f"Date evidence job {job_id!r} interrupted after checkpoint."
                )
        connection.execute(
            "UPDATE date_evidence_jobs SET status='completed',updated_at="
            "strftime('%Y-%m-%dT%H:%M:%fZ','now'),completed_at="
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?", (job_id,),
        )
        connection.execute(
            "UPDATE analysis_runs SET completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE analysis_run_id=?", (job["analysis_run_id"],),
        )
        connection.commit()
        return _report(
            connection, job_id, str(job["config_fingerprint"]), selection
        )
    except PipelineInterrupted:
        raise
    except (DateEvidenceError, sqlite3.Error) as exc:
        connection.rollback()
        try:
            connection.execute(
                "UPDATE date_evidence_jobs SET status='failed',updated_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now'),completed_at="
                "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?", (job_id,),
            )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
        raise PipelineError(f"Date evidence pipeline failed safely: {exc}") from exc
    finally:
        connection.close()


def _start_or_resume_job(
    connection: sqlite3.Connection, *, job_id: str, fingerprint: str,
    config_json: str, policy_version: str,
    compatible_configs: tuple[tuple[str, str], ...] = (),
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM date_evidence_jobs WHERE job_id=?", (job_id,)
    ).fetchone()
    if row is not None:
        identity = tuple(row[key] for key in (
            "pipeline_version", "policy_name", "policy_version",
        ))
        accepted_configs = {(fingerprint, config_json), *compatible_configs}
        if identity != (
            DATE_EVIDENCE_PIPELINE_VERSION, "preferred-date-policy", policy_version,
        ) or (row["config_fingerprint"], row["config_json"]) not in accepted_configs:
            raise PipelineError(f"Job ID {job_id!r} has different date pipeline configuration.")
        connection.execute(
            "UPDATE date_evidence_jobs SET status='running',completed_at=NULL,updated_at="
            "strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?", (job_id,),
        )
        connection.commit()
        return connection.execute(
            "SELECT * FROM date_evidence_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    run_key = "date-evidence-job:" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()
    cursor = connection.execute(
        "INSERT INTO analysis_runs(run_key,analysis_kind,algorithm,algorithm_version,"
        "parameters_json,started_at) VALUES(?, 'date_evidence', 'catalogue-fields', ?, ?, "
        "strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
        (run_key, DATE_EVIDENCE_PIPELINE_VERSION, config_json),
    )
    analysis_run_id = int(cursor.lastrowid)
    connection.execute(
        "INSERT INTO date_evidence_jobs(job_id,pipeline_version,policy_name,policy_version,"
        "config_fingerprint,config_json,analysis_run_id) VALUES(?,?,?,?,?,?,?)",
        (job_id, DATE_EVIDENCE_PIPELINE_VERSION, "preferred-date-policy", policy_version,
         fingerprint, config_json, analysis_run_id),
    )
    connection.commit()
    return connection.execute(
        "SELECT * FROM date_evidence_jobs WHERE job_id=?", (job_id,)
    ).fetchone()


def _process_item(
    connection: sqlite3.Connection, *, row: sqlite3.Row, analysis_run_id: int,
    policy_version: str,
) -> tuple[dict[str, object], str, int]:
    content_id = int(row["content_identity_id"])
    physical_id = int(row["physical_instance_id"])
    source_id = int(row["source_id"])
    path = str(row["raw_relative_path"])
    raw_filename = path.replace("\\", "/").rsplit("/", 1)[-1]
    created = reused = invalid = filename_matches = filename_invalid = 0
    by_type: dict[str, int] = {}
    for field, evidence_type in (
        ("observed_created_at", EvidenceType.FILESYSTEM_CREATED),
        ("observed_modified_at", EvidenceType.FILESYSTEM_MODIFIED),
    ):
        raw = row[field]
        if raw is None:
            continue
        try:
            value = parse_partial_date(str(raw))
        except DateEvidenceError:
            invalid += 1
            continue
        result = record_evidence(connection, EvidenceInput(
            content_identity_id=content_id, physical_instance_id=physical_id,
            source_id=source_id, analysis_run_id=analysis_run_id,
            evidence_type=evidence_type, raw_value=str(raw), value=value,
            source_field=field, source_locator=path,
            extractor_name=CATALOGUE_TIMESTAMP_EXTRACTOR,
            extractor_version=CATALOGUE_TIMESTAMP_EXTRACTOR_VERSION,
            actor_type="system", actor_identifier="date-evidence-pipeline",
            provenance="stored-catalogue-field",
        ))
        created += int(result.created)
        reused += int(not result.created)
        by_type[evidence_type.value] = by_type.get(evidence_type.value, 0) + 1
    filename = parse_allowlisted_filename(raw_filename)
    if filename.status == "matched" and filename.value is not None:
        filename_matches = 1
        result = record_evidence(connection, EvidenceInput(
            content_identity_id=content_id, physical_instance_id=physical_id,
            source_id=source_id, analysis_run_id=analysis_run_id,
            evidence_type=EvidenceType.FILENAME_DERIVED, raw_value=raw_filename,
            value=filename.value, source_field="filename", source_locator=path,
            extractor_name=filename.parser_id, extractor_version=filename.parser_version,
            actor_type="system", actor_identifier="date-evidence-pipeline",
            provenance="allow-listed-filename-parser",
        ))
        created += int(result.created)
        reused += int(not result.created)
        by_type[EvidenceType.FILENAME_DERIVED.value] = 1
    elif filename.status in {"invalid", "ambiguous"}:
        filename_invalid = 1
        invalid += 1
    resolution = resolve_preferred_date(
        connection, content_identity_id=content_id, analysis_run_id=analysis_run_id,
        policy_version=policy_version,
    )
    candidate_count = created + reused
    outcome = (
        "recorded" if created else "reused" if reused else
        "invalid_metadata" if invalid else "no_candidate"
    )
    payload: dict[str, object] = {
        "evidence_created": created, "evidence_reused": reused,
        "evidence_by_type": by_type, "invalid_candidates": invalid,
        "filename_parser_matches": filename_matches,
        "filename_parser_invalid_ambiguous": filename_invalid,
        "preferred_status": resolution["status"], "resolution_reason": resolution["reason"],
        "preferred_state_changed": bool(resolution["changed"]),
        "owner_override_preserved": bool(resolution["owner_override_preserved"]),
    }
    return payload, outcome, candidate_count


def _report(
    connection: sqlite3.Connection, job_id: str, fingerprint: str,
    selection: dict[str, object],
) -> DateEvidencePipelineReport:
    rows = connection.execute(
        "SELECT content_identity_id,outcome,error,payload_json FROM date_evidence_job_items "
        "WHERE job_id=? ORDER BY item_key", (job_id,),
    ).fetchall()
    metrics: dict[str, Any] = {
        "config_fingerprint": fingerprint,
        **selection,
        "physical_candidates_considered": int(selection["selected_count"]),
        "physical_items_checkpointed": len(rows),
        "content_candidates_considered": len({int(row["content_identity_id"]) for row in rows}),
        "evidence_rows_created": 0, "evidence_rows_reused": 0,
        "evidence_by_type": {}, "filename_parser_matches": 0,
        "filename_parser_invalid_ambiguous": 0, "preferred_state_changes": 0,
        "unchanged_preferred_states": 0, "owner_overrides_preserved": 0,
        "job_errors": sum(1 for row in rows if row["outcome"] == "failed"),
    }
    latest: dict[int, dict[str, object]] = {}
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        metrics["evidence_rows_created"] += int(payload.get("evidence_created", 0))
        metrics["evidence_rows_reused"] += int(payload.get("evidence_reused", 0))
        metrics["filename_parser_matches"] += int(payload.get("filename_parser_matches", 0))
        metrics["filename_parser_invalid_ambiguous"] += int(
            payload.get("filename_parser_invalid_ambiguous", 0)
        )
        if "preferred_state_changed" in payload:
            metrics["preferred_state_changes"] += int(payload["preferred_state_changed"])
            metrics["unchanged_preferred_states"] += int(
                not payload["preferred_state_changed"]
            )
        for evidence_type, count in dict(payload.get("evidence_by_type", {})).items():
            by_type = metrics["evidence_by_type"]
            by_type[evidence_type] = by_type.get(evidence_type, 0) + int(count)
        if "preferred_status" in payload:
            latest[int(row["content_identity_id"])] = payload
    for status in ("resolved", "needs_review", "unknown"):
        metrics[f"{status}_count"] = sum(
            1 for payload in latest.values() if payload.get("preferred_status") == status
        )
    metrics["weak_evidence_only_count"] = sum(
        1 for payload in latest.values() if payload.get("resolution_reason") == "weak_evidence_only"
    )
    metrics["strong_conflict_count"] = sum(
        1 for payload in latest.values() if payload.get("resolution_reason") == "strong_conflict"
    )
    metrics["owner_overrides_preserved"] = sum(
        1 for payload in latest.values() if payload.get("owner_override_preserved")
    )
    return DateEvidencePipelineReport(job_id, "completed", metrics)
