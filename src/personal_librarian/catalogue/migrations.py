"""Ordered, transactional SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from personal_librarian.catalogue.errors import (
    CatalogueNotInitialisedError,
    MigrationError,
    SchemaVersionError,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS = (
    Migration(
        version=1,
        name="initial_catalogue",
        sql=r"""
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE sources (
    source_id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE acquisition_batches (
    batch_id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
    batch_key TEXT NOT NULL,
    acquisition_method TEXT,
    acquired_at TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (verification_status IN ('unknown', 'pending', 'verified', 'failed')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_id, batch_key),
    UNIQUE (batch_id, source_id)
);

CREATE TABLE analysis_runs (
    analysis_run_id INTEGER PRIMARY KEY,
    run_key TEXT NOT NULL UNIQUE,
    analysis_kind TEXT NOT NULL,
    algorithm TEXT,
    algorithm_version TEXT,
    parameters_json TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE content_identities (
    content_identity_id INTEGER PRIMARY KEY,
    identity_key TEXT NOT NULL UNIQUE,
    created_by_analysis_run_id INTEGER
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE physical_instances (
    physical_instance_id INTEGER PRIMARY KEY,
    instance_key TEXT NOT NULL UNIQUE,
    source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
    acquisition_batch_id INTEGER,
    content_identity_id INTEGER
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    raw_relative_path TEXT NOT NULL,
    display_path TEXT,
    relative_path_comparison_key TEXT,
    path_comparison_key_version TEXT,
    current_observed_path TEXT,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    extension TEXT,
    observed_created_at TEXT,
    observed_modified_at TEXT,
    first_observed_analysis_run_id INTEGER
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (relative_path_comparison_key IS NULL AND path_comparison_key_version IS NULL)
        OR
        (relative_path_comparison_key IS NOT NULL AND path_comparison_key_version IS NOT NULL)
    ),
    FOREIGN KEY (acquisition_batch_id, source_id)
        REFERENCES acquisition_batches(batch_id, source_id) ON DELETE RESTRICT
);

CREATE TABLE hash_observations (
    hash_observation_id INTEGER PRIMARY KEY,
    physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    algorithm TEXT NOT NULL,
    algorithm_version TEXT,
    hash_value TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (physical_instance_id, analysis_run_id, algorithm)
);

CREATE TABLE content_identity_hashes (
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    algorithm TEXT NOT NULL,
    hash_value TEXT NOT NULL,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    asserted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (content_identity_id, algorithm, hash_value),
    UNIQUE (content_identity_id, algorithm),
    UNIQUE (algorithm, hash_value)
);

CREATE TABLE similarity_relationships (
    similarity_relationship_id INTEGER PRIMARY KEY,
    relationship_key TEXT NOT NULL UNIQUE,
    left_content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    right_content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    relationship_type TEXT NOT NULL DEFAULT 'perceptual_similarity',
    phash_distance INTEGER CHECK (phash_distance IS NULL OR phash_distance >= 0),
    dhash_distance INTEGER CHECK (dhash_distance IS NULL OR dhash_distance >= 0),
    review_tier TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (left_content_identity_id < right_content_identity_id),
    CHECK (phash_distance IS NOT NULL OR dhash_distance IS NOT NULL),
    UNIQUE (
        left_content_identity_id,
        right_content_identity_id,
        analysis_run_id,
        relationship_type
    )
);

CREATE TABLE decision_events (
    decision_event_id INTEGER PRIMARY KEY,
    decision_key TEXT NOT NULL UNIQUE,
    canonical_scope TEXT NOT NULL
        CHECK (canonical_scope IN ('archival', 'display_export')),
    event_type TEXT NOT NULL
        CHECK (event_type IN ('proposal', 'approval', 'rejection', 'withdrawal', 'supersession')),
    subject_content_identity_id INTEGER
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    subject_physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    related_decision_event_id INTEGER
        REFERENCES decision_events(decision_event_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('owner', 'system')),
    actor_identifier TEXT NOT NULL,
    owner_approved INTEGER NOT NULL DEFAULT 0 CHECK (owner_approved IN (0, 1)),
    reason TEXT,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (subject_content_identity_id IS NOT NULL AND subject_physical_instance_id IS NULL)
        OR
        (subject_content_identity_id IS NULL AND subject_physical_instance_id IS NOT NULL)
    ),
    CHECK (
        event_type = 'proposal'
        OR (owner_approved = 1 AND actor_type = 'owner')
    )
);

CREATE INDEX ix_acquisition_batches_source
    ON acquisition_batches(source_id);
CREATE INDEX ix_physical_instances_source_path_key
    ON physical_instances(source_id, relative_path_comparison_key);
CREATE INDEX ix_physical_instances_content
    ON physical_instances(content_identity_id);
CREATE INDEX ix_hash_observations_digest
    ON hash_observations(algorithm, hash_value);
CREATE INDEX ix_similarity_left
    ON similarity_relationships(left_content_identity_id);
CREATE INDEX ix_similarity_right
    ON similarity_relationships(right_content_identity_id);
CREATE INDEX ix_decision_events_subject_content
    ON decision_events(subject_content_identity_id, canonical_scope, recorded_at);
CREATE INDEX ix_decision_events_subject_instance
    ON decision_events(subject_physical_instance_id, canonical_scope, recorded_at);

CREATE TRIGGER decision_events_append_only_update
BEFORE UPDATE ON decision_events
BEGIN
    SELECT RAISE(ABORT, 'decision_events are append-only');
END;

CREATE TRIGGER decision_events_append_only_delete
BEFORE DELETE ON decision_events
BEGIN
    SELECT RAISE(ABORT, 'decision_events are append-only');
END;
""",
    ),
    Migration(
        version=2,
        name="evidence_import_foundation",
        sql=r"""
CREATE TABLE evidence_import_stages (
    import_stage_id INTEGER PRIMARY KEY,
    stage_key TEXT NOT NULL UNIQUE,
    importer_name TEXT NOT NULL,
    importer_version TEXT NOT NULL,
    analysis_run_id INTEGER NOT NULL UNIQUE
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    input_fingerprint_json TEXT NOT NULL,
    reconciliation_json TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE inventory_observations (
    inventory_observation_id INTEGER PRIMARY KEY,
    observation_key TEXT NOT NULL UNIQUE,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
    acquisition_batch_id INTEGER,
    row_ordinal INTEGER NOT NULL CHECK (row_ordinal > 0),
    raw_relative_path TEXT NOT NULL,
    relative_path_comparison_key TEXT NOT NULL,
    path_comparison_key_version TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    observed_modified_at TEXT,
    timestamp_state TEXT NOT NULL
        CHECK (timestamp_state IN ('aware', 'naive', 'missing')),
    matched_physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    match_method TEXT CHECK (
        match_method IS NULL OR match_method IN ('exact_path', 'unique_metadata')
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (analysis_run_id, row_ordinal),
    FOREIGN KEY (acquisition_batch_id, source_id)
        REFERENCES acquisition_batches(batch_id, source_id) ON DELETE RESTRICT,
    CHECK (
        (matched_physical_instance_id IS NULL AND match_method IS NULL)
        OR
        (matched_physical_instance_id IS NOT NULL AND match_method IS NOT NULL)
    )
);

CREATE TABLE instance_path_observations (
    path_observation_id INTEGER PRIMARY KEY,
    observation_key TEXT NOT NULL UNIQUE,
    physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    evidence_layer TEXT NOT NULL,
    raw_relative_path TEXT NOT NULL,
    absolute_path TEXT,
    relative_path_comparison_key TEXT NOT NULL,
    path_comparison_key_version TEXT NOT NULL,
    observed_modified_at TEXT,
    timestamp_state TEXT NOT NULL
        CHECK (timestamp_state IN ('aware', 'naive', 'missing')),
    is_authoritative_current INTEGER NOT NULL DEFAULT 0
        CHECK (is_authoritative_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (physical_instance_id, analysis_run_id, evidence_layer)
);

CREATE TABLE exact_duplicate_groups (
    exact_duplicate_group_id INTEGER PRIMARY KEY,
    group_key TEXT NOT NULL UNIQUE,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    copies INTEGER NOT NULL CHECK (copies >= 2),
    unique_sources INTEGER NOT NULL CHECK (unique_sources >= 1),
    source_pattern TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    redundant_copies INTEGER NOT NULL CHECK (redundant_copies >= 1),
    reclaimable_bytes INTEGER NOT NULL CHECK (reclaimable_bytes >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (content_identity_id, analysis_run_id)
);

CREATE TABLE exact_duplicate_memberships (
    exact_duplicate_group_id INTEGER NOT NULL
        REFERENCES exact_duplicate_groups(exact_duplicate_group_id) ON DELETE RESTRICT,
    physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    reported_copies INTEGER NOT NULL CHECK (reported_copies >= 2),
    PRIMARY KEY (exact_duplicate_group_id, physical_instance_id)
);

CREATE TABLE content_hash_observations (
    content_hash_observation_id INTEGER PRIMARY KEY,
    observation_key TEXT NOT NULL UNIQUE,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    algorithm TEXT NOT NULL,
    algorithm_version TEXT,
    hash_value TEXT,
    status TEXT NOT NULL,
    error TEXT,
    representative_path TEXT,
    representative_source TEXT,
    reported_copies INTEGER CHECK (reported_copies IS NULL OR reported_copies >= 1),
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (content_identity_id, analysis_run_id, algorithm)
);

CREATE TABLE similarity_groups (
    similarity_group_id INTEGER PRIMARY KEY,
    group_key TEXT NOT NULL UNIQUE,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    external_group_id TEXT NOT NULL,
    unique_contents INTEGER NOT NULL CHECK (unique_contents >= 2),
    candidate_pairs INTEGER NOT NULL CHECK (candidate_pairs >= 1),
    min_phash_distance INTEGER NOT NULL CHECK (min_phash_distance >= 0),
    max_phash_distance INTEGER NOT NULL CHECK (max_phash_distance >= min_phash_distance),
    min_dhash_distance INTEGER NOT NULL CHECK (min_dhash_distance >= 0),
    max_dhash_distance INTEGER NOT NULL CHECK (max_dhash_distance >= min_dhash_distance),
    unique_sources INTEGER NOT NULL CHECK (unique_sources >= 1),
    sources_text TEXT NOT NULL,
    review_tier TEXT NOT NULL,
    is_large_ambiguous INTEGER NOT NULL CHECK (is_large_ambiguous IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (analysis_run_id, external_group_id)
);

CREATE TABLE similarity_group_memberships (
    similarity_group_id INTEGER NOT NULL
        REFERENCES similarity_groups(similarity_group_id) ON DELETE RESTRICT,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    PRIMARY KEY (similarity_group_id, content_identity_id)
);

CREATE TABLE similarity_group_relationships (
    similarity_group_id INTEGER NOT NULL
        REFERENCES similarity_groups(similarity_group_id) ON DELETE RESTRICT,
    similarity_relationship_id INTEGER NOT NULL
        REFERENCES similarity_relationships(similarity_relationship_id) ON DELETE RESTRICT,
    PRIMARY KEY (similarity_group_id, similarity_relationship_id),
    UNIQUE (similarity_relationship_id)
);

CREATE INDEX ix_inventory_observations_source_path
    ON inventory_observations(source_id, relative_path_comparison_key);
CREATE INDEX ix_inventory_observations_metadata
    ON inventory_observations(source_id, size_bytes, extension, observed_modified_at);
CREATE INDEX ix_inventory_observations_match
    ON inventory_observations(matched_physical_instance_id);
CREATE INDEX ix_instance_path_observations_instance
    ON instance_path_observations(physical_instance_id, is_authoritative_current);
CREATE INDEX ix_exact_duplicate_memberships_instance
    ON exact_duplicate_memberships(physical_instance_id);
CREATE INDEX ix_content_hash_observations_digest
    ON content_hash_observations(algorithm, hash_value);
CREATE INDEX ix_similarity_group_memberships_content
    ON similarity_group_memberships(content_identity_id);
""",
    ),
    Migration(
        version=3,
        name="reproducible_inventory_hash_pipeline",
        sql=r"""
CREATE TABLE pipeline_jobs (
    job_id TEXT PRIMARY KEY,
    job_kind TEXT NOT NULL
        CHECK (job_kind IN ('inventory', 'sha256', 'exact_duplicates')),
    pipeline_version TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    config_json TEXT NOT NULL,
    analysis_run_id INTEGER NOT NULL UNIQUE
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'interrupted', 'failed')),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT
);

CREATE TABLE pipeline_job_items (
    job_id TEXT NOT NULL REFERENCES pipeline_jobs(job_id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL,
    physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    raw_relative_path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    extension TEXT,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    modified_time_ns INTEGER,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'inventory_success', 'unsupported_extension', 'zero_byte_inventory',
        'hash_success', 'hash_reused', 'zero_byte_hashed', 'zero_byte_reused',
        'unreadable', 'permission_denied', 'disappeared', 'changed_during_hash'
    )),
    error TEXT,
    sha256 TEXT,
    reused_from_hash_observation_id INTEGER
        REFERENCES pipeline_hash_observations(pipeline_hash_observation_id) ON DELETE RESTRICT,
    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (job_id, item_key),
    CHECK (sha256 IS NULL OR length(sha256) = 64)
);

CREATE TABLE pipeline_hash_observations (
    pipeline_hash_observation_id INTEGER PRIMARY KEY,
    physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER NOT NULL
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    algorithm TEXT NOT NULL DEFAULT 'SHA-256' CHECK (algorithm = 'SHA-256'),
    pipeline_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'hash_success', 'hash_reused', 'zero_byte_hashed', 'zero_byte_reused',
        'unreadable', 'permission_denied', 'disappeared', 'changed_during_hash'
    )),
    hash_value TEXT,
    size_bytes_before INTEGER CHECK (size_bytes_before IS NULL OR size_bytes_before >= 0),
    modified_time_ns_before INTEGER,
    size_bytes_after INTEGER CHECK (size_bytes_after IS NULL OR size_bytes_after >= 0),
    modified_time_ns_after INTEGER,
    reused_from_hash_observation_id INTEGER
        REFERENCES pipeline_hash_observations(pipeline_hash_observation_id) ON DELETE RESTRICT,
    error TEXT,
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (physical_instance_id, analysis_run_id),
    CHECK (hash_value IS NULL OR length(hash_value) = 64),
    CHECK (
        status NOT IN ('hash_success', 'hash_reused', 'zero_byte_hashed', 'zero_byte_reused')
        OR hash_value IS NOT NULL
    )
);

CREATE INDEX ix_pipeline_job_items_outcome
    ON pipeline_job_items(job_id, outcome);
CREATE INDEX ix_pipeline_hash_reuse
    ON pipeline_hash_observations(
        physical_instance_id, size_bytes_after, modified_time_ns_after, status
    );
""",
    ),
    Migration(
        version=4,
        name="reproducible_near_duplicate_pipeline",
        sql=r"""
ALTER TABLE content_hash_observations
    ADD COLUMN physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT;

CREATE TABLE similarity_pipeline_jobs (
    job_id TEXT PRIMARY KEY,
    job_kind TEXT NOT NULL
        CHECK (job_kind IN ('perceptual_hash', 'similarity_analysis', 'similarity_groups')),
    pipeline_version TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    config_json TEXT NOT NULL,
    analysis_run_id INTEGER NOT NULL UNIQUE
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'interrupted', 'failed')),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT
);

CREATE TABLE similarity_pipeline_items (
    job_id TEXT NOT NULL
        REFERENCES similarity_pipeline_jobs(job_id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL,
    content_identity_id INTEGER
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'success', 'reused', 'decode_error', 'missing', 'unreadable',
        'unsupported_format', 'zero_byte', 'relationship', 'group'
    )),
    payload_json TEXT,
    error TEXT,
    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (job_id, item_key)
);

CREATE INDEX ix_content_hash_observations_physical
    ON content_hash_observations(physical_instance_id, algorithm, algorithm_version);
CREATE INDEX ix_similarity_pipeline_items_outcome
    ON similarity_pipeline_items(job_id, outcome);
""",
    ),
    Migration(
        version=5,
        name="review_and_canonical_decision_workflow",
        sql=r"""
ALTER TABLE decision_events ADD COLUMN workflow_action TEXT
    CHECK (workflow_action IS NULL OR workflow_action IN (
        'nominate', 'approve', 'reject', 'supersede', 'abstain'
    ));
ALTER TABLE decision_events ADD COLUMN exact_content_identity_id INTEGER
    REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT;
ALTER TABLE decision_events ADD COLUMN similarity_group_id INTEGER
    REFERENCES similarity_groups(similarity_group_id) ON DELETE RESTRICT;
ALTER TABLE decision_events ADD COLUMN secondary_related_decision_event_id INTEGER
    REFERENCES decision_events(decision_event_id) ON DELETE RESTRICT;

CREATE INDEX ix_decision_events_exact_context
    ON decision_events(exact_content_identity_id, canonical_scope, decision_event_id);
CREATE INDEX ix_decision_events_similar_context
    ON decision_events(similarity_group_id, canonical_scope, decision_event_id);
CREATE INDEX ix_decision_events_workflow_action
    ON decision_events(workflow_action, decision_event_id);
""",
    ),
    Migration(
        version=6,
        name="safe_action_planning_and_preflight",
        sql=r"""
CREATE TABLE action_plans (
    action_plan_id INTEGER PRIMARY KEY,
    plan_key TEXT NOT NULL UNIQUE,
    planner_version TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('copy', 'move', 'rename', 'quarantine')),
    canonical_scope TEXT NOT NULL CHECK (canonical_scope IN ('archival', 'display_export')),
    context_type TEXT NOT NULL CHECK (context_type IN ('exact', 'similar')),
    context_id INTEGER NOT NULL CHECK (context_id >= 1),
    approval_decision_event_id INTEGER NOT NULL
        REFERENCES decision_events(decision_event_id) ON DELETE RESTRICT,
    decision_fingerprint TEXT NOT NULL,
    destination_root TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    safety_margin_bytes INTEGER NOT NULL CHECK (safety_margin_bytes >= 0),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'preflight_passed', 'preflight_failed', 'stale', 'invalidated')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    invalidated_at TEXT,
    invalidation_reason TEXT
);

CREATE TABLE action_plan_items (
    action_plan_item_id INTEGER PRIMARY KEY,
    action_plan_id INTEGER NOT NULL
        REFERENCES action_plans(action_plan_id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL UNIQUE,
    action_type TEXT NOT NULL CHECK (action_type IN ('copy', 'move', 'rename', 'quarantine')),
    source_physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    source_raw_path TEXT NOT NULL,
    source_current_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    sha256 TEXT NOT NULL,
    expected_size_bytes INTEGER NOT NULL CHECK (expected_size_bytes >= 0),
    expected_modified_at TEXT,
    expected_filesystem_mtime_ns INTEGER,
    canonical_scope TEXT NOT NULL CHECK (canonical_scope IN ('archival', 'display_export')),
    context_type TEXT NOT NULL CHECK (context_type IN ('exact', 'similar')),
    context_id INTEGER NOT NULL CHECK (context_id >= 1),
    approval_decision_event_id INTEGER NOT NULL
        REFERENCES decision_events(decision_event_id) ON DELETE RESTRICT,
    reason TEXT NOT NULL,
    expected_preconditions_json TEXT NOT NULL,
    expected_postconditions_json TEXT NOT NULL,
    restore_provenance_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (action_plan_id, source_physical_instance_id, destination_path)
);

CREATE TABLE action_plan_preflight_results (
    action_plan_preflight_result_id INTEGER PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    action_plan_id INTEGER NOT NULL
        REFERENCES action_plans(action_plan_id) ON DELETE RESTRICT,
    action_plan_item_id INTEGER NOT NULL
        REFERENCES action_plan_items(action_plan_item_id) ON DELETE RESTRICT,
    source_state TEXT NOT NULL,
    destination_state TEXT NOT NULL,
    conflict_state TEXT NOT NULL,
    free_space_state TEXT NOT NULL CHECK (free_space_state IN ('PASS', 'FAIL', 'UNKNOWN')),
    safety_state TEXT NOT NULL CHECK (safety_state IN ('PASS', 'FAIL', 'UNKNOWN')),
    overall_state TEXT NOT NULL CHECK (overall_state IN ('PASS', 'FAIL', 'STALE')),
    observed_free_bytes INTEGER,
    required_bytes INTEGER NOT NULL CHECK (required_bytes >= 0),
    details_json TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (attempt_id, action_plan_item_id)
);

CREATE TABLE action_plan_events (
    action_plan_event_id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    action_plan_id INTEGER NOT NULL
        REFERENCES action_plans(action_plan_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'created', 'preflight_passed', 'preflight_failed', 'stale', 'invalidated'
    )),
    actor_identifier TEXT NOT NULL,
    reason TEXT,
    attempt_id TEXT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX ix_action_plans_status ON action_plans(status, created_at);
CREATE INDEX ix_action_plan_items_plan ON action_plan_items(action_plan_id, item_key);
CREATE INDEX ix_action_preflight_attempt ON action_plan_preflight_results(attempt_id);
CREATE INDEX ix_action_plan_events_plan ON action_plan_events(action_plan_id, action_plan_event_id);

CREATE TRIGGER action_plan_items_append_only_update
BEFORE UPDATE ON action_plan_items BEGIN
    SELECT RAISE(ABORT, 'action_plan_items are append-only');
END;
CREATE TRIGGER action_plan_items_append_only_delete
BEFORE DELETE ON action_plan_items BEGIN
    SELECT RAISE(ABORT, 'action_plan_items are append-only');
END;
CREATE TRIGGER action_preflight_append_only_update
BEFORE UPDATE ON action_plan_preflight_results BEGIN
    SELECT RAISE(ABORT, 'action_plan_preflight_results are append-only');
END;
CREATE TRIGGER action_preflight_append_only_delete
BEFORE DELETE ON action_plan_preflight_results BEGIN
    SELECT RAISE(ABORT, 'action_plan_preflight_results are append-only');
END;
CREATE TRIGGER action_plan_events_append_only_update
BEFORE UPDATE ON action_plan_events BEGIN
    SELECT RAISE(ABORT, 'action_plan_events are append-only');
END;
CREATE TRIGGER action_plan_events_append_only_delete
BEFORE DELETE ON action_plan_events BEGIN
    SELECT RAISE(ABORT, 'action_plan_events are append-only');
END;
CREATE TRIGGER action_plans_no_delete
BEFORE DELETE ON action_plans BEGIN
    SELECT RAISE(ABORT, 'action_plans cannot be deleted');
END;
CREATE TRIGGER action_plans_snapshot_immutable
BEFORE UPDATE ON action_plans
WHEN OLD.plan_key IS NOT NEW.plan_key
  OR OLD.planner_version IS NOT NEW.planner_version
  OR OLD.policy_id IS NOT NEW.policy_id
  OR OLD.action_type IS NOT NEW.action_type
  OR OLD.canonical_scope IS NOT NEW.canonical_scope
  OR OLD.context_type IS NOT NEW.context_type
  OR OLD.context_id IS NOT NEW.context_id
  OR OLD.approval_decision_event_id IS NOT NEW.approval_decision_event_id
  OR OLD.decision_fingerprint IS NOT NEW.decision_fingerprint
  OR OLD.destination_root IS NOT NEW.destination_root
  OR OLD.requested_by IS NOT NEW.requested_by
  OR OLD.safety_margin_bytes IS NOT NEW.safety_margin_bytes
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    SELECT RAISE(ABORT, 'action plan snapshot fields are immutable');
END;
""",
    ),
    Migration(
        version=7,
        name="reversible_quarantine_execution",
        sql=r"""
CREATE TABLE action_executions (
    action_execution_id INTEGER PRIMARY KEY,
    execution_key TEXT NOT NULL UNIQUE,
    action_plan_id INTEGER NOT NULL
        REFERENCES action_plans(action_plan_id) ON DELETE RESTRICT,
    action_plan_item_id INTEGER NOT NULL UNIQUE
        REFERENCES action_plan_items(action_plan_item_id) ON DELETE RESTRICT,
    preflight_result_id INTEGER NOT NULL
        REFERENCES action_plan_preflight_results(action_plan_preflight_result_id)
        ON DELETE RESTRICT,
    action_type TEXT NOT NULL CHECK (action_type = 'quarantine'),
    actor_identifier TEXT NOT NULL,
    source_path_snapshot TEXT NOT NULL,
    quarantine_root TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    original_physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    approval_decision_event_id INTEGER NOT NULL
        REFERENCES decision_events(decision_event_id) ON DELETE RESTRICT,
    expected_sha256 TEXT NOT NULL,
    pre_execution_sha256 TEXT,
    post_execution_sha256 TEXT,
    expected_size_bytes INTEGER NOT NULL CHECK (expected_size_bytes >= 0),
    status TEXT NOT NULL CHECK (status IN (
        'requested', 'validating', 'moving', 'verifying', 'succeeded',
        'failed', 'recovery_required', 'restored'
    )),
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    failure_reason TEXT,
    recovery_details_json TEXT
);

CREATE TABLE quarantine_records (
    quarantine_record_id INTEGER PRIMARY KEY,
    record_key TEXT NOT NULL UNIQUE,
    action_execution_id INTEGER NOT NULL UNIQUE
        REFERENCES action_executions(action_execution_id) ON DELETE RESTRICT,
    original_physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    original_path TEXT NOT NULL,
    quarantine_path TEXT NOT NULL UNIQUE,
    expected_sha256 TEXT NOT NULL,
    expected_size_bytes INTEGER NOT NULL CHECK (expected_size_bytes >= 0),
    state TEXT NOT NULL CHECK (state IN (
        'pending', 'quarantined', 'restored', 'recovery_required'
    )),
    quarantined_at TEXT,
    restored_at TEXT,
    last_reconciliation_state TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE action_execution_events (
    action_execution_event_id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    action_execution_id INTEGER NOT NULL
        REFERENCES action_executions(action_execution_id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'requested', 'validating', 'moving', 'verifying', 'succeeded',
        'failed', 'recovery_required', 'reconciled', 'restore_requested',
        'restoring', 'restore_failed', 'restored'
    )),
    actor_identifier TEXT NOT NULL,
    details_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE physical_instance_location_events (
    location_event_id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    action_execution_id INTEGER NOT NULL
        REFERENCES action_executions(action_execution_id) ON DELETE RESTRICT,
    physical_instance_id INTEGER NOT NULL
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    location_action TEXT NOT NULL CHECK (location_action IN ('quarantined', 'restored')),
    from_path TEXT NOT NULL,
    to_path TEXT NOT NULL,
    verified_sha256 TEXT NOT NULL,
    verified_size_bytes INTEGER NOT NULL CHECK (verified_size_bytes >= 0),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX ix_action_executions_status
    ON action_executions(status, requested_at);
CREATE INDEX ix_action_execution_events_execution
    ON action_execution_events(action_execution_id, action_execution_event_id);
CREATE INDEX ix_location_events_instance
    ON physical_instance_location_events(physical_instance_id, location_event_id);

CREATE TRIGGER action_executions_no_delete
BEFORE DELETE ON action_executions BEGIN
    SELECT RAISE(ABORT, 'action executions cannot be deleted');
END;
CREATE TRIGGER quarantine_records_no_delete
BEFORE DELETE ON quarantine_records BEGIN
    SELECT RAISE(ABORT, 'quarantine records cannot be deleted');
END;
CREATE TRIGGER quarantine_record_snapshot_immutable
BEFORE UPDATE ON quarantine_records
WHEN OLD.record_key IS NOT NEW.record_key
  OR OLD.action_execution_id IS NOT NEW.action_execution_id
  OR OLD.original_physical_instance_id IS NOT NEW.original_physical_instance_id
  OR OLD.content_identity_id IS NOT NEW.content_identity_id
  OR OLD.original_path IS NOT NEW.original_path
  OR OLD.quarantine_path IS NOT NEW.quarantine_path
  OR OLD.expected_sha256 IS NOT NEW.expected_sha256
  OR OLD.expected_size_bytes IS NOT NEW.expected_size_bytes
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    SELECT RAISE(ABORT, 'quarantine record snapshot fields are immutable');
END;
CREATE TRIGGER action_execution_events_append_only_update
BEFORE UPDATE ON action_execution_events BEGIN
    SELECT RAISE(ABORT, 'action execution events are append-only');
END;
CREATE TRIGGER action_execution_events_append_only_delete
BEFORE DELETE ON action_execution_events BEGIN
    SELECT RAISE(ABORT, 'action execution events are append-only');
END;
CREATE TRIGGER location_events_append_only_update
BEFORE UPDATE ON physical_instance_location_events BEGIN
    SELECT RAISE(ABORT, 'physical instance location events are append-only');
END;
CREATE TRIGGER location_events_append_only_delete
BEFORE DELETE ON physical_instance_location_events BEGIN
    SELECT RAISE(ABORT, 'physical instance location events are append-only');
END;
CREATE TRIGGER action_execution_snapshot_immutable
BEFORE UPDATE ON action_executions
WHEN OLD.execution_key IS NOT NEW.execution_key
  OR OLD.action_plan_id IS NOT NEW.action_plan_id
  OR OLD.action_plan_item_id IS NOT NEW.action_plan_item_id
  OR OLD.preflight_result_id IS NOT NEW.preflight_result_id
  OR OLD.action_type IS NOT NEW.action_type
  OR OLD.actor_identifier IS NOT NEW.actor_identifier
  OR OLD.source_path_snapshot IS NOT NEW.source_path_snapshot
  OR OLD.quarantine_root IS NOT NEW.quarantine_root
  OR OLD.destination_path IS NOT NEW.destination_path
  OR OLD.original_physical_instance_id IS NOT NEW.original_physical_instance_id
  OR OLD.content_identity_id IS NOT NEW.content_identity_id
  OR OLD.approval_decision_event_id IS NOT NEW.approval_decision_event_id
  OR OLD.expected_sha256 IS NOT NEW.expected_sha256
  OR OLD.expected_size_bytes IS NOT NEW.expected_size_bytes
  OR OLD.requested_at IS NOT NEW.requested_at
BEGIN
    SELECT RAISE(ABORT, 'action execution snapshot fields are immutable');
END;
""",
    ),
    Migration(
        version=8,
        name="production_catalogue_identity",
        sql=r"""
CREATE TABLE catalogue_identity (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    catalogue_uuid TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    application_version TEXT NOT NULL,
    schema_version_at_bootstrap INTEGER NOT NULL CHECK (schema_version_at_bootstrap > 0),
    catalogue_role TEXT NOT NULL CHECK (catalogue_role IN ('production', 'non-production')),
    app_data_root_fingerprint TEXT,
    bootstrap_provenance_json TEXT NOT NULL,
    production_marked_at TEXT
);

CREATE TRIGGER catalogue_identity_no_delete
BEFORE DELETE ON catalogue_identity BEGIN
    SELECT RAISE(ABORT, 'catalogue identity cannot be deleted');
END;
CREATE TRIGGER catalogue_identity_snapshot_immutable
BEFORE UPDATE ON catalogue_identity
WHEN OLD.singleton_id IS NOT NEW.singleton_id
  OR OLD.catalogue_uuid IS NOT NEW.catalogue_uuid
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.application_version IS NOT NEW.application_version
  OR OLD.schema_version_at_bootstrap IS NOT NEW.schema_version_at_bootstrap
  OR OLD.app_data_root_fingerprint IS NOT NEW.app_data_root_fingerprint
  OR OLD.bootstrap_provenance_json IS NOT NEW.bootstrap_provenance_json
BEGIN
    SELECT RAISE(ABORT, 'catalogue identity snapshot fields are immutable');
END;
CREATE TRIGGER catalogue_identity_production_one_way
BEFORE UPDATE ON catalogue_identity
WHEN OLD.catalogue_role = 'production'
  OR NEW.catalogue_role != 'production'
  OR OLD.production_marked_at IS NOT NULL
  OR NEW.production_marked_at IS NULL
BEGIN
    SELECT RAISE(ABORT, 'catalogue production role may be assigned exactly once');
END;
""",
    ),
    Migration(
        version=9,
        name="manual_logical_organisation",
        sql=r"""
CREATE TABLE albums (
    album_id INTEGER PRIMARY KEY,
    album_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 200),
    description TEXT CHECK (description IS NULL OR length(description) <= 4000),
    album_kind TEXT NOT NULL DEFAULT 'manual'
        CHECK (length(trim(album_kind)) BETWEEN 1 AND 50),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    provenance_type TEXT NOT NULL CHECK (provenance_type IN ('owner', 'system', 'ai')),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    archived_at TEXT,
    CHECK (
        (state = 'active' AND archived_at IS NULL)
        OR (state = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE TABLE album_memberships (
    album_membership_id INTEGER PRIMARY KEY,
    album_id INTEGER NOT NULL REFERENCES albums(album_id) ON DELETE RESTRICT,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    membership_state TEXT NOT NULL DEFAULT 'active'
        CHECK (membership_state IN ('active', 'removed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    provenance_type TEXT NOT NULL CHECK (provenance_type IN ('owner', 'system', 'ai')),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    ended_at TEXT,
    UNIQUE (album_id, content_identity_id),
    CHECK (
        (membership_state = 'active' AND ended_at IS NULL)
        OR (membership_state = 'removed' AND ended_at IS NOT NULL)
    )
);

CREATE TABLE tags (
    tag_id INTEGER PRIMARY KEY,
    tag_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 200),
    namespace TEXT CHECK (namespace IS NULL OR length(trim(namespace)) BETWEEN 1 AND 100),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    provenance_type TEXT NOT NULL CHECK (provenance_type IN ('owner', 'system', 'ai')),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    archived_at TEXT,
    CHECK (
        (state = 'active' AND archived_at IS NULL)
        OR (state = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE TABLE content_tags (
    content_tag_id INTEGER PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE RESTRICT,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    membership_state TEXT NOT NULL DEFAULT 'active'
        CHECK (membership_state IN ('active', 'removed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    provenance_type TEXT NOT NULL CHECK (provenance_type IN ('owner', 'system', 'ai')),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    ended_at TEXT,
    UNIQUE (tag_id, content_identity_id),
    CHECK (
        (membership_state = 'active' AND ended_at IS NULL)
        OR (membership_state = 'removed' AND ended_at IS NOT NULL)
    )
);

CREATE TABLE organisation_events (
    organisation_event_id INTEGER PRIMARY KEY,
    event_uuid TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'album_created', 'album_renamed', 'album_archived', 'album_restored',
        'album_member_added', 'album_member_removed', 'album_member_restored',
        'tag_created', 'tag_archived', 'tag_restored',
        'tag_member_added', 'tag_member_removed', 'tag_member_restored'
    )),
    album_id INTEGER REFERENCES albums(album_id) ON DELETE RESTRICT,
    album_membership_id INTEGER
        REFERENCES album_memberships(album_membership_id) ON DELETE RESTRICT,
    tag_id INTEGER REFERENCES tags(tag_id) ON DELETE RESTRICT,
    content_tag_id INTEGER REFERENCES content_tags(content_tag_id) ON DELETE RESTRICT,
    content_identity_id INTEGER
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('owner', 'system', 'ai')),
    actor_identifier TEXT NOT NULL CHECK (length(trim(actor_identifier)) BETWEEN 1 AND 200),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 2000),
    details_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        album_id IS NOT NULL OR album_membership_id IS NOT NULL
        OR tag_id IS NOT NULL OR content_tag_id IS NOT NULL
    )
);

CREATE INDEX ix_albums_state_name ON albums(state, name, album_id);
CREATE INDEX ix_album_memberships_album_state
    ON album_memberships(album_id, membership_state, content_identity_id);
CREATE INDEX ix_album_memberships_content_state
    ON album_memberships(content_identity_id, membership_state, album_id);
CREATE INDEX ix_tags_state_namespace_name ON tags(state, namespace, name, tag_id);
CREATE INDEX ix_content_tags_tag_state
    ON content_tags(tag_id, membership_state, content_identity_id);
CREATE INDEX ix_content_tags_content_state
    ON content_tags(content_identity_id, membership_state, tag_id);
CREATE INDEX ix_organisation_events_album
    ON organisation_events(album_id, organisation_event_id);
CREATE INDEX ix_organisation_events_content
    ON organisation_events(content_identity_id, organisation_event_id);
CREATE INDEX ix_organisation_events_tag
    ON organisation_events(tag_id, organisation_event_id);

CREATE TRIGGER albums_no_delete
BEFORE DELETE ON albums BEGIN
    SELECT RAISE(ABORT, 'albums cannot be deleted');
END;
CREATE TRIGGER albums_snapshot_immutable
BEFORE UPDATE ON albums
WHEN OLD.album_uuid IS NOT NEW.album_uuid
  OR OLD.album_kind IS NOT NEW.album_kind
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.provenance_type IS NOT NEW.provenance_type
  OR OLD.provenance IS NOT NEW.provenance
BEGIN
    SELECT RAISE(ABORT, 'album identity and creation provenance are immutable');
END;
CREATE TRIGGER album_memberships_no_delete
BEFORE DELETE ON album_memberships BEGIN
    SELECT RAISE(ABORT, 'album memberships cannot be deleted');
END;
CREATE TRIGGER album_memberships_snapshot_immutable
BEFORE UPDATE ON album_memberships
WHEN OLD.album_id IS NOT NEW.album_id
  OR OLD.content_identity_id IS NOT NEW.content_identity_id
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.provenance_type IS NOT NEW.provenance_type
  OR OLD.provenance IS NOT NEW.provenance
BEGIN
    SELECT RAISE(ABORT, 'album membership identity and creation provenance are immutable');
END;
CREATE TRIGGER tags_no_delete
BEFORE DELETE ON tags BEGIN
    SELECT RAISE(ABORT, 'tags cannot be deleted');
END;
CREATE TRIGGER tags_snapshot_immutable
BEFORE UPDATE ON tags
WHEN OLD.tag_uuid IS NOT NEW.tag_uuid
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.provenance_type IS NOT NEW.provenance_type
  OR OLD.provenance IS NOT NEW.provenance
BEGIN
    SELECT RAISE(ABORT, 'tag identity and creation provenance are immutable');
END;
CREATE TRIGGER content_tags_no_delete
BEFORE DELETE ON content_tags BEGIN
    SELECT RAISE(ABORT, 'content tags cannot be deleted');
END;
CREATE TRIGGER content_tags_snapshot_immutable
BEFORE UPDATE ON content_tags
WHEN OLD.tag_id IS NOT NEW.tag_id
  OR OLD.content_identity_id IS NOT NEW.content_identity_id
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.provenance_type IS NOT NEW.provenance_type
  OR OLD.provenance IS NOT NEW.provenance
BEGIN
    SELECT RAISE(ABORT, 'content tag identity and creation provenance are immutable');
END;
CREATE TRIGGER organisation_events_append_only_update
BEFORE UPDATE ON organisation_events BEGIN
    SELECT RAISE(ABORT, 'organisation events are append-only');
END;
CREATE TRIGGER organisation_events_append_only_delete
BEFORE DELETE ON organisation_events BEGIN
    SELECT RAISE(ABORT, 'organisation events are append-only');
END;
""",
    ),
    Migration(
        version=10,
        name="preferred_date_evidence_and_collections",
        sql=r"""
CREATE TABLE content_date_evidence (
    date_evidence_id INTEGER PRIMARY KEY,
    evidence_key TEXT NOT NULL UNIQUE CHECK (length(trim(evidence_key)) > 0),
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    source_id INTEGER REFERENCES sources(source_id) ON DELETE RESTRICT,
    analysis_run_id INTEGER REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN (
        'owner_set', 'exif_datetime_original', 'embedded_video_capture',
        'google_photos_takeout', 'onedrive_source_metadata', 'filename_derived',
        'filesystem_modified', 'filesystem_created', 'specialist_import'
    )),
    evidence_role TEXT NOT NULL CHECK (evidence_role IN ('observed', 'owner_correction')),
    source_field TEXT CHECK (source_field IS NULL OR length(trim(source_field)) > 0),
    source_locator TEXT CHECK (source_locator IS NULL OR length(trim(source_locator)) > 0),
    raw_value TEXT NOT NULL,
    precision TEXT NOT NULL CHECK (precision IN ('year', 'year_month', 'date', 'datetime')),
    time_precision TEXT CHECK (time_precision IN ('minute', 'second', 'fraction')),
    date_year INTEGER NOT NULL CHECK (date_year BETWEEN 1 AND 9999),
    date_month INTEGER,
    date_day INTEGER,
    time_hour INTEGER,
    time_minute INTEGER,
    time_second INTEGER,
    time_fraction TEXT,
    timezone_state TEXT NOT NULL
        CHECK (timezone_state IN ('not_applicable', 'unknown', 'known_offset')),
    utc_offset_minutes INTEGER,
    timezone_name TEXT CHECK (timezone_name IS NULL OR length(trim(timezone_name)) > 0),
    extractor_name TEXT CHECK (extractor_name IS NULL OR length(trim(extractor_name)) > 0),
    extractor_version TEXT CHECK (
        extractor_version IS NULL OR length(trim(extractor_version)) > 0
    ),
    actor_type TEXT NOT NULL CHECK (actor_type IN ('owner', 'system')),
    actor_identifier TEXT NOT NULL CHECK (length(trim(actor_identifier)) > 0),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (precision = 'year' AND date_month IS NULL AND date_day IS NULL)
        OR (precision = 'year_month' AND date_month IS NOT NULL
            AND date_month BETWEEN 1 AND 12 AND date_day IS NULL)
        OR (precision IN ('date', 'datetime') AND date_month IS NOT NULL
            AND date_day IS NOT NULL AND date_month BETWEEN 1 AND 12
            AND date_day BETWEEN 1 AND CASE date_month
                WHEN 2 THEN CASE
                    WHEN date_year % 400 = 0 OR (date_year % 4 = 0 AND date_year % 100 != 0)
                    THEN 29 ELSE 28 END
                WHEN 4 THEN 30 WHEN 6 THEN 30 WHEN 9 THEN 30 WHEN 11 THEN 30
                ELSE 31 END)
    ),
    CHECK (
        (precision != 'datetime' AND time_precision IS NULL AND time_hour IS NULL
            AND time_minute IS NULL AND time_second IS NULL AND time_fraction IS NULL)
        OR (precision = 'datetime' AND time_precision IS NOT NULL
            AND time_hour IS NOT NULL AND time_minute IS NOT NULL
            AND time_hour BETWEEN 0 AND 23 AND time_minute BETWEEN 0 AND 59 AND (
                (time_precision = 'minute' AND time_second IS NULL AND time_fraction IS NULL)
                OR (time_precision = 'second' AND time_second IS NOT NULL
                    AND time_second BETWEEN 0 AND 59
                    AND time_fraction IS NULL)
                OR (time_precision = 'fraction' AND time_second IS NOT NULL
                    AND time_second BETWEEN 0 AND 59 AND time_fraction IS NOT NULL
                    AND length(time_fraction) BETWEEN 1 AND 9
                    AND time_fraction NOT GLOB '*[^0-9]*')
            ))
    ),
    CHECK (
        (precision != 'datetime' AND timezone_state = 'not_applicable'
            AND utc_offset_minutes IS NULL AND timezone_name IS NULL)
        OR (precision = 'datetime' AND timezone_state = 'unknown'
            AND utc_offset_minutes IS NULL AND timezone_name IS NULL)
        OR (precision = 'datetime' AND timezone_state = 'known_offset'
            AND utc_offset_minutes IS NOT NULL AND utc_offset_minutes BETWEEN -840 AND 840)
    ),
    CHECK (
        (evidence_type = 'owner_set' AND evidence_role = 'owner_correction'
            AND actor_type = 'owner' AND analysis_run_id IS NULL
            AND extractor_name IS NULL AND extractor_version IS NULL)
        OR (evidence_type != 'owner_set' AND evidence_role = 'observed'
            AND actor_type = 'system' AND analysis_run_id IS NOT NULL
            AND extractor_name IS NOT NULL AND extractor_version IS NOT NULL)
    )
);

CREATE TABLE content_preferred_dates (
    preferred_date_id INTEGER PRIMARY KEY,
    content_identity_id INTEGER NOT NULL UNIQUE
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('resolved', 'needs_review', 'unknown')),
    selection_method TEXT NOT NULL
        CHECK (selection_method IN ('owner_selection', 'policy_selection', 'no_selection')),
    selected_evidence_id INTEGER
        REFERENCES content_date_evidence(date_evidence_id) ON DELETE RESTRICT,
    selected_precision TEXT CHECK (
        selected_precision IN ('year', 'year_month', 'date', 'datetime')
    ),
    selected_time_precision TEXT CHECK (
        selected_time_precision IN ('minute', 'second', 'fraction')
    ),
    selected_year INTEGER,
    selected_month INTEGER,
    selected_day INTEGER,
    selected_hour INTEGER,
    selected_minute INTEGER,
    selected_second INTEGER,
    selected_fraction TEXT,
    selected_timezone_state TEXT CHECK (
        selected_timezone_state IN ('not_applicable', 'unknown', 'known_offset')
    ),
    selected_utc_offset_minutes INTEGER,
    policy_name TEXT CHECK (policy_name IS NULL OR length(trim(policy_name)) > 0),
    policy_version TEXT CHECK (policy_version IS NULL OR length(trim(policy_version)) > 0),
    determined_by_analysis_run_id INTEGER
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('owner', 'system')),
    actor_identifier TEXT NOT NULL CHECK (length(trim(actor_identifier)) > 0),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
    determined_at TEXT NOT NULL,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (status = 'resolved' AND selection_method IN ('owner_selection', 'policy_selection')
            AND selected_evidence_id IS NOT NULL AND selected_precision IS NOT NULL
            AND selected_year IS NOT NULL AND selected_timezone_state IS NOT NULL)
        OR (status IN ('needs_review', 'unknown') AND selection_method = 'no_selection'
            AND selected_evidence_id IS NULL AND selected_precision IS NULL
            AND selected_time_precision IS NULL AND selected_year IS NULL
            AND selected_month IS NULL AND selected_day IS NULL AND selected_hour IS NULL
            AND selected_minute IS NULL AND selected_second IS NULL
            AND selected_fraction IS NULL AND selected_timezone_state IS NULL
            AND selected_utc_offset_minutes IS NULL)
    ),
    CHECK (
        selection_method != 'owner_selection' OR actor_type = 'owner'
    ),
    CHECK (
        selection_method != 'policy_selection' OR (
            actor_type = 'system' AND policy_name IS NOT NULL AND policy_version IS NOT NULL
            AND determined_by_analysis_run_id IS NOT NULL
        )
    )
);

CREATE TABLE preferred_date_basis (
    preferred_date_basis_id INTEGER PRIMARY KEY,
    preferred_date_id INTEGER NOT NULL
        REFERENCES content_preferred_dates(preferred_date_id) ON DELETE RESTRICT,
    date_evidence_id INTEGER NOT NULL
        REFERENCES content_date_evidence(date_evidence_id) ON DELETE RESTRICT,
    basis_role TEXT NOT NULL CHECK (basis_role IN (
        'selected', 'corroborating', 'conflicting', 'timezone_adjacent',
        'ignored_lower_authority'
    )),
    basis_state TEXT NOT NULL DEFAULT 'current'
        CHECK (basis_state IN ('current', 'superseded')),
    linked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    superseded_at TEXT,
    UNIQUE (preferred_date_id, date_evidence_id),
    CHECK (
        (basis_state = 'current' AND superseded_at IS NULL)
        OR (basis_state = 'superseded' AND superseded_at IS NOT NULL)
    )
);

CREATE TABLE date_evidence_jobs (
    job_id TEXT PRIMARY KEY CHECK (length(trim(job_id)) > 0),
    pipeline_version TEXT NOT NULL CHECK (length(trim(pipeline_version)) > 0),
    policy_name TEXT NOT NULL CHECK (length(trim(policy_name)) > 0),
    policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
    config_fingerprint TEXT NOT NULL CHECK (length(trim(config_fingerprint)) > 0),
    config_json TEXT NOT NULL,
    analysis_run_id INTEGER NOT NULL UNIQUE
        REFERENCES analysis_runs(analysis_run_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'interrupted', 'failed')),
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at TEXT
);

CREATE TABLE date_evidence_job_items (
    job_id TEXT NOT NULL REFERENCES date_evidence_jobs(job_id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL CHECK (length(trim(item_key)) > 0),
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    physical_instance_id INTEGER
        REFERENCES physical_instances(physical_instance_id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'recorded', 'reused', 'no_candidate', 'unsupported', 'missing', 'unreadable',
        'changed_during_read', 'invalid_metadata', 'failed'
    )),
    evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
    size_bytes_before INTEGER CHECK (size_bytes_before IS NULL OR size_bytes_before >= 0),
    modified_time_ns_before INTEGER,
    size_bytes_after INTEGER CHECK (size_bytes_after IS NULL OR size_bytes_after >= 0),
    modified_time_ns_after INTEGER,
    error TEXT,
    payload_json TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (job_id, item_key)
);

CREATE TABLE collections (
    collection_id INTEGER PRIMARY KEY,
    collection_uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 200),
    description TEXT CHECK (description IS NULL OR length(description) <= 4000),
    collection_kind TEXT NOT NULL DEFAULT 'manual' CHECK (collection_kind = 'manual'),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    provenance_type TEXT NOT NULL CHECK (provenance_type IN ('owner', 'system', 'ai')),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    archived_at TEXT,
    CHECK (
        (state = 'active' AND archived_at IS NULL)
        OR (state = 'archived' AND archived_at IS NOT NULL)
    )
);

CREATE TABLE collection_memberships (
    collection_membership_id INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(collection_id) ON DELETE RESTRICT,
    content_identity_id INTEGER NOT NULL
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    membership_state TEXT NOT NULL DEFAULT 'active'
        CHECK (membership_state IN ('active', 'removed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_by TEXT NOT NULL CHECK (length(trim(created_by)) BETWEEN 1 AND 200),
    provenance_type TEXT NOT NULL CHECK (provenance_type IN ('owner', 'system', 'ai')),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    ended_at TEXT,
    UNIQUE (collection_id, content_identity_id),
    CHECK (
        (membership_state = 'active' AND ended_at IS NULL)
        OR (membership_state = 'removed' AND ended_at IS NOT NULL)
    )
);

DROP TRIGGER organisation_events_append_only_update;
DROP TRIGGER organisation_events_append_only_delete;
DROP INDEX ix_organisation_events_album;
DROP INDEX ix_organisation_events_content;
DROP INDEX ix_organisation_events_tag;

CREATE TABLE organisation_events_schema10 (
    organisation_event_id INTEGER PRIMARY KEY,
    event_uuid TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'album_created', 'album_renamed', 'album_archived', 'album_restored',
        'album_member_added', 'album_member_removed', 'album_member_restored',
        'tag_created', 'tag_archived', 'tag_restored',
        'tag_member_added', 'tag_member_removed', 'tag_member_restored',
        'collection_created', 'collection_renamed', 'collection_archived',
        'collection_restored', 'collection_member_added', 'collection_member_removed',
        'collection_member_restored', 'preferred_date_resolved',
        'preferred_date_needs_review', 'preferred_date_unknown',
        'preferred_date_owner_set', 'preferred_date_changed'
    )),
    album_id INTEGER REFERENCES albums(album_id) ON DELETE RESTRICT,
    album_membership_id INTEGER
        REFERENCES album_memberships(album_membership_id) ON DELETE RESTRICT,
    tag_id INTEGER REFERENCES tags(tag_id) ON DELETE RESTRICT,
    content_tag_id INTEGER REFERENCES content_tags(content_tag_id) ON DELETE RESTRICT,
    collection_id INTEGER REFERENCES collections(collection_id) ON DELETE RESTRICT,
    collection_membership_id INTEGER
        REFERENCES collection_memberships(collection_membership_id) ON DELETE RESTRICT,
    preferred_date_id INTEGER
        REFERENCES content_preferred_dates(preferred_date_id) ON DELETE RESTRICT,
    content_identity_id INTEGER
        REFERENCES content_identities(content_identity_id) ON DELETE RESTRICT,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('owner', 'system', 'ai')),
    actor_identifier TEXT NOT NULL CHECK (length(trim(actor_identifier)) BETWEEN 1 AND 200),
    provenance TEXT NOT NULL CHECK (length(trim(provenance)) BETWEEN 1 AND 500),
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 2000),
    details_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (event_type IN ('album_created', 'album_renamed', 'album_archived', 'album_restored')
            AND album_id IS NOT NULL AND album_membership_id IS NULL
            AND tag_id IS NULL AND content_tag_id IS NULL AND collection_id IS NULL
            AND collection_membership_id IS NULL AND preferred_date_id IS NULL
            AND content_identity_id IS NULL)
        OR (event_type IN ('album_member_added', 'album_member_removed', 'album_member_restored')
            AND album_id IS NOT NULL AND album_membership_id IS NOT NULL
            AND content_identity_id IS NOT NULL AND tag_id IS NULL AND content_tag_id IS NULL
            AND collection_id IS NULL AND collection_membership_id IS NULL
            AND preferred_date_id IS NULL)
        OR (event_type IN ('tag_created', 'tag_archived', 'tag_restored')
            AND tag_id IS NOT NULL AND content_tag_id IS NULL AND album_id IS NULL
            AND album_membership_id IS NULL AND collection_id IS NULL
            AND collection_membership_id IS NULL AND preferred_date_id IS NULL
            AND content_identity_id IS NULL)
        OR (event_type IN ('tag_member_added', 'tag_member_removed', 'tag_member_restored')
            AND tag_id IS NOT NULL AND content_tag_id IS NOT NULL
            AND content_identity_id IS NOT NULL AND album_id IS NULL
            AND album_membership_id IS NULL AND collection_id IS NULL
            AND collection_membership_id IS NULL AND preferred_date_id IS NULL)
        OR (event_type IN ('collection_created', 'collection_renamed',
                'collection_archived', 'collection_restored')
            AND collection_id IS NOT NULL AND collection_membership_id IS NULL
            AND album_id IS NULL AND album_membership_id IS NULL AND tag_id IS NULL
            AND content_tag_id IS NULL AND preferred_date_id IS NULL
            AND content_identity_id IS NULL)
        OR (event_type IN ('collection_member_added', 'collection_member_removed',
                'collection_member_restored')
            AND collection_id IS NOT NULL AND collection_membership_id IS NOT NULL
            AND content_identity_id IS NOT NULL AND album_id IS NULL
            AND album_membership_id IS NULL AND tag_id IS NULL AND content_tag_id IS NULL
            AND preferred_date_id IS NULL)
        OR (event_type IN ('preferred_date_resolved', 'preferred_date_needs_review',
                'preferred_date_unknown', 'preferred_date_owner_set', 'preferred_date_changed')
            AND preferred_date_id IS NOT NULL AND content_identity_id IS NOT NULL
            AND album_id IS NULL AND album_membership_id IS NULL AND tag_id IS NULL
            AND content_tag_id IS NULL AND collection_id IS NULL
            AND collection_membership_id IS NULL)
    )
);

INSERT INTO organisation_events_schema10(
    organisation_event_id, event_uuid, event_type, album_id, album_membership_id,
    tag_id, content_tag_id, content_identity_id, actor_type, actor_identifier,
    provenance, reason, details_json, recorded_at
)
SELECT organisation_event_id, event_uuid, event_type, album_id, album_membership_id,
       tag_id, content_tag_id, content_identity_id, actor_type, actor_identifier,
       provenance, reason, details_json, recorded_at
FROM organisation_events;
DROP TABLE organisation_events;
ALTER TABLE organisation_events_schema10 RENAME TO organisation_events;

CREATE INDEX ix_content_date_evidence_content_type
    ON content_date_evidence(content_identity_id, evidence_type);
CREATE INDEX ix_content_date_evidence_year_precision_content
    ON content_date_evidence(date_year, precision, content_identity_id);
CREATE INDEX ix_content_date_evidence_physical
    ON content_date_evidence(physical_instance_id);
CREATE INDEX ix_content_date_evidence_source_type
    ON content_date_evidence(source_id, evidence_type);
CREATE INDEX ix_content_date_evidence_analysis_run
    ON content_date_evidence(analysis_run_id);
CREATE INDEX ix_content_preferred_dates_status_year_content
    ON content_preferred_dates(status, selected_year, content_identity_id);
CREATE INDEX ix_content_preferred_dates_selected_evidence
    ON content_preferred_dates(selected_evidence_id);
CREATE INDEX ix_preferred_date_basis_preferred_current_role
    ON preferred_date_basis(preferred_date_id, basis_state, basis_role);
CREATE INDEX ix_preferred_date_basis_evidence_current
    ON preferred_date_basis(date_evidence_id, basis_state);
CREATE INDEX ix_date_evidence_job_items_outcome
    ON date_evidence_job_items(job_id, outcome);
CREATE INDEX ix_collections_state_name ON collections(state, name, collection_id);
CREATE INDEX ix_collection_memberships_collection_state_content
    ON collection_memberships(collection_id, membership_state, content_identity_id);
CREATE INDEX ix_collection_memberships_content_state_collection
    ON collection_memberships(content_identity_id, membership_state, collection_id);
CREATE INDEX ix_organisation_events_album
    ON organisation_events(album_id, organisation_event_id);
CREATE INDEX ix_organisation_events_content
    ON organisation_events(content_identity_id, organisation_event_id);
CREATE INDEX ix_organisation_events_tag
    ON organisation_events(tag_id, organisation_event_id);
CREATE INDEX ix_organisation_events_collection
    ON organisation_events(collection_id, organisation_event_id);
CREATE INDEX ix_organisation_events_collection_membership
    ON organisation_events(collection_membership_id, organisation_event_id);
CREATE INDEX ix_organisation_events_preferred_date
    ON organisation_events(preferred_date_id, organisation_event_id);

CREATE TRIGGER content_date_evidence_relationship_insert
BEFORE INSERT ON content_date_evidence
WHEN NEW.physical_instance_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM physical_instances pi
    WHERE pi.physical_instance_id = NEW.physical_instance_id
      AND pi.content_identity_id = NEW.content_identity_id
      AND (NEW.source_id IS NULL OR pi.source_id = NEW.source_id)
)
BEGIN
    SELECT RAISE(ABORT, 'date evidence physical/content/source mismatch');
END;
CREATE TRIGGER content_date_evidence_append_only_update
BEFORE UPDATE ON content_date_evidence BEGIN
    SELECT RAISE(ABORT, 'content date evidence is append-only');
END;
CREATE TRIGGER content_date_evidence_append_only_delete
BEFORE DELETE ON content_date_evidence BEGIN
    SELECT RAISE(ABORT, 'content date evidence is append-only');
END;

CREATE TRIGGER content_preferred_dates_validate_insert
BEFORE INSERT ON content_preferred_dates
WHEN NEW.selected_evidence_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM content_date_evidence e
    WHERE e.date_evidence_id = NEW.selected_evidence_id
      AND e.content_identity_id = NEW.content_identity_id
      AND e.precision IS NEW.selected_precision
      AND e.time_precision IS NEW.selected_time_precision
      AND e.date_year IS NEW.selected_year AND e.date_month IS NEW.selected_month
      AND e.date_day IS NEW.selected_day AND e.time_hour IS NEW.selected_hour
      AND e.time_minute IS NEW.selected_minute AND e.time_second IS NEW.selected_second
      AND e.time_fraction IS NEW.selected_fraction
      AND e.timezone_state IS NEW.selected_timezone_state
      AND e.utc_offset_minutes IS NEW.selected_utc_offset_minutes
      AND (NEW.selection_method != 'owner_selection' OR e.evidence_type = 'owner_set')
)
BEGIN
    SELECT RAISE(ABORT, 'preferred date must exactly project evidence for the same content');
END;
CREATE TRIGGER content_preferred_dates_validate_update
BEFORE UPDATE ON content_preferred_dates
WHEN NEW.selected_evidence_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM content_date_evidence e
    WHERE e.date_evidence_id = NEW.selected_evidence_id
      AND e.content_identity_id = NEW.content_identity_id
      AND e.precision IS NEW.selected_precision
      AND e.time_precision IS NEW.selected_time_precision
      AND e.date_year IS NEW.selected_year AND e.date_month IS NEW.selected_month
      AND e.date_day IS NEW.selected_day AND e.time_hour IS NEW.selected_hour
      AND e.time_minute IS NEW.selected_minute AND e.time_second IS NEW.selected_second
      AND e.time_fraction IS NEW.selected_fraction
      AND e.timezone_state IS NEW.selected_timezone_state
      AND e.utc_offset_minutes IS NEW.selected_utc_offset_minutes
      AND (NEW.selection_method != 'owner_selection' OR e.evidence_type = 'owner_set')
)
BEGIN
    SELECT RAISE(ABORT, 'preferred date must exactly project evidence for the same content');
END;
CREATE TRIGGER content_preferred_dates_snapshot_immutable
BEFORE UPDATE ON content_preferred_dates
WHEN OLD.content_identity_id IS NOT NEW.content_identity_id
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    SELECT RAISE(ABORT, 'preferred date identity and creation timestamp are immutable');
END;
CREATE TRIGGER content_preferred_dates_no_delete
BEFORE DELETE ON content_preferred_dates BEGIN
    SELECT RAISE(ABORT, 'preferred dates cannot be deleted');
END;

CREATE TRIGGER preferred_date_basis_content_insert
BEFORE INSERT ON preferred_date_basis
WHEN NOT EXISTS (
    SELECT 1 FROM content_preferred_dates p JOIN content_date_evidence e
      ON e.content_identity_id = p.content_identity_id
    WHERE p.preferred_date_id = NEW.preferred_date_id
      AND e.date_evidence_id = NEW.date_evidence_id
)
BEGIN
    SELECT RAISE(ABORT, 'preferred date basis evidence belongs to different content');
END;
CREATE TRIGGER preferred_date_basis_content_update
BEFORE UPDATE ON preferred_date_basis
WHEN NOT EXISTS (
    SELECT 1 FROM content_preferred_dates p JOIN content_date_evidence e
      ON e.content_identity_id = p.content_identity_id
    WHERE p.preferred_date_id = NEW.preferred_date_id
      AND e.date_evidence_id = NEW.date_evidence_id
)
BEGIN
    SELECT RAISE(ABORT, 'preferred date basis evidence belongs to different content');
END;

CREATE TRIGGER date_evidence_job_items_relationship_insert
BEFORE INSERT ON date_evidence_job_items
WHEN NEW.physical_instance_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM physical_instances pi
    WHERE pi.physical_instance_id = NEW.physical_instance_id
      AND pi.content_identity_id = NEW.content_identity_id
)
BEGIN
    SELECT RAISE(ABORT, 'date evidence job item physical/content mismatch');
END;
CREATE TRIGGER date_evidence_job_items_relationship_update
BEFORE UPDATE ON date_evidence_job_items
WHEN NEW.physical_instance_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM physical_instances pi
    WHERE pi.physical_instance_id = NEW.physical_instance_id
      AND pi.content_identity_id = NEW.content_identity_id
)
BEGIN
    SELECT RAISE(ABORT, 'date evidence job item physical/content mismatch');
END;

CREATE TRIGGER collections_no_delete
BEFORE DELETE ON collections BEGIN
    SELECT RAISE(ABORT, 'collections cannot be deleted');
END;
CREATE TRIGGER collections_snapshot_immutable
BEFORE UPDATE ON collections
WHEN OLD.collection_uuid IS NOT NEW.collection_uuid
  OR OLD.collection_kind IS NOT NEW.collection_kind
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.provenance_type IS NOT NEW.provenance_type
  OR OLD.provenance IS NOT NEW.provenance
BEGIN
    SELECT RAISE(ABORT, 'collection identity and creation provenance are immutable');
END;
CREATE TRIGGER collection_memberships_no_delete
BEFORE DELETE ON collection_memberships BEGIN
    SELECT RAISE(ABORT, 'collection memberships cannot be deleted');
END;
CREATE TRIGGER collection_memberships_snapshot_immutable
BEFORE UPDATE ON collection_memberships
WHEN OLD.collection_id IS NOT NEW.collection_id
  OR OLD.content_identity_id IS NOT NEW.content_identity_id
  OR OLD.created_at IS NOT NEW.created_at
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.provenance_type IS NOT NEW.provenance_type
  OR OLD.provenance IS NOT NEW.provenance
BEGIN
    SELECT RAISE(ABORT, 'collection membership identity and creation provenance are immutable');
END;
CREATE TRIGGER organisation_events_append_only_update
BEFORE UPDATE ON organisation_events BEGIN
    SELECT RAISE(ABORT, 'organisation events are append-only');
END;
CREATE TRIGGER organisation_events_append_only_delete
BEFORE DELETE ON organisation_events BEGIN
    SELECT RAISE(ABORT, 'organisation events are append-only');
END;
""",
    ),
)

_DECLARED_VERSIONS = tuple(migration.version for migration in MIGRATIONS)
if _DECLARED_VERSIONS != tuple(range(1, len(MIGRATIONS) + 1)):
    raise RuntimeError("Catalogue migrations must be declared once in contiguous version order.")
if len({migration.name for migration in MIGRATIONS}) != len(MIGRATIONS):
    raise RuntimeError("Catalogue migration names must be unique.")

CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply every pending migration in order and return the current version."""

    applied = _read_and_validate_history(connection, allow_uninitialised=True)
    current_version = applied[-1][0] if applied else 0

    for migration in MIGRATIONS:
        if migration.version <= current_version:
            continue
        escaped_name = migration.name.replace("'", "''")
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n"
            "INSERT INTO schema_migrations(version, name) "
            f"VALUES ({migration.version}, '{escaped_name}');\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise MigrationError(
                f"Migration {migration.version} ({migration.name}) failed: {exc}"
            ) from exc

    applied = _read_and_validate_history(connection, allow_uninitialised=False)
    return applied[-1][0]


def read_schema_version(connection: sqlite3.Connection) -> int:
    """Return and validate the recorded schema version without applying migrations."""

    applied = _read_and_validate_history(connection, allow_uninitialised=False)
    return applied[-1][0]


def _read_and_validate_history(
    connection: sqlite3.Connection,
    *,
    allow_uninitialised: bool,
) -> tuple[tuple[int, str], ...]:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if "schema_migrations" not in tables:
        if tables:
            raise CatalogueNotInitialisedError(
                "Database contains tables but is not a recognised Personal Librarian catalogue."
            )
        if allow_uninitialised:
            return ()
        raise CatalogueNotInitialisedError("Database is not an initialised Personal Librarian catalogue.")

    rows = tuple(
        (int(row[0]), str(row[1]))
        for row in connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
    )
    if not rows:
        raise SchemaVersionError("Migration history is empty.")

    latest = rows[-1][0]
    if latest > CURRENT_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Catalogue schema version {latest} is newer than supported version "
            f"{CURRENT_SCHEMA_VERSION}."
        )

    expected_versions = tuple(range(1, latest + 1))
    actual_versions = tuple(version for version, _ in rows)
    if actual_versions != expected_versions:
        raise SchemaVersionError("Migration history is not a contiguous sequence from version 1.")

    known = {migration.version: migration.name for migration in MIGRATIONS}
    for version, name in rows:
        if known.get(version) != name:
            raise SchemaVersionError(
                f"Migration {version} has unexpected name '{name}'."
            )
    return rows
