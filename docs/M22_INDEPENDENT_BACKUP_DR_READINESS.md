# M22 - Independent Backup and Disaster-Recovery Readiness

Date: 23 August 2026

Status: independent hardware backup and recovery-readiness validation complete; pending owner close-out

## Scope and safety boundary

M22 protects the production catalogue/control plane on a second local physical device. The owner-approved roots are:

- Production: `<data-root>`
- Independent backup: `<backup-root>`

The server/NAS was unavailable and was not contacted, discovered, mounted, configured, or used. Z: was not accessed. No media was scanned, hashed, copied, moved, renamed, quarantined, or deleted, and no production decision, plan, or execution was created.

## Physical-device independence

Host storage inspection confirmed:

- H: is Windows storage device 2, `WDC WD1002FBYS-18W8B1`, serial `<redacted-machine-serial>`, SATA HDD.
- X: is Windows storage device 1, `KINGSTON SA400S37240G`, serial `<redacted-machine-serial>`, SATA SSD.

Both NTFS volumes reported `Healthy`, `OK`, online, and writable. Before the M22 write, X: had 197,357,674,496 bytes free and the approved root was an ordinary empty directory. The application now resolves Windows storage device numbers and rejects `independent-local` creation when production and destination are measurably on the same physical device or independence cannot be established.

X: is an independent physical-device backup, but it remains local. It is not off-site, geographically independent, a NAS copy, or protection against every shared-site risk.

## Independent layout

M22 uses the existing backup architecture under the approved X: root:

```text
<backup-root>\
    backups\
        catalogue\
            catalogue-<timestamp>-<backup-id>.sqlite3
            catalogue-<timestamp>-<backup-id>.manifest.json
```

No hidden production root exists on X:. No retention deletion, pruning, or unknown-file cleanup is available.

## Backup classes and manifest v2

Backup classes are explicit:

- `operational-local`: routine snapshots, normally under the H: application-data root;
- `independent-local`: a local disaster-recovery snapshot on a confirmed different physical device.

Manifest version 2 adds:

- backup class;
- approved backup root and actual backup directory;
- destination-root fingerprint;
- source/destination physical-device identities;
- confirmed device-independence state;
- key catalogue counts; and
- creation verification status.

The manifest retains UUID, schema, timestamps, source path/size, backup filename/size/SHA-256, SQLite integrity and foreign-key results, application version, reason, and timing. Version 1 operational manifests remain readable for backward compatibility. X: contains both the database and all metadata needed for standalone validation after loss of H:.

## Creation workflow

The production database is opened through the existing SQLite-safe source connection. SQLite's backup API writes a uniquely named incomplete database directly to X:. The X: database is then opened immutable/read-only, checked for catalogue identity/schema/integrity/foreign keys/counts, streamed through SHA-256, promoted without overwrite, and paired with an exclusively created manifest.

There is no blind live-database file copy and no intermediate H: snapshot in this workflow. Cross-device success is established by independent verification of the completed X: artefact rather than by trusting the write call.

## First independent backup

- Backup class: `independent-local`
- Backup ID: `7883e7cb-7359-4bb7-898d-b9497829d0bf`
- Database: `catalogue-20260823T105007236536Z-7883e7cb-7359-4bb7-898d-b9497829d0bf.sqlite3`
- Manifest: `catalogue-20260823T105007236536Z-7883e7cb-7359-4bb7-898d-b9497829d0bf.manifest.json`
- Created: `2026-08-23T10:50:12.345156Z`
- Size: 271,785,984 bytes
- SHA-256: `f3572f8bd42611781a1360168bd44508a63b3134e4790ec0a8e394f5ef474b78`
- Duration: 5.109 seconds
- SHA-256 duration: 0.223 seconds
- Source device: `windows-storage-device:2`
- Destination device: `windows-storage-device:1`
- Destination fingerprint: `2cb9cbfa1382b4fd9b20f7ccb5fa0fa4e7698b8ffd1cd3ca4899200bda2a437d`
- Device independence: `confirmed`

The digest matches the two H: operational snapshots because catalogue state was unchanged. The X: file is nevertheless a separate SQLite-safe snapshot on another physical device with its own backup ID and manifest.

## Independent verification and counts

Independent verification returned `ACCEPTED`:

- Catalogue UUID: `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Role: `production`
- Schema: 8
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: zero rows
- Inventory observations: 69,444
- Physical instances: 69,444
- Content identities: 56,127
- Exact duplicate groups: 7,707
- Similarity relationships: 9,403
- Similarity groups: 5,067

The CLI can cross-check against live production or validate standalone after H: loss:

```powershell
personal-librarian catalogue backup verify `
  --manifest '<backup-root>\backups\catalogue\<manifest>.json' `
  --expected-catalogue-uuid '613affe5-a00b-49bc-9ad9-99b95adeec33'
```

The database UUID must match both the manifest and any explicit expected UUID. Manifest schema/counts must match the actual database.

## Inventory, readiness, and freshness

Independent inventory reports one valid backup, its location, age, size, digest, UUID/schema, and verification result. Unknown files are ignored and never removed. Retention remains report-only.

Production health accepts an optional independent root:

```powershell
personal-librarian production health `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

Catalogue health and disaster-recovery readiness are distinct. The catalogue may remain `PASS` while X: is disconnected; the nested DR result reports `WARN`. DR readiness is:

- `PASS`: at least one independently verified backup exists and the newest is no more than seven days old;
- `WARN`: X: is disconnected, no accepted backup exists, a backup is stale, or some manifests are rejected while another usable copy remains; or
- `FAIL`: independent manifests exist but none verify successfully.

The freshness threshold is seven days (604,800 seconds). M22 creates no scheduler, service, automatic deletion, or retention pruning.

## Recovery staging from X:

The independent backup was restored through SQLite's backup API to the temporary path `<data-root>\state\recovery\m22-independent-recovery-validation.sqlite3`. It was never promoted or substituted for production.

- Staging duration: 4.666 seconds
- Staged size: 271,785,984 bytes
- UUID/role/schema matched production
- All six key counts matched production
- Integrity: `ok`
- Foreign-key violations: 0
- Production SHA-256 before/after: `8D2BA2CA7F7F45C395609453B583FE5AD67C52E92463859484F0293422D1501C`
- Temporary validation catalogue was removed after its exact path was verified

The production database remained unchanged.

## Owner-controlled H:-loss procedure

If H: becomes unavailable while X: survives:

1. Stop routine Personal Librarian writes and preserve X: unchanged.
2. Obtain a supported Personal Librarian installation/source checkout on the surviving or replacement computer. The current editable checkout is on H: and must not be assumed to survive H: loss.
3. Choose and manually create a replacement application-data root on healthy storage other than X:. Do not turn the only X: backup into the working production copy.
4. Run standalone verification of the X: manifest/database with the known catalogue UUID. Require SHA-256, UUID/schema, integrity, foreign keys, and counts to pass.
5. Use SQLite's backup API to stage the verified X: database inside the replacement root; never raw-copy a live database.
6. Verify the staged database again before production assignment.
7. Record an external recovery journal containing source manifest/hash, destination, identity, timestamps, actor, and verification results.
8. With explicit owner confirmation and an empty destination, atomically promote the staged database where supported.
9. Run production health, verify counts, and immediately create a new independent backup on a device other than the new production device.
10. Preserve the original X: snapshot until the recovered installation and its new independent backup are proven.

M22 documents but does not automate empty-root promotion. The existing production recovery command protects replacement of an identified existing catalogue; a future recovery-kit milestone should add a separately confirmed empty-root disaster-restoration workflow and durable packaging.

## Routine commands

```powershell
personal-librarian catalogue backup create `
  --app-data-root '<data-root>' `
  --backup-root '<backup-root>' `
  --backup-class independent-local `
  --reason 'Independent DR snapshot'

personal-librarian catalogue backup list `
  --app-data-root '<data-root>' `
  --backup-root '<backup-root>' `
  --backup-class independent-local

personal-librarian catalogue backup report `
  --app-data-root '<data-root>' `
  --backup-root '<backup-root>' `
  --backup-class independent-local
```

Run health routinely and create a fresh X: snapshot after significant catalogue changes or before the seven-day threshold expires.

## Limitations and next boundary

- X: protects against loss of the H: device, not loss/theft/disaster affecting both local devices.
- The NAS/server was not available and was not used; future NAS addition requires separate owner approval and validation.
- The current editable application install and repository are on H:, so code/package recovery is not yet independently protected by this catalogue-only backup.
- Empty-root disaster promotion remains an explicitly documented manual procedure.
- No scheduled automation, encryption/key management, media backup, or broad filesystem execution exists.
- The two H: operational snapshots remain unchanged and preserved.

General delete/copy/move/rename execution, media quarantine, automatic canonical selection, installer work, and UI work remain outside M22.
