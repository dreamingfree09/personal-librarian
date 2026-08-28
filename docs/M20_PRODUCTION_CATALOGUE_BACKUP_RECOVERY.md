# M20 - Production Catalogue, Backup and Recovery Foundation

Date: 23 August 2026

Status: implementation complete; temporary validation only; permanent owner root not selected

## Purpose and boundary

M20 protects the SQLite catalogue/control plane. It establishes an explicit application-data layout, catalogue identity, verified bootstrap, SQLite-safe backups, health reporting, and a confirmed recovery workflow.

It does not scan, hash, copy, move, rename, quarantine, or delete media. General filesystem execution, bulk quarantine, near-duplicate cleanup, automatic canonical selection, overwrite, and delete remain unavailable. The narrow M19 quarantine/restore workflow is unchanged.

## Explicit application-data root and layout

The owner must supply an absolute Windows drive or UNC application-data root. Application code contains no permanent drive or fallback. Z: is rejected lexically before access. Parent traversal, unsafe resolved boundaries, symlink/reparse roots, and paths outside the approved root fail closed.

The deterministic layout is:

```text
<app-data-root>\
    catalogue\
        personal_librarian.sqlite3
    backups\
        catalogue\
    logs\
    exports\
    state\
        recovery\
```

Bootstrap may create only these directories inside the explicit root. M20 validation uses temporary roots; it does not choose or create the owner's permanent production location.

## Catalogue identity and schema

Migration 8, `production_catalogue_identity`, adds the singleton `catalogue_identity` table. It records:

- a UUID independent of the filename;
- UTC creation time;
- application and bootstrap schema versions;
- `production` or `non-production` role;
- a versioned SHA-256 fingerprint of the normalised application-data root;
- JSON bootstrap/import provenance; and
- the time production status was assigned.

Identity provenance is immutable. Bootstrap initially writes `non-production` and changes the role to `production` only after evidence reconciliation, integrity checking, foreign-key checking, and schema/UUID verification all pass.

## Bootstrap workflow

`personal-librarian production bootstrap` requires the explicit application-data root and all verified M9/M10/M11 evidence paths. It:

1. validates and creates the deterministic in-root layout;
2. refuses if the production filename already exists, with no force/overwrite option;
3. creates a uniquely named staging database inside the catalogue directory through normal migrations;
4. imports evidence through the existing transactional M14 importers;
5. requires every frozen M9/M10/M11 baseline to report `MATCH`;
6. verifies current schema, catalogue UUID, `integrity_check`, and `foreign_key_check`;
7. marks the staged catalogue as production; and
8. checkpoints WAL and atomically promotes the same-filesystem staging file.

On failure, staging database/WAL files are removed and the production path is never created. No existing production catalogue can be silently adopted or replaced.

## SQLite runtime settings

Production bootstrap intentionally selects conservative single-user desktop settings:

- `foreign_keys = ON` on every application connection;
- `journal_mode = WAL` for the production catalogue;
- `synchronous = FULL` during production setup; and
- `busy_timeout = 5000` milliseconds.

Backups use Python's SQLite backup API from a live read-only source connection. Tests confirm a committed row still resident in a WAL is present in the snapshot. The implementation never blindly copies a live database file.

## Backup architecture and manifest

`catalogue backup create` defaults to `<app-data-root>\backups\catalogue` and accepts an explicit alternate absolute safe backup root. It refuses unsafe roots, Z:, non-production sources, collisions, and the production database path. It has no overwrite or force option.

A uniquely named incomplete database is populated through the SQLite backup API. Before acceptance it must open read-only and pass current schema, production role, expected catalogue UUID, `PRAGMA integrity_check = ok`, and zero-row `PRAGMA foreign_key_check`. SHA-256 is then streamed, the database is promoted, and a JSON manifest is exclusively created.

Manifest version 1 includes backup ID, source UUID/schema/path/size, timestamp, backup filename/size/SHA-256, integrity and foreign-key results, application version, reason, backup duration, and hash duration. An accepted snapshot always has both database and manifest. A failed incomplete artefact is removed and never affects an older backup.

`catalogue backup verify` rechecks manifest version/status, filename safety, file existence, SHA-256, UUID, schema, production role, integrity, foreign keys, and manifest/schema agreement. `list` recognises only matching Personal Librarian manifest names with accepted JSON metadata; unknown files are ignored.

## Retention policy

The conservative default is to keep the latest 10 accepted backups. M20 implements retention reporting only: `catalogue backup report --keep-latest N` identifies older recognised manifest candidates but deletes nothing. Unknown files are ignored. Actual pruning remains deferred until separately owner-approved; no broad folder cleanup exists.

A backup under the same application-data root protects against catalogue mistakes and some local corruption. It is not an independent/off-site disaster-recovery copy and must not be represented as one.

## Health model

`personal-librarian production health --app-data-root ...` reads catalogue and backup metadata without scanning media. It reports path, UUID, role, schema, file size, journal mode, integrity and foreign-key results, latest accepted backup, age/count, decision events, action plans, executions/events, and unresolved `recovery_required` executions.

The summary is:

- `PASS`: catalogue checks pass, at least one accepted backup exists, and no execution needs recovery;
- `WARN`: integrity/identity pass but backup or execution-recovery attention is needed; or
- `FAIL`: catalogue missing, unreadable, wrongly identified, unsupported, or structurally invalid.

## Recovery workflow and confirmation

`production recover` requires `--confirm-restore-catalogue` and an explicit actor. There is no force option. Before replacement it:

1. identifies the current production catalogue and UUID;
2. verifies the selected manifest/hash and backup read-only;
3. rejects a different UUID, schema, role, integrity result, or foreign-key result;
4. writes a durable external recovery-attempt journal under `state\recovery`;
5. creates and verifies a fresh pre-recovery backup of the readable current catalogue;
6. stages the candidate through the SQLite backup API inside the catalogue directory;
7. verifies the staged database again;
8. atomically renames the current catalogue to a unique safeguarded filename;
9. atomically promotes the staged database; and
10. verifies the replacement.

If promotion fails, the safeguarded catalogue is renamed back. If final verification fails, the failed replacement is preserved separately and the safeguarded original is restored. The old production database is never simply deleted. Staging and replacement are on the same filesystem; inability to perform this controlled rename/swap fails closed.

The external JSON recovery journal records attempt ID/time/actor, source backup/hash, old production hash, production/staging/safeguard paths, pre-recovery backup, verification outcome, result, and timing. It survives catalogue replacement and retains failed/interrupted attempt evidence.

## Backup-before-control-plane-write policy

A fresh verified backup is required or strongly recommended before high-value catalogue changes: future production schema migrations, recovery, bulk evidence import/re-import, future bulk action execution, and significant catalogue transformations. It is not required before each ordinary append-only review or decision event.

Migrations 1-8 remain deterministic history. Going forward, production migration policy is: verify the current catalogue, create and verify a recoverable backup where practical, then migrate. A migration must never silently destroy the only valid production copy.

## CLI

```powershell
personal-librarian production bootstrap --help
personal-librarian production health --help
personal-librarian production recover --help
personal-librarian catalogue backup create --help
personal-librarian catalogue backup list --help
personal-librarian catalogue backup verify --help
personal-librarian catalogue backup report --help
```

Commands support `--format human|json` under the established structured-output convention. All require an explicit application-data root; bootstrap additionally requires every evidence path, and recovery requires the manifest, actor, and confirmation gate.

## Validation and limitations

Synthetic tests use temporary directories and catalogues. They cover explicit roots and lexical Z: rejection, layout, successful/mismatched/existing bootstrap, UUID/role metadata, WAL-safe snapshots, manifests and SHA-256, integrity/foreign-key/UUID rejection, list/report behavior, unknown-file retention safety, health outcomes, recovery verification/confirmation/replacement, old-catalogue safeguarding, and external history.

The bounded full-evidence validation is also confined to a temporary root. It bootstraps the verified M9/M10/M11 evidence, checks frozen baselines, health, two backups and manifests, stages a restore, performs one synthetic production replacement, and verifies SQLite integrity/foreign keys throughout. The temporary root is removed after measurement.

The 23 August 2026 bounded run reported all frozen baselines `MATCH`. Bootstrap took 65.160 seconds and produced a 271,785,984-byte catalogue. Two accepted snapshots were the same size, took 9.310 and 9.258 seconds, and required 0.219 and 0.252 seconds for SHA-256; both had digest `4a1dec1d14c4a19bbb67990807d13941a280b6d682efdae2dc03fc23f1a549e9`. A separate staged restore took 4.810 seconds and matched the source counts. The confirmed replacement, including its pre-recovery backup and repeated verification, took 25.220 seconds. Final health was `PASS`, every integrity check returned `ok`, every foreign-key check returned zero rows, the synthetic post-backup marker was absent after recovery, and the temporary root was removed.

Deliberate limitations:

- no permanent owner application-data root has been selected;
- retention pruning is report-only;
- local snapshots are not independent/off-site backup;
- recovery preserves the pre-recovery database and does not auto-prune it;
- no scheduled backup service, installer, encryption/key management, cloud replication, or multi-user coordination is introduced; and
- no media operation or broader execution capability is introduced.
