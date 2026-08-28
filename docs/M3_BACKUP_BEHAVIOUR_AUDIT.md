# M3 Backup Behaviour Audit

> Recovery reconstruction created 17 August 2026 after failure of the former Z: working drive.
> This document reconstructs the known M3 findings and safety decisions from previously verified project records.

## Purpose

M3 established how the existing cloud and synchronisation systems behave before Personal Librarian begins changing where files live.

The objective was to avoid confusing synchronisation with backup and to prevent accidental loss during migration.

## Core principle

A file appearing in a synchronised folder is not automatically a verified independent backup.

Personal Librarian therefore follows:

Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act

No destructive action is permitted merely because another copy appears to exist.

## OneDrive

Local OneDrive root observed:

`C:\Users\<user>\OneDrive`

Active processes observed during audit:

- OneDrive.exe
- OneDrive.Sync.Service.exe

OneDrive Files On-Demand is in use.

This means entries visible in Explorer can be:

- fully local
- provider-managed
- cloud-only placeholders

A visible filename is therefore not proof that the file contents are physically present on the local disk.

## OneDrive phone backup behaviour

OneDrive Camera Upload is enabled on the current phone.

Videos are included.

Observed selected upload folders include:

- Camera
- Tapo
- Screen recordings
- Screenshots

This OneDrive feed remains an active acquisition source until a replacement workflow has been proven.

## Google Photos

Google Photos Backup is enabled on the current phone.

Google Photos is treated as another independent acquisition/safety source.

It is not yet considered the canonical Personal Library.

Google Photos backup must remain enabled until M6 acquisition and later replacement behaviour are verified.

## Dropbox

Dropbox root observed:

`C:\Users\<user>\Dropbox`

Dropbox is treated as a separate source population.

Files found there must be inventoried and verified before any cleanup or deduplication.

## Synchronisation is not archival backup

Cloud-sync systems can propagate:

- deletions
- renames
- corruption
- accidental edits

For that reason Personal Librarian must maintain a preserved acquisition layer separate from live synchronised folders.

## Files On-Demand safety

Cloud-only OneDrive files must not be counted as locally preserved simply because they have directory entries on C:.

M5 therefore distinguishes storage state before acquisition.

The known OneDrive states included attributes associated with:

- ReparsePoint
- Offline
- RecallOnOpen
- RecallOnDataAccess
- Pinned
- Unpinned

The exact Windows attribute combination is less important than the safety rule: verify file content, not filename presence.

## Source-of-truth rule

During acquisition, the existing source remains authoritative.

For cloud-backed data:

- cloud copy remains untouched
- acquisition is copy-only
- local staging is not canonical until verified

For local historical sources:

- original source remains untouched
- files are copied into source-separated staging
- no deduplication deletion occurs during acquisition

## Zero-byte files

Zero-byte entries discovered during source inventory are preserved.

They may represent:

- legitimate empty files
- historic application artefacts
- damaged files
- cloud/provider state

They are not deleted automatically.

Their meaning is deferred to later analysis.

## Personal Librarian backup philosophy

The intended model is eventually:

1. Authoritative local library
2. Independent backup copy
3. Off-site or cloud protection

No single synchronisation provider should be treated as the only source of truth.

## Temporary cloud behaviour

During the acquisition milestones:

- Google Photos remains enabled.
- OneDrive Camera Upload remains enabled.
- Existing OneDrive and Dropbox data remain untouched.
- No existing sync service is disabled merely to simplify migration.

This preserves safety while the replacement library is being built.

## M3 completion state

M3 completed the backup-behaviour audit and established the operational safety rules required for local staging.

The project then proceeded to M4 Safe Local Staging.

## Recovery note

The original M3_BACKUP_BEHAVIOUR_AUDIT.md Git blob was lost when the former Z: device became unreadable.
This reconstruction preserves the known findings and decisions but does not claim byte-for-byte identity with the lost original.
