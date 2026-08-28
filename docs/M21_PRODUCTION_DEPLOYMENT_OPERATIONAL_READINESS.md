# M21 - Production Deployment and Operational Readiness

Date: 23 August 2026

Status: production deployment and operational-readiness validation complete; pending owner close-out

## Scope and safety boundary

M21 deployed the first genuine Personal Librarian production catalogue into the owner-approved application-data root:

`<data-root>`

Only the frozen M9/M10/M11 CSV evidence was read. No media was scanned or re-hashed, no perceptual hashes were regenerated, and no canonical decision, action plan, quarantine, execution, copy, move, rename, overwrite, or deletion capability was exercised or broadened.

## Pre-deployment verification

Before bootstrap, the approved root:

- existed as the owner-approved absolute `<data-root>`;
- was an ordinary empty directory, not a link/reparse target;
- passed the central path-safety policy;
- contained no catalogue or unexpected Personal Librarian structure; and
- was on the H: NTFS volume, which reported `Healthy` / `OK` with 425,354,457,088 bytes free.

All eight approved M9/M10/M11 evidence files existed. No alternative production root was created.

## Production layout

Bootstrap created only the M20 layout under the approved root:

```text
<data-root>\
    catalogue\
        personal_librarian.sqlite3
    backups\
        catalogue\
    logs\
    exports\
    state\
        recovery\
```

The logs, exports, and recovery directories remain empty unless legitimate operations need them.

The deployment audit exposed that the original M20 verification path opened WAL-mode staging and backup snapshots through SQLite's ordinary read-only mode. This left zero-byte WAL and 32,768-byte SHM runtime sidecars under old bootstrap/incomplete/backup names. The M21 fix now verifies completed snapshots with SQLite immutable read-only mode and removes only newly generated, empty bootstrap staging sidecars before promotion; regression tests cover the absence of these artefacts. The ten sidecars already generated during the real deployment were retained because M21 explicitly forbids deletion. They are not accepted backups, are ignored by backup listing/retention, and do not affect catalogue or manifest verification. Exact owner-authorised cleanup remains a follow-up housekeeping action. The live production database's own WAL/SHM files are normal SQLite runtime state, not stale deployment artefacts.

## Production catalogue identity

- Catalogue path: `<data-root>\catalogue\personal_librarian.sqlite3`
- Catalogue UUID: `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Role: `production`
- Schema version: 8
- Application version at bootstrap: 0.1.0
- Created: `2026-08-23T01:14:18.707980Z`
- Marked production: `2026-08-23T01:15:01.658859Z`
- Application-data-root fingerprint: `5dcf153de19057792e44244f33903c89dc1f2773c2876887a8a9e6ab6ea42926`
- Catalogue size: 271,785,984 bytes
- Bootstrap duration: 46.637 seconds

Normal reopen retains this UUID and identity; the database filename alone does not establish production status.

## Baseline reconciliation

All importer reconciliation was `MATCH`.

M9:

- 69,444 inventory rows;
- 122,312,861,984 bytes;
- OneDrive 23,538;
- GooglePhotos 4,287;
- Dropbox 837; and
- HDD_Disk2 40,782.

M10:

- 69,444 valid SHA-256 observations;
- 56,127 content identities;
- 7,707 exact groups;
- 21,024 memberships;
- 13,317 redundant copies; and
- 25,488,473,284 informational reclaimable bytes.

M11:

- 54,839 analysed identities;
- 64,569 represented physical copies;
- 9,403 similarity relationships;
- 5,067 similarity groups;
- 11,325 grouped contents;
- largest group 135;
- groups over 20: 12; and
- groups over 50: 1.

## Production health

Health before the first backup correctly returned `WARN` solely because no accepted backup existed. After the two initial snapshots it returned `PASS`:

- role `production`;
- schema 8/current;
- journal mode `wal`;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: zero rows;
- accepted backup count: 2;
- unresolved `recovery_required` executions: 0;
- decision events: 0;
- action plans: 0; and
- action executions/events: 0.

M21 adds a conservative health warning when the latest accepted backup is older than seven days (604,800 seconds). This is an operational warning, not automatic backup scheduling or retention deletion.

## Initial production backups

Both backups use manifest version 1, schema 8, source UUID `613affe5-a00b-49bc-9ad9-99b95adeec33`, and independently passed SHA-256, identity, integrity, and foreign-key verification.

### Snapshot 1

- Backup ID: `acd9709c-8308-4c64-843a-27c2f77b2cdb`
- Database: `catalogue-20260823T011527401756Z-acd9709c-8308-4c64-843a-27c2f77b2cdb.sqlite3`
- Size: 271,785,984 bytes
- SHA-256: `f3572f8bd42611781a1360168bd44508a63b3134e4790ec0a8e394f5ef474b78`
- Snapshot duration: 8.454 seconds
- SHA-256 duration: 0.204 seconds
- Verification: `ACCEPTED`; integrity `ok`; zero foreign-key violations

### Snapshot 2

- Backup ID: `db3c3902-dee3-412b-9b88-ddfd2aa042e2`
- Database: `catalogue-20260823T011537225832Z-db3c3902-dee3-412b-9b88-ddfd2aa042e2.sqlite3`
- Size: 271,785,984 bytes
- SHA-256: `f3572f8bd42611781a1360168bd44508a63b3134e4790ec0a8e394f5ef474b78`
- Snapshot duration: 8.394 seconds
- SHA-256 duration: 0.206 seconds
- Verification: `ACCEPTED`; integrity `ok`; zero foreign-key violations

Identical digests are expected because the production catalogue did not change between snapshots. Names, IDs, database files, and manifests remain distinct; nothing was overwritten.

## Local-backup limitation

`<data-root>\backups\catalogue` and the production catalogue were on the same physical device. These snapshots are useful operational/recovery copies, but they are not an independent hardware backup, NAS backup, off-site copy, or disaster-recovery backup. Establishing an independently stored verified backup remains an operational priority.

## Recovery readiness without production replacement

Snapshot 1 was restored with SQLite's backup API to the explicitly named temporary validation file under `state\recovery`. It was never promoted over production.

- Staging duration: 4.536 seconds
- Staged size: 271,785,984 bytes
- UUID/role/schema matched production
- M9/M10/M11 and control-plane counts matched production
- Integrity: `ok`
- Foreign-key violations: 0
- Production database SHA-256 was unchanged before/after staging
- Temporary staged database was removed after its exact path was verified

The real catalogue was never renamed, replaced, or opened for a recovery write.

## Routine operational commands

Run health regularly and create a snapshot after significant catalogue changes:

```powershell
personal-librarian production health --app-data-root '<data-root>'
personal-librarian catalogue backup create --app-data-root '<data-root>' --reason 'owner reason'
personal-librarian catalogue backup list --app-data-root '<data-root>'
personal-librarian catalogue backup verify --app-data-root '<data-root>' --manifest '<absolute manifest path>'
personal-librarian catalogue backup report --app-data-root '<data-root>'
```

Health should be investigated when it returns `WARN` or `FAIL`. Backup retention remains report-only with a conservative keep-latest-10 default; M21 adds no scheduler and deletes no backup.

## Portability and current installation

Production data does not depend on the repository location. Every operational command receives the independent application-data root explicitly, and the production catalogue/backups reside entirely under `<data-root>`. The root can be migrated through a future verified control-plane procedure without moving the source repository, although its recorded fingerprint/provenance must be handled deliberately.

The current `personal-librarian.exe` launcher is under `C:\Python313\Scripts`, and package metadata reports an editable project location of `H:\PersonalLibrarian`. Therefore today's CLI code execution depends on that editable checkout remaining available or the package being reinstalled after the repository moves. This is a code/package dependency, not a production-data dependency. M21 does not treat the editable install as production packaging and does not build an installer.

## Next operational concerns

1. Establish and verify an independent backup on different hardware/NAS, with an explicit owner-approved destination and recovery test.
2. Decide how routine health and backup reminders should be surfaced before introducing scheduling.
3. Replace the editable development install with a supported packaging/deployment method in a later milestone.
4. Continue monitoring H: because the catalogue and current snapshots share it.
5. Begin a user-facing desktop review interface only after production operational close-out.

Delete, general copy/move/rename execution, bulk quarantine, near-duplicate cleanup, and automatic canonical selection remain unavailable.
