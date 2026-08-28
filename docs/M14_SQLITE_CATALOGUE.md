# M14 - SQLite Catalogue and Evidence Import

Date: 21 August 2026

Status: M14B evidence import implemented and reconciled for review; M14 is not complete

## Purpose

M14A adds the persistent SQLite catalogue foundation. M14B adds controlled import of the existing verified M9, M10 and M11 CSV evidence. Neither scans, hashes or changes media.

The catalogue uses Python's standard-library `sqlite3` module. No ORM or new runtime dependency was added.

## Schema version

M14 closed with schema version **2**. M15 subsequently adds migration 3 for reproducible pipeline checkpoints and state-qualified hash observations. M16 adds migration 4 for perceptual-analysis checkpoints and chosen-physical-instance provenance. M17 adds migration 5 for explicit review-context and workflow-action provenance on append-only decision events. Migration 1 is `initial_catalogue`; migration 2 is `evidence_import_foundation`.

`schema_migrations` records every applied migration by ordered integer version, source-controlled name and UTC application timestamp. Migration history must be contiguous and match the known name for every version. A newer or inconsistent history fails safely.

Migrations execute inside explicit SQLite transactions. Reopening and initialising an up-to-date catalogue is idempotent. A database containing unrelated tables is not adopted or modified as a Personal Librarian catalogue.

## Entity overview

- `sources` - stable source keys such as OneDrive, GooglePhotos, Dropbox and HDD_Disk2.
- `acquisition_batches` - source-specific import/acquisition batches and verification state.
- `analysis_runs` - provenance for inventory, hashing, perceptual analysis and later imports, including algorithms, versions and parameters.
- `content_identities` - identities for byte-identical content, independent of physical paths.
- `physical_instances` - particular observed files with source, batch, raw path, current observed path, size, extension and observed timestamps.
- `hash_observations` - per-instance, per-run hash evidence for SHA-256 and future algorithms.
- `content_identity_hashes` - explicit assertions linking digest evidence to a content identity without placing SHA-256 directly on the identity row.
- `similarity_relationships` - pHash/dHash distances and review tiers between two distinct content identities, with analysis-run provenance.
- `decision_events` - append-only future human decision history supporting archival and display/export canonical scopes.
- `evidence_import_stages` - importer/version, input fingerprints and successful reconciliation records.
- `inventory_observations` and `instance_path_observations` - separate M9 raw inventory evidence and M10 authoritative repaired path evidence.
- `exact_duplicate_groups` and `exact_duplicate_memberships` - M10 duplicate-report provenance without collapsing instances.
- `content_hash_observations` - M11 pHash/dHash evidence attached to content identities.
- `similarity_groups`, memberships and relationship junctions - M11 review-group provenance.

Stable external keys (`source_key`, `batch_key`, `run_key`, `identity_key`, `instance_key`, relationship keys and decision keys) provide future evidence importers with deterministic idempotency boundaries. Internal integer identifiers provide compact foreign keys.

## Evidence importer architecture and stable keys

`catalogue/importers` contains one importer per evidence milestone plus shared CSV validation, fingerprinting, transaction and reconciliation support. M9, M10 and M11 are separate `BEGIN IMMEDIATE` transactions. A stage is recorded only after its counts match the approved baseline; malformed data or a mismatch rolls the complete stage back. A rerun with the same importer version and CSV fingerprints returns the stored report without inserting rows. A changed fingerprint fails instead of silently mixing evidence.

Keys are deterministic and namespaced:

- sources use fixed keys for the four verified sources;
- acquisition batches combine milestone and stable source key;
- analysis runs use milestone-specific verified-run keys;
- M9 observations and M10 physical instances include the exact source label and exact raw path text;
- content identities use the lower-case SHA-256 digest;
- M11 relationships use the ordered pair of SHA-256 digests; and
- evidence groups retain their external SHA-256 or M11 `GroupID` provenance.

Length-prefixed UTF-8 components are SHA-256-derived where a compact compound key is needed. Physical identity is never keyed solely from a normalized comparison path.

## Identity boundaries

One content identity may be referenced by many physical instances. Hash observations are evidence gathered during a particular run. An explicit content-identity hash assertion is separate from both the raw observation and the physical-instance relationship.

Similarity always joins two different, ordered content identities and requires at least one perceptual distance. It never creates or merges a content identity.

## Path and Unicode strategy

`physical_instances.raw_relative_path` preserves the original imported text. It is never overwritten by display or comparison values.

Optional, separate fields retain:

- display path;
- current observed/staging path;
- derived relative-path comparison key; and
- comparison-key algorithm version.

The provided `windows-lexical-v1` helper normalises separators and lexical `.`/`..` components, applies Unicode NFC and case-folds text. The result is a non-authoritative lookup aid. It is deliberately not unique: raw paths with different byte or Unicode representations may coexist even when their comparison keys match. A comparison-key match must never imply that files or paths are identical.

M9 raw paths remain immutable observations, including historical mojibake. M10 repaired paths are the authoritative current/import representation. M10 links an M9 observation only by exact raw source/path or by a metadata tuple that is unique on both sides; ambiguous observations remain unlinked. Supersession never deletes or rewrites the M9 text, and Unicode normalization never establishes file identity.

Source modification timestamps are retained exactly as supplied. An additional state records `aware`, `naive` or `missing`; a timezone is never inferred. Capture-date precedence remains outside M14B.

## Decision-history foundation

Decision events support `archival` and `display_export` scopes. An event targets exactly one content identity or one physical instance. Approval events are constrained to an owner actor with explicit `owner_approved = 1`.

Update and delete triggers make decision events append-only. Withdrawal and supersession are new events linked to earlier events; history is not overwritten. M14A exposes no nomination or approval command.

## Referential integrity

Every application catalogue connection enables and verifies `PRAGMA foreign_keys = ON`. Foreign keys use restrictive deletion behavior, and a physical instance cannot reference an acquisition batch owned by another source. The schema includes uniqueness constraints for stable import keys and only the indexes needed for source/path, content, digest, similarity and decision lookups.

## Catalogue commands

```powershell
personal-librarian catalogue init --database 'C:\explicit\catalogue.sqlite3'
personal-librarian catalogue status --database 'C:\explicit\catalogue.sqlite3'
personal-librarian catalogue import-evidence `
  --database 'C:\explicit\temporary.sqlite3' `
  --m9 'H:\explicit\global_media_inventory.csv' `
  --m10-manifest 'H:\explicit\m10_hash_manifest.csv' `
  --m10-groups 'H:\explicit\exact_duplicate_groups.csv' `
  --m10-rows 'H:\explicit\exact_duplicate_rows.csv' `
  --m11-dualhash 'H:\explicit\m11_unique_content_dualhash.csv' `
  --m11-pairs 'H:\explicit\m11_dualhash_review.csv' `
  --m11-groups 'H:\explicit\m11_dualhash_groups.csv' `
  --m11-summary 'H:\explicit\m11_dualhash_group_summary.csv'
```

The database path is mandatory and must be an explicit absolute Windows drive or UNC path. `init` is the only M14A control-plane write: it may create or migrate that database only. Structured logs label it `catalogue_access=create-or-migrate`, separately from the still-restricted media-operation mode. `status` opens SQLite in read-only mode and cannot create or migrate a database.

All commands and importer inputs call the M13 central path-safety policy. Z: paths are rejected from string evidence alone and are never probed. Import is an explicitly requested catalogue control-plane write; it does not open paths found inside CSV rows.

## M14B reconciliation result

The controlled 21 August 2026 import into a temporary system-directory database matched every approved baseline:

- M9: 69,444 rows; 122,312,861,984 bytes; OneDrive 23,538; GooglePhotos 4,287; Dropbox 837; HDD_Disk2 40,782.
- M10: 69,444 manifest rows and valid SHA-256 values; 56,127 distinct contents; 69,444 physical instances; 7,707 exact groups; 21,024 memberships; 13,317 redundant copies; 25,488,473,284 reclaimable bytes. M9 linkage yielded 32,461 exact-path, 32,901 unique-metadata and 4,082 deliberately unlinked observations.
- M11: 54,839 unique dual-hash contents representing 64,569 physical copies; complete dHash coverage; 9,403 review relationships; 5,067 groups containing 11,325 distinct contents; largest group 135; 12 groups over 20 and one over 50.

All M11 relationships remain review evidence between distinct content identities. Groups over 20 contents receive a `large_ambiguous_review_only` tier; no group or pair nominates a canonical copy.

## Safety boundaries

M14B:

- creates no implicit or production database;
- uses temporary databases for tests and validation;
- reads only explicitly supplied verified evidence CSVs and does not access Z:;
- does not open or scan paths contained in evidence rows;
- does not expose action mode;
- does not rank, nominate or approve canonical copies; and
- does not move, rename, quarantine or delete files.

## Validation

Run the complete suite:

```powershell
python -m unittest discover -s tests -v
```

Catalogue and importer tests cover schema creation, migrations, foreign keys, path safety, raw Unicode preservation, all three synthetic import stages, exact-copy identity, near-duplicate separation, timestamp states, idempotency, reconciliation failure, malformed-input rollback and CLI path requirements.

## Current limitations and close-out boundary

- The validated database is temporary; no permanent production catalogue location has been selected.
- M9-to-M10 matching intentionally leaves 4,082 ambiguous M9 observations unlinked rather than guessing.
- CSV validation/reconciliation mode is implemented through transactional import and rollback; there is no separate dry-run flag.
- The comparison key is a review/search aid, not a filesystem identity mechanism.
- Decision state is derived from append-only events; M14A does not implement the derivation or owner workflow.
- Catalogue backup, integrity-check scheduling and production location policy remain to be defined before production use.

## M18 schema extension

Migration 6 adds immutable action-plan snapshots plus append-only items, preflight results, and plan events. The only mutable plan fields are lifecycle-status conveniences and explicit invalidation metadata; historical evidence cannot be updated or deleted. The schema contains no delete action type and no reachable executed status. See `docs/M18_SAFE_ACTION_PLANNING_DRY_RUN.md` for the planner and safety contract.

## M19 schema extension

Migration 7 adds narrowly scoped quarantine executions, append-only execution events, quarantine/restore records, and append-only physical-instance location events. Execution snapshot fields and all history are protected from destructive change. Exact content identity remains unchanged while `current_observed_path` acts only as the latest verified-location projection. See `docs/M19_REVERSIBLE_QUARANTINE_EXECUTION.md`.

## M20 schema extension

Migration 8 adds immutable catalogue UUID/bootstrap identity and an explicit production/non-production role. Production bootstrap, backup, health, and recovery behavior is documented in `docs/M20_PRODUCTION_CATALOGUE_BACKUP_RECOVERY.md`.
