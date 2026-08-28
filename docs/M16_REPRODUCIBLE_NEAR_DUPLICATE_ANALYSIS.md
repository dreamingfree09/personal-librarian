# M16 - Reproducible Near-Duplicate Analysis

Date: 22 August 2026

Status: implementation and bounded real-data validation complete; M16 remains open pending owner close-out decision

## Purpose and safety boundary

M16 replaces the historical one-off M11 pHash/dHash mechanics with source-controlled application code. SQLite is the primary state; historical CSV evidence remains preserved and can be reconciled.

The implementation keeps four concepts separate:

- SHA-256 content identity represents exact byte identity;
- pHash/dHash relationships represent perceptual similarity evidence;
- connected components are review groupings; and
- canonical nominations and owner decisions remain separate, explicit future actions.

Near-duplicate analysis never merges or mutates content identities. It does not select canonical copies or move, rename, quarantine, delete, or modify media. All output remains Analyse/Recommend evidence under `Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act`.

## Architecture and dependencies

The M16 layer has four focused modules:

- `perceptual_hashing.py` selects exact identities and computes or reuses pHash/dHash observations;
- `similarity.py` uses a deterministic Hamming-distance index and records accepted review relationships;
- `similarity_groups.py` builds deterministic connected-component review groups; and
- `near_duplicate_reconciliation.py` compares imported verified M11 evidence with the approved baseline.

M15 checkpoint principles are reused through the common checkpoint module. Migration 4 adds M16-specific job/item tables because the migration-3 job-kind constraint is deliberately closed, and adds nullable chosen-physical-instance provenance to content hash observations.

Runtime dependencies are Pillow 11/12 and NumPy 2.x. Pillow supplies supported image decoding, grayscale conversion, and deterministic LANCZOS resizing. NumPy supplies the small deterministic DCT calculation. ImageHash, SciPy, PyWavelets, GPU libraries, facial recognition, and semantic/AI similarity are not required.

## Input and representation selection

M16 operates once per SHA-256 content identity for catalogue instances whose extension is one of:

`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`

Content identities and representations are ordered deterministically. For each identity, the pipeline tries its exact-copy physical instances in stable order until it finds a readable, supported image. Every path passes the M13 policy before it is opened. The selected physical instance, path, source, represented exact-copy count, analysis run, and algorithm version are retained with both observations.

An exact identity with multiple physical copies is perceptually analysed once, not once per path. A missing or broken preferred representation does not prevent a later exact-copy representation from supplying the observation.

## Perceptual hash algorithms

Hash-suite version: `m16-imagehash-compatible-v1`.

### pHash

Algorithm name: `pHash`; algorithm version: `m16-imagehash-compatible-v1:phash-8x8-hf4-lanczos`.

The image is converted to grayscale and resized to 32 x 32 with Pillow LANCZOS. A deterministic unnormalised two-dimensional DCT is calculated, the upper-left 8 x 8 coefficients are compared with their median, and the 64 result bits are stored as a 16-character hexadecimal value. The implementation was checked against ImageHash 4.3.2 behavior without making ImageHash or SciPy runtime dependencies.

### dHash

Algorithm name: `dHash`; algorithm version: `m16-imagehash-compatible-v1:dhash-8x8-horizontal-lanczos`.

The image is converted to grayscale and resized to 9 x 8 with Pillow LANCZOS. Each pixel is compared with its horizontal neighbor, producing a deterministic 64-bit hexadecimal hash compatible with the historical ImageHash behavior.

Neither perceptual hash is an identity key.

## Reuse and errors

A successful perceptual observation may be reused only for the same SHA-256 content identity and exact algorithm version. A different identity or algorithm version produces a distinct analysis context and cannot use that observation. Imported M11 observations are retained as historical evidence but do not silently satisfy the M16 cache because their algorithm provenance is different.

Per-identity checkpoints distinguish `success`, `reused`, `decode_error`, `missing`, `unreadable`, `unsupported_format`, and `zero_byte`. A bad image does not abort the run. Python-native paths preserve Greek and distinct NFC/NFD raw names. Z: is rejected from lexical path evidence before an image decoder can access it.

## Candidate search and approved rule

Rule version: `m16-phash4-dhash4-v1`.

The final relationship rule is exactly:

```text
pHash Hamming distance <= 4
AND
dHash Hamming distance <= 4
```

A deterministic 64-bit BK-tree finds pHash neighbors without an all-pairs O(n squared) scan; candidates then receive the independent dHash test. Content identities and relationship endpoints are stably ordered. The catalogue stores both distances separately, the rule and hash versions, analysis-run provenance, and a `review_only` tier. Relationship keys are deterministic and idempotent. The historical pHash <= 6 discovery threshold is not used as the final rule.

## Review grouping

Deterministic union-find connected components are built from accepted relationships. Group keys derive from the ordered member identity keys and rule version. Membership and relationship provenance remain evidence; grouping never establishes exact identity.

Review tiers are:

- up to 20 contents: `review_only`;
- 21 through 50: `large_low_confidence_review_only`; and
- over 50: `very_large_low_confidence_review_only`.

Both thresholds are reported explicitly. Large groups remain low-confidence because repeated layouts and screenshots created structural false positives in M11.

## Checkpoint and resume behavior

Hashing, relationship generation, and group generation each use an explicit job ID, canonical configuration fingerprint, upstream job reference where applicable, and per-item committed checkpoints. An interrupted run retains committed work and resumes deterministically. Repeating a completed configuration is idempotent. Reusing a job ID with a changed limit, upstream context, algorithm version, or rule version fails safely; changed versions require distinct analysis context.

The implementation is sequential. It commits small durable units rather than retaining the complete result in memory.

## Catalogue integration

Schema migration 4, `reproducible_near_duplicate_pipeline`, adds:

- `content_hash_observations.physical_instance_id` for the chosen representation;
- `similarity_pipeline_jobs` for explicit M16 stage/config state; and
- `similarity_pipeline_items` for per-identity, relationship, and group checkpoints/outcomes.

Existing tables remain authoritative for content identities, physical instances, perceptual observations, analysis runs, similarity relationships, groups, memberships, and relationship/group provenance. No CSV output is required for normal operation.

## CLI

```powershell
personal-librarian similarity hash `
  --database 'C:\explicit\catalogue.sqlite3' `
  --job-id perceptual-20260822 `
  --limit 20

personal-librarian similarity analyse `
  --database 'C:\explicit\catalogue.sqlite3' `
  --job-id relationships-20260822 `
  --hash-job perceptual-20260822

personal-librarian similarity report `
  --database 'C:\explicit\catalogue.sqlite3' `
  --job-id groups-20260822 `
  --analysis-job relationships-20260822

personal-librarian similarity reconcile `
  --database 'C:\explicit\catalogue.sqlite3'
```

Hash and analysis accept an optional positive `--limit` for bounded work. Hash-suite and relationship-rule versions may be explicit. Every stage returns human-readable counts and a machine-readable JSON summary. There is no hidden media root or destructive action mode.

## Validation

Synthetic tests cover deterministic pHash and dHash values, exact-copy deduplication before perceptual analysis, byte-different visually identical content, independent and combined distance thresholds, ordered relationship keys, connected components, both large-group tiers, idempotency, hash reuse, interrupted/resumed hashing, version isolation, invalid and zero-byte images, Greek and distinct NFC/NFD paths, unchanged source bytes/mtime, and Z: rejection before decoder access.

The local implementation produced the same pHash and dHash as ImageHash 4.3.2 for a deterministic reference fixture.

### Bounded real-data pilot

A temporary schema-v4 catalogue was populated from the existing verified M9/M10/M11 evidence. A deterministic 20-identity pilot produced:

- 20 pHash successes and 0 errors;
- 20 dHash successes and 0 errors;
- 20 physical copies represented;
- 40/40 generated observations matching imported M11 values exactly;
- 0 accepted pairs and 0 groups within that bounded subset; and
- a second independent job reusing 20/20 identity/version-qualified observations.

The initial CLI hash stage took approximately four seconds in the validation environment. Candidate search over the bounded population completed in approximately one second including process startup. Work was sequential, CPU-only, and used no full-library decode, full SHA-256 rehash, or GPU.

### Historical M11 reconciliation

The reconciliation command compared the imported verified historical run with the approved M11 baseline. Every metric reported MATCH:

- candidate identities: 54,839;
- pHash successes/errors: 54,839 / 0;
- physical copies represented: 64,569;
- dHash successes/errors: 54,839 / 0;
- accepted pairs: 9,403;
- review groups: 5,067;
- grouped unique contents: 11,325;
- largest group: 135;
- groups over 20: 12; and
- groups over 50: 1.

This reconciles preserved verified evidence; it does not claim a new full-library perceptual rehash. The bounded 40/40 comparison supplies direct algorithm-compatibility evidence without unnecessary full media I/O.

## Known limitations and close-out boundary

- Validation intentionally avoids regenerating all 54,839 perceptual hashes; compatibility is supported by deterministic fixtures, a bounded real comparison, and full imported-evidence reconciliation.
- Animated formats use the decoder's initial frame, matching ordinary Pillow/ImageHash behavior; no video or animation similarity is attempted.
- Perceptual hashes and dual-hash thresholds can still produce false positives and false negatives. All relationships require human review.
- The BK-tree is in-memory and sequential. It is appropriate for the historical population but is not a distributed index.
- No scheduler, UI, production catalogue location, canonical workflow, facial recognition, or semantic similarity is introduced by M16.
