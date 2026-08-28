# Engineering documentation

This directory records the architecture, evidence, decisions, validation, and safety reasoning developed across Personal Librarian milestones. It is engineering history, not a substitute for current user documentation.

[PROJECT_TRUTH.md](../PROJECT_TRUTH.md) remains the authoritative project definition. The root [README](../README.md) is the public introduction, and the frozen reconstructed starting point is retained in [PROJECT_TRUTH.v0.2.BASELINE.RECONSTRUCTED.md](../PROJECT_TRUTH.v0.2.BASELINE.RECONSTRUCTED.md).

## Project foundations

- [Application foundation and safety boundaries](M13_APPLICATION_FOUNDATION.md)
- [Canonical organisation policy](M12_ORGANISATION_CANONICAL_POLICY.md)
- [SQLite catalogue foundation](M14_SQLITE_CATALOGUE.md)

## Acquisition and inventory

The M2–M9 records cover source classification, backup behaviour, guarded staging, acquisition evidence, and the first global media inventory. These documents preserve historical context; they are not general-purpose instructions for importing a new library.

- [Source ledger](M2_SOURCE_LEDGER.md)
- [Backup behaviour audit](M3_BACKUP_BEHAVIOUR_AUDIT.md)
- [Global media inventory](M9_GLOBAL_MEDIA_INVENTORY.md)

## Catalogue and duplicate analysis

The M10–M16 records cover exact hashing, perceptual similarity, catalogue ingestion, and reproducible analysis pipelines.

- [SHA-256 exact duplicates](M10_SHA256_EXACT_DUPLICATES.md)
- [Near-duplicate analysis](M11_NEAR_DUPLICATE_ANALYSIS.md)
- [Reproducible inventory and hash pipeline](M15_REPRODUCIBLE_INVENTORY_HASH_PIPELINE.md)
- [Reproducible near-duplicate pipeline](M16_REPRODUCIBLE_NEAR_DUPLICATE_ANALYSIS.md)

## Decisions and safety workflows

The M17–M19 records define review decisions, dry-run action planning, preflight, constrained quarantine, and restoration.

- [Review and canonical decisions](M17_REVIEW_CANONICAL_DECISIONS.md)
- [Safe action planning and dry run](M18_SAFE_ACTION_PLANNING_DRY_RUN.md)
- [Reversible quarantine execution](M19_REVERSIBLE_QUARANTINE_EXECUTION.md)

## Backup and recovery

The M20–M22 records cover production-catalogue identity, safe SQLite backup, recovery staging, health checks, and independent local disaster-recovery readiness.

- [Catalogue backup and recovery](M20_PRODUCTION_CATALOGUE_BACKUP_RECOVERY.md)
- [Operational readiness](M21_PRODUCTION_DEPLOYMENT_OPERATIONAL_READINESS.md)
- [Independent backup and DR readiness](M22_INDEPENDENT_BACKUP_DR_READINESS.md)
- [Repository recovery record](RECOVERY_2026-08-17.md)

## Desktop and release work

The M23–M26 records cover the PySide6 desktop, usability, Windows packaging, release-candidate validation, and interface refinement.

- [Desktop review interface](M23_DESKTOP_REVIEW_INTERFACE_FOUNDATION.md)
- [Windows packaging](M24_DESKTOP_USABILITY_WINDOWS_PACKAGING.md)
- [Release candidate](M25_RELEASE_CANDIDATE.md)
- [Desktop UX refinement](M26_DESKTOP_UX_REFINEMENT.md)

## Organisation and preferred dates

The M27–M30 records cover organisation policy, schema-10 foundations, Albums, Year/Unknown browsing, preferred-date evidence, and cross-year Collections.

- [Organisation and AI policy](M27_LIBRARY_ORGANISATION_ALBUMS_AI_POLICY.md)
- [Albums and schema foundation](M28_CATALOGUE_ORGANISATION_SCHEMA_MANUAL_ALBUMS.md)
- [Year-centred desktop organisation](M29_YEAR_CENTRED_DESKTOP_ORGANISATION.md)
- [Preferred dates and Collections](M30_PREFERRED_DATE_COLLECTIONS.md)

Historical reports may describe one-time validation conditions. Before changing current behaviour, follow [PROJECT_TRUTH.md](../PROJECT_TRUTH.md) and verify the present source and tests.
