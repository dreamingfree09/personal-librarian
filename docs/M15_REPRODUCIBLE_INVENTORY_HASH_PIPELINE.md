# M15 - Reproducible Inventory and Exact-Hash Pipeline

Date: 21 August 2026

Status: implementation and bounded real-data pilot complete; M15 remains open pending owner close-out decision

## Purpose and architecture

M15 replaces the historical one-off M9/M10 mechanics with source-controlled Python code. The primary state is SQLite; CSV is not required for operation.

The pipeline has four small layers:

- `inventory.py` performs deterministic, metadata-only filesystem traversal;
- `hashing.py` streams SHA-256 and applies conservative cached-observation reuse;
- `checkpoints.py` persists job/config identity and per-item completion; and
- `exact_duplicates.py` derives informational exact-copy groups from a completed hash job.

`reconciliation.py` compares catalogue state with the verified M9/M10 baseline. Schema migration 3 adds `pipeline_jobs`, `pipeline_job_items`, and state-qualified `pipeline_hash_observations`. Existing catalogue entities remain authoritative for sources, batches, physical instances, inventory observations, SHA-256 assertions, content identities, and duplicate groups.

## Media extension policy

Policy version: `m9-media-extensions-v1`.

Extensions are matched case-insensitively and deterministically:

`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.mp4`, `.mpg`, `.mkv`, `.avi`, `.3gp`

This exactly reflects the verified M9 population. Unsupported extensions are checkpointed as `unsupported_extension`; they are not decoded or hashed.

## Inventory behavior

Each run requires an explicit database, job ID, source label, and root. The root passes the M13 safety policy before traversal. Directory and filenames are sorted by the non-authoritative Windows comparison key with raw text as a tie-breaker.

Inventory records source, exact raw relative path, current absolute path, extension, size, UTC-aware filesystem modification time, nanosecond mtime state, and the existing path comparison key. File content is never opened. Zero-byte media are explicit `zero_byte_inventory` successes. Directory/file disappearance, permission, and other access errors remain distinct outcomes.

Physical stable identity combines the stable source key and exact raw relative path. Existing M14 instances with the same exact source/path are reused. Comparison-key or Unicode-normalization equality never establishes identity.

## SHA-256 and reuse policy

SHA-256 is the only M15 content algorithm. Reads are sequential in 1 MiB chunks; a whole file is never loaded into memory. Size and nanosecond mtime are captured before and after reading. A change discards the digest and records `changed_during_hash`.

A cached digest may be reused only when all are identical:

- physical catalogue instance;
- byte size;
- nanosecond filesystem modification time; and
- a prior successful M15 SHA-256 observation containing a digest.

Imported M10 hashes do not satisfy this cache rule because they lack the M15 nanosecond state observation. Metadata equality authorizes cache reuse under this explicit policy; it is not described as new cryptographic verification. Changed size or mtime forces a new read under a new hash job.

Successful SHA-256 attaches the physical instance to deterministic `sha256:<digest>` content identity. Multiple physical instances can reference one content identity. Exact grouping reports copies, memberships, redundant-copy count, and informational reclaimable bytes; it never chooses or deletes a copy.

## Checkpoint and resume strategy

Every command requires an explicit job ID. The stored job binds that ID to pipeline version and canonical JSON configuration fingerprint. Reusing an ID with different source, root, limits, upstream job, or policy fails safely.

Each completed item and its observed file state commits atomically with catalogue changes. An interrupted job retains completed checkpoints. Resume re-enumerates deterministically, skips items whose exact state is already committed, and continues. A completed job is idempotent and returns its stored catalogue-derived summary. New filesystem state should normally use a new explicit job ID, allowing prior observations to remain auditable.

## Error states

- `inventory_success`
- `zero_byte_inventory`
- `unsupported_extension`
- `hash_success`
- `hash_reused`
- `zero_byte_hashed`
- `zero_byte_reused`
- `permission_denied`
- `unreadable`
- `disappeared`
- `changed_during_hash`

Empty content receives the valid SHA-256 digest of zero bytes when readable. Empty, missing, and unreadable are never conflated.

## CLI

```powershell
personal-librarian inventory scan `
  --database 'C:\explicit\catalogue.sqlite3' `
  --job-id inventory-20260821 `
  --source OneDrive `
  --root 'H:\explicit\media-root'

personal-librarian hash sha256 `
  --database 'C:\explicit\catalogue.sqlite3' `
  --job-id sha256-20260821 `
  --inventory-job inventory-20260821 `
  --source OneDrive `
  --root 'H:\explicit\media-root'

personal-librarian exact-duplicates report `
  --database 'C:\explicit\catalogue.sqlite3' `
  --job-id exact-20260821 `
  --hash-job sha256-20260821

personal-librarian pipeline reconcile `
  --database 'C:\explicit\catalogue.sqlite3'
```

Inventory and hash commands accept a positive `--limit` for bounded pilots. All commands provide human and JSON summaries. Reconciliation returns a non-zero status when any historical baseline differs.

## Unicode, paths, and safety

Python-native `pathlib`/`os.walk` APIs preserve raw Greek, NFC, and NFD names. No JSON path stream passes through legacy PowerShell decoding. Raw path and normalized comparison key remain separate. Hashing verifies that every catalogue path passes M13 safety and remains lexically inside the explicit inventory root before opening it. Z: is rejected before any filesystem access.

The pipeline only reads media metadata/content. It has no move, rename, delete, quarantine, canonical-selection, rclone, perceptual-hash, UI, or hidden-root behavior. Catalogue writes are control-plane writes to the explicit database.

## Validation results

Synthetic validation covers deterministic nested inventory, extension rules, Greek/NFC/NFD raw paths, zero-byte files, streaming digest correctness, state-qualified reuse, changed-size and changed-mtime rehash, disappeared and permission-denied files, changed-during-read rejection, inventory/hash interruption and resume, idempotency, exact grouping, reclaimable bytes, relative/absolute root policy, Z: rejection, catalogue integration, and preservation of source bytes/mtime.

The host rejected creation of a synthetic path longer than 260 characters with Windows error 206, so that capability test is reported as a host skip. The implementation uses Python-native path APIs and imposes no shorter application limit.

### Bounded real-data pilot

Root: `H:\PersonalLibrary\Staging\OneDrive\CameraRoll`

- deterministic limit: 5 media files;
- inventory: 5 rows, 20,942,861 bytes;
- initial SHA-256: 5 successes, 0 errors, 5 distinct digests;
- comparison with verified M10: 5/5 digests matched;
- second independent hash job: 5/5 state-qualified cache reuses;
- exact groups in this subset: 0;
- SQLite integrity: `ok`; foreign-key violations: 0.

No full media rehash was performed because it would reread approximately 122 GB without adding evidence needed to validate the implementation.

### Historical catalogue reconciliation

The new reconciliation command was run against a temporary schema-v3 catalogue populated from the verified M9/M10/M11 CSV evidence. Every M9/M10 baseline matched:

- inventory: 69,444 rows; 122,312,861,984 bytes; source counts 23,538 / 4,287 / 837 / 40,782;
- SHA-256: 69,444 mapped successes and 56,127 distinct identities;
- exact duplicates: 7,707 groups, 21,024 memberships, 13,317 redundant copies, and 25,488,473,284 informational reclaimable bytes.

## Known limitations and close-out boundary

- The new pipeline has been validated on synthetic cases and a bounded real pilot, not by a full 122 GB rehash.
- Stable physical identity is source plus exact raw relative path; rename/move correlation remains a later policy problem.
- Metadata-qualified cache reuse cannot detect content changes that preserve both size and nanosecond mtime; a new forced-rehash mode may be added if operationally required.
- The current implementation is deliberately sequential.
- No permanent production catalogue location, backup schedule, or recurring job scheduler is selected here.
