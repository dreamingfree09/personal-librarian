# Personal Librarian - Project Truth

**Version:** 3.3
**Date:** 27 August 2026
**Current phase:** M30 - Preferred Date Evidence and Cross-Year Collections Design/Foundation - COMPLETE

> Recovery-era living Project Truth.
> The original working copy was lost when the former Z: storage device became unreliable on 17 August 2026.
> This document preserves the known project state and supersedes that lost working copy.

## 1. Mission

Personal Librarian exists to bring years of scattered personal photos, videos and later other digital material into one trustworthy, locally controlled library.

Primary media sources include:

- Microsoft OneDrive
- Google Photos
- Current phone
- Dropbox
- Historical HDD material
- Old phones
- Future NAS / server sources

Later scope may include documents, hyperlinks, notes and other personal digital material.

## 2. Core acquisition model

Personal Librarian follows:

Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act

Never:

Discover -> Delete

Acquisition is deliberately non-destructive.

## 3. Core principles

- Copy before changing sources.
- Verify before trusting a new copy.
- A cloud placeholder is not a verified local file.
- Preserve source separation during ingestion.
- Preserve zero-byte and unusual files until analysed.
- Do not automatically delete duplicates.
- Prefer quarantine and rollback to destructive cleanup.
- AI may recommend but must not perform destructive cleanup autonomously.
- The programme serves the library.
- The library does not belong to the programme.

## 4. Current working locations

Following the Z: storage incident on 17 August 2026:

- Programme / repository: `H:\PersonalLibrarian`
- Temporary library root: `H:\PersonalLibrary`
- Temporary staging root: `H:\PersonalLibrary\Staging`

H: is temporary working storage until the planned server/NAS is operational.

## 5. Retired Z: device

Former layout:

- `Z:\PersonalLibrarian`
- `Z:\PersonalLibrary`

Former physical device:

- Windows model: SSD 4TB
- Serial: `<redacted-machine-serial>`
- Bus: SATA
- Approximate capacity: 4 TB

On 17 August 2026 the device produced repeated real I/O failures.

Windows logged:

- Disk Event ID 51 - I/O errors on `\Device\Harddisk0\DR0`.
- NTFS Event ID 50 - delayed-write failures including `Z:\$Mft` and project Git data.
- NTFS Event ID 140 - failure to flush the NTFS transaction log, with possible corruption.

Z: is retired from active Personal Librarian use.

No Personal Librarian workflow should depend on data stored only on Z:.

## 6. Temporary H: storage

H: is on:

- Physical Disk 2
- Model: WDC WD1002FBYS-18W8B1
- Serial: `<redacted-machine-serial>`
- SATA HDD
- H: usable size approximately 839.84 GB

At migration time H: had approximately 647 GB free.

An elevated `chkdsk H: /scan` completed on 17 August 2026 with:

- no filesystem problems found
- 0 KB in bad sectors
- no further action required

Windows also reported the disk Healthy / Online and the H: volume Healthy / OK.

## 7. Current computer

- Host: `<local-workstation>`
- User: `<user>`
- Windows 11 Pro 64-bit
- CPU: AMD Ryzen 7 5800X
- RAM: approximately 64 GB
- GPU: AMD Radeon RX 5700 XT

Known drive layout during recovery:

- C: approximately 465 GB usable; approximately 41 GB free
- E: approximately 932 GB usable; approximately 183 GB free
- G: approximately 92 GB usable; approximately 85 GB free
- H: approximately 840 GB usable; approximately 647 GB free before migration
- X: approximately 224 GB usable; approximately 184 GB free
- Z: approximately 4 TB; retired from trusted use

## 8. Repository recovery

The original Git repository on Z: suffered unreadable object files during the storage incident.

A partial rescue was made to H:.

The damaged repository has been preserved at:

`H:\PersonalLibrarian\.git-damaged-20260817`

It is excluded from the new active repository.

The damaged repository retained known commit lineage through:

- `6d25bbe` - M5: harden OneDrive acquisition safety
- `69f6400` - M5: add verified OneDrive acquisition workflow
- `9d0377e` - M4: complete safe local staging
- `63ffd59` - M3: complete backup behaviour audit
- `68de305` - M2: complete source inventory
- `37d6430` - M2: record OneDrive storage state
- `9d5c29f` - M2: record Dropbox storage state
- `acba490` - M2: classify Legion backup contents
- `60de877` - M2: add initial source inventory ledger
- `07a8fb9` - M1: close workspace foundation and begin M2

A fresh repository was created on H:.

Current recovery root commit:

`aa76baa Recovery: preserve surviving Personal Librarian project`

## 9. Surviving project assets

The current M5 acquisition script survived intact:

`scripts\Invoke-M5OneDriveAcquisition.ps1`

Verified original Git blob:

`2c516e28aa56ebb17728ee3515a50639757a9406`

README.md was recovered exactly from surviving Git history.

The following documentation was reconstructed from known project records:

- `docs\M2_SOURCE_LEDGER.md`
- `docs\M3_BACKUP_BEHAVIOUR_AUDIT.md`
- `docs\M4_SAFE_LOCAL_STAGING.md`
- `docs\RECOVERY_2026-08-17.md`

## 10. Frozen baseline evidence

The lost original frozen baseline was:

`PROJECT_TRUTH.v0.2.BASELINE.md`

Previously verified original SHA-256:

`07381D7F8C03263D76AFB21A5C0A7C00EBB58F1945EE3CC2F81815AE733F7408`

That hash remains the identifier for the lost original bytes.

Any recovery reconstruction of the baseline must be clearly labelled as reconstructed and must never claim the original hash.

## 11. Completed milestones

### M0 - Project Truth Preflight
Completed before workspace construction.

### M1 - Workspace Foundation
Completed.

### M2 - Source Inventory
Completed.

Initial source categories, disks, cloud roots and synchronisation behaviour were inventoried.

### M3 - Backup Behaviour Audit
Completed.

Established that sync is not equivalent to independent backup and that cloud placeholders must not be mistaken for verified local files.

### M4 - Safe Local Staging
Completed.

Established source-separated, copy-only staging with verification required before later analysis or cleanup.

## 12. M5 - OneDrive Acquisition

M5 is COMPLETE.

Purpose: create a genuine verified local acquisition of relevant OneDrive material without deleting or modifying OneDrive originals.

Known OneDrive source groups:

- `onedrive-personal:Desktop/photos`
- `onedrive-personal:Pictures/Screenshots`
- `onedrive-personal:Pictures/Camera Roll`

Equivalent Windows OneDrive paths:

- `C:\Users\<user>\OneDrive\Desktop\photos`
- `C:\Users\<user>\OneDrive\Pictures\Screenshots`
- `C:\Users\<user>\OneDrive\Pictures\Camera Roll`

### M5 local/present acquisition before Z failure

The hardened M5 script verified all media that was already physically available through the Windows OneDrive source.

Final combined PresentOnly state before the storage incident:

- Snapshot media files: 23,470
- Present/provider-managed eligible media: 15,854
- Verified complete: 15,854
- Existing unverified: 0
- Pending PresentOnly: 0

Per group:

- DesktopPhotos: 15,581 verified present files
- Screenshots: 263 verified present files
- CameraRoll: 10 verified present files

### Known cloud-only population before direct cloud acquisition

- Cloud-only eligible media: 7,616
- Previously verified: 2
- Existing unverified: 6
- Pending media: 7,614
- Estimated pending size: approximately 9.31 GB

### Direct rclone cloud acquisition to former Z:

To avoid hydrating OneDrive Files On-Demand data onto the nearly full C: drive, rclone was configured to acquire directly from OneDrive cloud to the library.

The direct copy run to Z: completed with exit code 0 for all three groups:

- DesktopPhotos: 18,678 files transferred, approximately 12.521 GiB
- Screenshots: 4,268 files transferred, approximately 1.372 GiB
- CameraRoll: 583 files transferred, approximately 3.294 GiB

The transfer preserved more than the media-only inventory because the direct rclone operation included the complete contents of those source folders.

### Verification failure

Post-copy verification did not establish corruption in OneDrive data.

Instead, verification exposed the failing Z: device.

During `rclone check`, Windows repeatedly returned:

`A device which does not exist was specified.`

Examples included:

- failure to enumerate the Screenshots destination
- failure to calculate hashes for Camera Roll files
- repeated NTFS and disk I/O warnings in Windows Event Viewer

Therefore the Z:-based acquisition is not accepted as the final verified M5 destination.

### M5 recovery decision

OneDrive remains the authoritative source.

M5 was reacquired directly from OneDrive cloud to:

`H:\PersonalLibrary\Staging\OneDrive`

No bulk rescue of the cloud-backed library from Z: is required.

Final accepted H: verification completed on 17 August 2026.

- DesktopPhotos: 18,678 matching files; 0 differences; exit code 0
- Screenshots: 4,335 matching files; 0 differences; exit code 0
- CameraRoll: 583 matching files; 0 differences; exit code 0

**Total verified source-folder files: 23,596.**

All three verification jobs passed.

M5 is complete.

Close-out record: `docs\M5_ONEDRIVE_ACQUISITION.md`.

## 13. rclone

Portable rclone version used during M5:

- rclone v1.75.0

Portable executable survived at:

`H:\PersonalLibrarian\tools\rclone\rclone.exe`

The active rclone configuration was recreated on C: after the Z: config became unreadable.

Remote name:

`onedrive-personal`

Never commit rclone authentication configuration or credentials into Git.

## 14. Cloud backup state

Google Photos Backup remains enabled on the current phone.

OneDrive Camera Upload remains enabled and includes videos.

Observed OneDrive phone folders include:

- Camera
- Tapo
- Screen recordings
- Screenshots

Do not disable existing cloud acquisition/safety mechanisms until the replacement Personal Librarian workflow is tested and proven.

## 15. Planned milestone sequence

Current sequence:

- M5 - OneDrive Acquisition - COMPLETE
- M6 - Google Photos Acquisition - COMPLETE
- M7 - Current Phone Acquisition - DEFERRED
- M8 - Historical Sources Acquisition - COMPLETE
- M9 - Global Media Inventory - COMPLETE
- M10 - SHA-256 / exact duplicate foundation - COMPLETE
- M11 - Near-Duplicate Analysis - COMPLETE
- M12 - Organisation & Canonical Copy Policy - COMPLETE
- M13 - Application Foundation and Safety Boundaries - COMPLETE
- M14 - SQLite Catalogue and Evidence Import - COMPLETE
- M15 - Reproducible Inventory and Exact-Hash Pipeline - COMPLETE
- M16 - Reproducible Near-Duplicate Analysis - COMPLETE
- M17 - Review and Canonical-Decision Workflow - COMPLETE
- M18 - Safe Action Planning and Dry-Run - COMPLETE
- M19 - Reversible Quarantine Execution - COMPLETE
- M20 - Production Catalogue, Backup and Recovery Foundation - COMPLETE
- M21 - Production Deployment and Operational Readiness - COMPLETE
- M22 - Independent Backup and Disaster-Recovery Readiness - COMPLETE
- M23 - Desktop Review Interface Foundation - COMPLETE
- M24 - Desktop Usability and Windows Packaging - COMPLETE
- M25 - Release Engineering and First Owner Usability Pass - COMPLETE
- M26 - Desktop UX Refinement - COMPLETE
- M27 - Library Organisation, Albums and AI Suggestion Policy - COMPLETE
- M28 - Catalogue Organisation Schema and Manual Albums Foundation - COMPLETE
- M29 - Desktop Organisation and Owner Classification Foundation - COMPLETE
- M30 - Preferred Date Evidence and Cross-Year Collections Design/Foundation - COMPLETE

### M6 close-out evidence

- Completed: 18 August 2026
- Source: Google Photos
- Acquisition method: Google Takeout
- Export set: `takeout-20260817T231929Z-1`
- Raw archives retained unchanged: 2 ZIP files, 16.19 GB total
- Archive file entries: 8,574
- Both ZIP archives passed full read/decompression testing
- Cross-archive duplicate file paths: 0
- Extracted files: 8,574
- Missing files: 0
- Size mismatches: 0
- Extra files: 0
- SHA-256 part 1: `18EB7984605E9EB0CE45C23E4FF0E4E5A319544C6D6EDF1B906EAAE8A4B99BFF`
- SHA-256 part 2: `FA399349514E0FF34467A5FFAAD5977E5517BD4AB8DF2ABFD85AB3CCDE2141FB`
- Close-out record: `docs\M6_GOOGLE_PHOTOS_ACQUISITION.md`
- No Google Photos source material was deleted, reorganised or modified

### M8 close-out evidence

- Dropbox cloud: 15,746 files, 3.392 GiB, 0 differences after rclone verification
- Legion backup: 40,222 files, 161,992,258,009 bytes, verified
- φωτογραφιες: 19,253 files, 26,695,219,053 bytes, verified
- RECORDINGS: 27 files, 8,976,460,269 bytes, verified
- Androniki: 1,542 files, 6,881,391,620 bytes, verified
- CISCO: 7 files, 5,255,194,873 bytes, verified
- GMS: 202 files, 2,130,785,189 bytes, verified
- Scans: 25 files, 69,079,813 bytes, verified
- DIGITAL FORENSICS AND SYSTEM SECURITY: 33 files, 16,786,746 bytes, verified
- SYSTEM SECURITY MODULES: 18 files, 9,698,768 bytes, verified
- Close-out record: `docs\M8_HISTORICAL_SOURCES_ACQUISITION.md`
- Original sources remain untouched
- HDD_Disk2 source/staging copies are verified working copies, not independent backups

### M9 close-out evidence

- Global media inventory rows: 69,444
- Total media bytes: 122,312,861,984
- Total media size: 113.913 GB
- OneDrive: 23,538 media files
- Google Photos: 4,287 media files
- Dropbox: 837 media files
- HDD_Disk2: 40,782 media files
- Inventory file: `H:\PersonalLibrary\Staging\_inventory\global_media_inventory.csv`
- Saved CSV totals were independently re-read and matched the live inventory baseline
- No files were moved, renamed, deduplicated or deleted during M9
- No SHA-256 hashing was performed during M9
- Close-out record: `docs\M9_GLOBAL_MEDIA_INVENTORY.md`

### M10 close-out evidence

- Media inventory rows hashed: 69,444
- Valid SHA-256 hashes: 69,444
- Invalid hash rows: 0
- Exact duplicate groups: 7,707
- Files participating in exact duplicate groups: 21,024
- Redundant exact copies: 13,317
- Potential reclaimable bytes: 25,488,473,284
- Potential reclaimable size: 23.738 GB
- Google Photos + OneDrive exact-overlap groups: 3,062
- HDD_Disk2-only exact-duplicate groups: 4,351
- Hash manifest: `H:\PersonalLibrary\Staging\_inventory\M10\hashes\m10_hash_manifest.csv`
- Duplicate rows report: `H:\PersonalLibrary\Staging\_inventory\M10\reports\exact_duplicate_rows.csv`
- Duplicate groups report: `H:\PersonalLibrary\Staging\_inventory\M10\reports\exact_duplicate_groups.csv`
- Close-out record: `docs\M10_SHA256_EXACT_DUPLICATES.md`
- No files were deleted, moved, renamed or consolidated during M10

### M11 close-out evidence

- Photo-extension population assessed: 67,937
- Successfully perceptually hashed photos: 64,569
- Unique SHA-256 photo contents analysed: 54,839
- Zero-byte image placeholders excluded from perceptual analysis: 3,364
- Other unusable/non-image files identified: 3
- One valid image was blocked by a Unicode path-normalisation issue and retained unchanged
- Primary perceptual hash: pHash
- Secondary perceptual hash: dHash
- Full dHash coverage of unique image contents: 54,839 / 54,839, 0 errors
- Initial pHash candidate pairs at distance <= 6: 32,669
- pHash review set at distance <= 4: 16,304 pairs
- Dual-hash review set after requiring dHash distance <= 4: 9,403 pairs
- Dual-hash review groups: 5,067
- Unique image contents represented in dual-hash groups: 11,325
- Largest dual-hash connected group: 135 unique contents
- Groups over 20 unique contents: 12
- Groups over 50 unique contents: 1
- Large screenshot/layout clusters demonstrated that perceptual similarity is not sufficient evidence for automatic deduplication
- Large ambiguous structural-similarity clusters remain review-only
- Exact SHA-256 duplicates remain a separate M10 classification
- No files were deleted, moved, renamed or consolidated during M11
- Dual-hash manifest: `H:\PersonalLibrary\Staging\_inventory\M11\hashes\m11_unique_content_dualhash.csv`
- Dual-hash candidate report: `H:\PersonalLibrary\Staging\_inventory\M11\reports\m11_dualhash_review_phash0_4_dhash0_4.csv`
- Dual-hash group report: `H:\PersonalLibrary\Staging\_inventory\M11\reports\m11_dualhash_groups.csv`
- Dual-hash group summary: `H:\PersonalLibrary\Staging\_inventory\M11\reports\m11_dualhash_group_summary.csv`

### M12 close-out evidence

- Policy record: `docs\M12_ORGANISATION_CANONICAL_POLICY.md`
- Separate archival-canonical and display/export-canonical scopes approved
- Canonical roles are reversible catalogue decisions and never imply deletion
- Initial policy requires explicit owner approval for every canonical nomination
- Exact SHA-256 identity is evidence but does not itself authorise canonical selection
- Automatic canonical nomination remains unauthorised
- Logical organisation remains separate from physical file layout
- Date precedence, physical organisation, screenshot/document routing, people recognition, quarantine rules and scoring remain deferred
- Repository audit confirmed Personal Librarian is not yet an application
- M13 will begin the reusable application foundation
- No source media or PersonalLibrary staging data was modified during M12

### M13 close-out evidence

- Application version: `0.1.0`
- Python package created under `src\personal_librarian`
- Central CLI implemented
- Typed TOML configuration implemented
- Central path-safety policy implemented
- Retired Z: drive rejected case-insensitively without accessing it
- Read-only and dry-run operation modes implemented
- Future action mode remains unavailable
- Structured logging and UUID run IDs implemented
- Historical M5 PowerShell script protected by an immediate retired-script fail-fast guard
- Standard automated validation added with 18 tests
- Independent validation: 18 / 18 tests passed
- CLI `version` smoke check passed
- CLI `doctor` checks passed
- No catalogue, database, media scanner, canonical selection, quarantine or file-changing workflow was introduced

### M14 close-out evidence

- SQLite catalogue implemented with versioned migrations
- Current schema version: 2
- Persistent entities include sources, batches, physical instances, content identities, hash observations, analysis runs, similarity relationships and decision history
- M9, M10 and M11 evidence importers implemented
- Importers are deterministic, transactional and idempotent
- M9 reconciliation: 69,444 rows and 122,312,861,984 bytes - MATCH
- M10 reconciliation: 69,444 valid SHA-256 rows, 56,127 content identities, 7,707 exact groups, 21,024 memberships - MATCH
- M11 reconciliation: 54,839 unique contents, 9,403 similarity pairs, 5,067 groups, 11,325 grouped contents - MATCH
- M9/M10 linkage retained 4,082 ambiguous observations as intentionally unlinked rather than forcing unsafe matches
- Unicode/raw-path evidence is preserved separately from comparison keys
- Exact identity and perceptual similarity remain separate concepts
- Temporary real-evidence validation catalogue passed `PRAGMA integrity_check`
- `PRAGMA foreign_key_check` reported 0 violations
- Real evidence re-import was idempotent
- Full automated suite passed: 41 / 41 tests
- No production catalogue location has yet been chosen
- No media was moved, renamed, deleted, quarantined or assigned canonical status
- Close-out record: `docs\M14_SQLITE_CATALOGUE.md`
- Implementation commit: `319f846 M14: add SQLite catalogue and evidence import`

- Close-out record: `docs\M13_APPLICATION_FOUNDATION.md`
- Implementation commit: `bf23098 M13: add application foundation and safety boundaries`

Later stages will address catalogue persistence, reproducible evidence pipelines, metadata, local AI, specialist library applications and approved custody-changing workflows.

## 16. Future architecture

The eventual server/NAS is intended to become the durable Personal Library home.

Potential specialist applications remain:

- Immich for photos/videos
- Paperless-ngx for documents
- Linkwarden for links
- Markdown for notes
- Ollama or equivalent local AI

Personal Librarian remains the connective catalogue and safety/orchestration layer rather than replacing every specialist application.

### M15 close-out evidence

- Source-controlled reproducible inventory pipeline implemented
- Source-controlled streaming SHA-256 pipeline implemented
- Media-extension policy frozen as `m9-media-extensions-v1`
- Pipeline is read-only against media and records results directly in the SQLite catalogue
- Persistent job checkpoints support interruption-safe resume and deterministic reruns
- SHA-256 reuse requires the same physical instance, byte size, nanosecond mtime and a prior successful M15 observation
- Changed size or modified time forces re-hashing
- Files are statted before and after hashing; changed-during-read digests are discarded
- Existing imported M10 hashes are not silently treated as M15 state-qualified cache entries
- Exact-duplicate derivation remains informational and does not trigger deletion or canonical selection
- Unicode paths are handled with Python-native filesystem APIs; raw paths remain distinct from comparison keys
- M15-specific tests passed: 11, with 1 host-capability long-path skip
- Full automated suite passed: 52, with 1 host-capability skip
- Real-media pilot: 5 files / 20,942,861 bytes / 5 SHA-256 successes / 5 of 5 matched verified M10 digests
- Independent reuse run reused 5 of 5 verified hashes
- M9 reconciliation matched 69,444 rows and 122,312,861,984 bytes
- M10 reconciliation matched 69,444 hashes, 56,127 identities, 7,707 exact groups, 21,024 memberships, 13,317 redundant copies and 25,488,473,284 informational reclaimable bytes
- SQLite integrity check passed and foreign-key violations were 0
- No full 122 GB re-hash was required; reproducibility was validated with a bounded real-media pilot plus verified full baseline reconciliation
- No media was moved, renamed, deleted, quarantined or assigned canonical status
- Close-out record: `docs\M15_REPRODUCIBLE_INVENTORY_HASH_PIPELINE.md`
- Implementation commit: `63cf01a M15: add reproducible inventory and SHA-256 pipeline`

### M16 close-out evidence

- Source-controlled reproducible pHash/dHash analysis implemented
- Runtime dependencies kept to Pillow and NumPy; no ImageHash, SciPy, PyWavelets, GPU, facial recognition or semantic-AI dependency
- pHash algorithm version: `m16-imagehash-compatible-v1:phash-8x8-hf4-lanczos`
- dHash algorithm version: `m16-imagehash-compatible-v1:dhash-8x8-horizontal-lanczos`
- Perceptual analysis runs once per exact SHA-256 content identity using one deterministic readable physical representation
- Chosen physical representation and represented-copy count are retained as provenance
- Perceptual-hash reuse requires the same SHA-256 identity and exact algorithm version
- Approved similarity rule reproduced exactly: pHash distance <= 4 AND dHash distance <= 4
- Similarity relationships preserve separate pHash/dHash distances and never merge exact content identities
- Deterministic BK-tree search and connected-component review grouping implemented
- Groups over 20 are flagged large low-confidence; groups over 50 receive a separate very-large low-confidence tier
- Hashing, relationship analysis and grouping support checkpoint/resume, idempotency and configuration/version isolation
- Full automated suite passed: 58 tests, with 1 host-capability long-path skip
- Real pilot: 20 identities, 20/20 pHash successes, 20/20 dHash successes and 40/40 generated values matched verified M11 evidence
- Independent reuse run reused 20/20 identities
- Historical M11 reconciliation matched 54,839 identities, 64,569 represented copies, 9,403 pairs, 5,067 groups, 11,325 grouped contents, largest group 135, 12 groups over 20 and 1 group over 50
- SQLite integrity check passed and foreign-key violations were 0
- Temporary M16 validation catalogue was removed after validation
- No full 54,839-content perceptual rehash was required; reproducibility was established through bounded real-data comparison plus verified historical reconciliation
- All similarity results remain review-only
- No media was moved, renamed, deleted, quarantined or assigned canonical status
- Close-out record: `docs\M16_REPRODUCIBLE_NEAR_DUPLICATE_ANALYSIS.md`
- Implementation commit: `d048180 M16: add reproducible near-duplicate analysis`

### M17 close-out evidence

- Deterministic catalogue-driven review queues implemented for exact-duplicate and near-duplicate evidence
- Exact review context is the stable SHA-256 content identity with multiple physical instances
- Near-duplicate review context is the specific similarity group, preserving identities, relationship evidence and large-group flags
- Separate `archival` and `display_export` canonical scopes are supported
- The two canonical scopes may approve the same or different physical instances
- Every canonical nomination still requires explicit owner approval
- Nomination alone never creates an approved canonical state
- Owner workflow supports nominate, approve, reject, supersede and abstain events
- Decision history remains append-only; UPDATE and DELETE remain blocked
- Current decision state is derived deterministically from immutable event history rather than stored as mutable truth
- One current approval per review context and canonical scope is enforced
- Replacement approval requires explicit supersession of the exact prior approval
- Abstention creates no winner and does not imply rejection
- Review queues support deterministic filtering, pagination and evidence summaries without rescanning media
- CLI supports exact/similar review plus nomination, approval, rejection, supersession, abstention, current state and history
- Review/current/history outputs support machine-readable JSON while SQLite remains authoritative
- Full automated suite passed: 65 tests, with 1 existing Windows long-path capability skip
- Temporary real-evidence validation exposed 7,707 exact review contexts and 5,067 near-duplicate review contexts
- Real validation exercised pending nomination, approval, supersession, independent canonical scopes, rejection, abstention and explicit approval withdrawal
- Historical catalogue counts remained unchanged at 56,127 content identities, 7,707 exact groups and 5,067 similarity groups
- SQLite integrity check passed and foreign-key violations were 0
- Temporary M17 validation catalogue was removed after validation
- No automatic scoring or canonical nomination was introduced
- No media was copied, moved, renamed, deleted, quarantined or modified
- Close-out record: `docs\M17_REVIEW_CANONICAL_DECISIONS.md`
- Implementation commit: `3fa60a1 M17: add review and canonical decision workflow`

### M18 close-out evidence

- Deterministic, auditable physical-action planning implemented without enabling execution
- SQLite schema version 6 adds immutable action plans, plan items, preflight results and action-plan events
- Versioned planning policies exist for copy, move, rename and exact-duplicate quarantine
- No catch-all cleanup policy and no delete policy were introduced
- Plan creation requires the current effective owner-approved M17 decision
- Pending, rejected, abstained and superseded decisions cannot authorise a plan
- Plans snapshot decision provenance, catalogue evidence, source state, destination, policy/version, byte size and SHA-256 identity
- Identical inputs reproduce the same plan/item identity; changed evidence produces a new snapshot
- Preflight checks source identity, size, modified time, SHA-256 evidence, decision currency, path safety and retired-drive policy
- Explicit destination roots are required; no permanent production library location is assumed
- Destination preflight checks existing conflicts, case/Unicode collisions, planned-item collisions and no-overwrite policy
- Windows reparse/junction/symlink destination handling fails closed on boundary escape, retired targets or uncertainty
- Free-space planning reports PASS, FAIL or UNKNOWN with a configurable safety margin
- Quarantine plans preserve original location, physical instance, content identity, SHA-256, planned quarantine location, decision provenance and restore context
- Changed decision/evidence invalidates or stales an existing plan rather than silently updating it
- CLI supports plan create/list/show/preflight/report/invalidate
- There is no execution CLI command
- Dry-run reports explicitly state `NO FILESYSTEM CHANGES WERE PERFORMED`
- Targeted M18 tests passed: 10 / 10
- Full automated suite passed: 75 tests, with 1 existing Windows long-path capability skip
- Bounded real validation used one verified exact-duplicate context and exercised PASS -> deliberate conflict FAIL -> approval supersession STALE
- SQLite integrity check passed and foreign-key violations were 0
- Three preflight results and four plan events remained auditable after validation
- No copy, move, rename, quarantine or delete operation was executed
- Temporary validation artefacts were removed after validation
- Close-out record: `docs\M18_SAFE_ACTION_PLANNING_DRY_RUN.md`
- Implementation commit: `da83d97 M18: add safe action planning and dry-run`

### M19 close-out evidence

- First narrowly scoped real filesystem mutation capability implemented
- Execution is limited to `exact-duplicate-quarantine-v1`; there is no generic action executor
- Quarantine requires explicit `--confirm-quarantine`; restore requires explicit `--confirm-restore`
- Fresh plan, preflight, owner-decision, canonical-state, source-state, destination-safety and free-space checks run immediately before mutation
- Source SHA-256 is streamed and verified before quarantine
- Quarantined destination SHA-256 is streamed and verified before success may be recorded
- Post-move verification failure results in `recovery_required`, never false success
- Quarantine and restore are same-volume only and use rename/move semantics
- Cross-volume execution fails closed; no copy-delete fallback exists
- Durable append-only execution, execution-event, quarantine and physical-location history is retained
- Reconciliation classifies interrupted states without moving or deleting files
- Restore is allowed only to the exact original safe path with no overwrite
- Exact content identity remains unchanged through quarantine and restore
- The currently approved canonical physical instance cannot be quarantined
- Similarity/near-duplicate evidence cannot authorise M19 quarantine
- CLI supports quarantine execute/status/history/reconcile/restore
- No generic plan-execute, delete, overwrite or force command exists
- Targeted M19 tests passed: 11 / 11
- Full automated suite passed: 86 tests, with 1 existing Windows long-path capability skip
- One bounded real Google Photos exact duplicate was successfully quarantined and restored
- Real test file size: 4,342,370 bytes
- Real test SHA-256: `3AFD2949D666603944A87929F341F909320A4D4DE3134B6B396A151A95F5BC09`
- SHA-256 matched catalogue evidence, the second exact copy, quarantine destination and restored source
- The validation canonical OneDrive copy remained present, byte-identical and untouched
- SQLite integrity check passed and foreign-key violations were 0
- Schema version after M19: 7
- Temporary validation catalogue and quarantine root were removed after validation
- General copy/move/rename execution, delete, overwrite, bulk quarantine, near-duplicate cleanup and automatic canonical selection remain unavailable
- Close-out record: `docs\M19_REVERSIBLE_QUARANTINE_EXECUTION.md`
- Implementation commit: `aa83431 M19: add reversible quarantine execution`

### M20 close-out evidence

- Production application-data layout implemented with an explicit owner-supplied root
- No permanent drive or application-data location is hard-coded
- Production catalogue identity metadata includes catalogue UUID, creation time, schema/application provenance, role and application-data-root fingerprint
- Schema version after M20: 8
- Production bootstrap stages into a temporary in-root catalogue and promotes only after reconciliation and integrity validation
- Existing production catalogues are never silently overwritten
- Verified M9/M10/M11 bootstrap matched all historical baselines
- Temporary full production catalogue size: 271,785,984 bytes
- Full bootstrap completed in approximately 65.160 seconds
- SQLite production settings use foreign keys ON, WAL journalling, synchronous FULL and a 5-second busy timeout
- Live catalogue backups use the SQLite backup API rather than raw copying of an active database
- Accepted backups include versioned JSON manifests with catalogue identity, schema, sizes, SHA-256 and integrity results
- Two full validation backups were created and verified successfully
- Validation backup size: 271,785,984 bytes each
- Validation backup SHA-256: `4a1dec1d14c4a19bbb67990807d13941a280b6d682efdae2dc03fc23f1a549e9`
- Retention is report-only and defaults to showing the latest 10 accepted backups; M20 does not prune files
- Production health reporting exposes catalogue identity, schema, SQLite health, backups, decision/action counts and unresolved recovery states
- Catalogue recovery requires explicit `--confirm-restore-catalogue`
- Recovery verifies candidate identity/hash/integrity, creates a verified pre-recovery backup, stages restoration and preserves the previous catalogue
- External recovery history survives catalogue replacement
- Synthetic recovery successfully restored a prior catalogue state and removed the post-backup marker as expected
- Final validation health status: PASS
- All SQLite integrity checks returned `ok`
- All foreign-key checks returned zero violations
- Focused M20/catalogue tests passed: 30 / 30
- Full automated suite passed: 98 tests, with 1 existing Windows long-path capability skip
- Local catalogue snapshots are explicitly not treated as independent/off-site disaster-recovery backups
- No permanent production application-data root was selected during M20
- No media was scanned, hashed, copied, moved, renamed, quarantined or deleted during M20
- Broad physical execution remains unavailable
- Close-out record: `docs\M20_PRODUCTION_CATALOGUE_BACKUP_RECOVERY.md`
- Implementation commit: `3c5e7fd M20: add production catalogue backup and recovery foundation`

### M21 close-out evidence

- Owner-approved production application-data root established at `<data-root>`
- Production catalogue deployed at `<data-root>\catalogue\personal_librarian.sqlite3`
- Production catalogue UUID: `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Production role confirmed
- Production schema version: 8
- Production catalogue size: 271,785,984 bytes
- Production bootstrap completed in approximately 46.637 seconds
- M9 reconciliation matched 69,444 rows and 122,312,861,984 bytes with all source totals correct
- M10 reconciliation matched 69,444 hashes, 56,127 identities, 7,707 groups, 21,024 memberships and 13,317 redundant copies
- M11 reconciliation matched 54,839 analysed identities, 64,569 represented copies, 9,403 relationships, 5,067 groups and 11,325 grouped contents
- Final production health status: PASS
- SQLite integrity check returned `ok`
- Foreign-key violations: 0
- SQLite production journal mode: WAL
- Unresolved recovery-required executions: 0
- Production decision events, action plans, executions and quarantine records remain 0
- Health now warns when the most recent accepted backup is older than seven days
- Two real production catalogue backups were created and accepted
- Production backup IDs: `acd9709c-8308-4c64-843a-27c2f77b2cdb` and `db3c3902-dee3-412b-9b88-ddfd2aa042e2`
- Each production backup size: 271,785,984 bytes
- Both production backups SHA-256: `f3572f8bd42611781a1360168bd44508a63b3134e4790ec0a8e394f5ef474b78`
- Both backups independently passed integrity and foreign-key verification
- One real production backup was successfully staged as a recovery candidate without replacing production
- Staged recovery identity, schema and catalogue counts matched production
- Production database remained unchanged throughout recovery-readiness validation
- Static verification now uses immutable SQLite reads and no longer creates unnecessary WAL/SHM sidecars
- Production data is independent of the Git repository location
- Current CLI remains an editable install from `H:\PersonalLibrarian`; this is a packaging limitation, not a production-data dependency
- Production and local backup snapshots currently reside on the same physical H: HDD
- Current local backups are operational recovery snapshots, not independent hardware or disaster-recovery backups
- Full automated suite passed: 99 tests, with 1 existing Windows long-path capability skip
- No production owner decisions, plans, quarantine actions or media mutations occurred during M21
- No media was scanned, hashed, copied, moved, renamed, quarantined or deleted
- Close-out record: `docs\M21_PRODUCTION_DEPLOYMENT_OPERATIONAL_READINESS.md`
- Implementation commit: `d307085 M21: deploy production catalogue and operational readiness`

### M22 close-out evidence

- First independent hardware catalogue backup established at `<backup-root>`
- Independent backup target is physically separate from production storage
- Production H: device: `WDC WD1002FBYS-18W8B1`, disk 2, SATA HDD
- Independent X: device: `KINGSTON SA400S37240G`, disk 1, SATA SSD
- Independent backup layout: `<backup-root>\backups\catalogue\`
- Backup manifest format advanced to version 2 while retaining version 1 compatibility
- Backup storage classes distinguish `operational-local` from `independent-local`
- Independent backup ID: `7883e7cb-7359-4bb7-898d-b9497829d0bf`
- Independent backup file: `catalogue-20260823T105007236536Z-7883e7cb-7359-4bb7-898d-b9497829d0bf.sqlite3`
- Independent backup size: 271,785,984 bytes
- Independent backup SHA-256: `f3572f8bd42611781a1360168bd44508a63b3134e4790ec0a8e394f5ef474b78`
- Production catalogue UUID matched: `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Production schema version matched: 8
- Independent backup integrity check returned `ok`
- Independent backup foreign-key violations: 0
- Verified catalogue counts: 69,444 inventory observations, 69,444 physical instances, 56,127 content identities, 7,707 exact groups, 9,403 similarity relationships and 5,067 similarity groups
- Independent backup readiness status: PASS
- Independent-backup freshness warning threshold: seven days
- Existing H: operational backups remain preserved
- One independent X: backup was staged successfully as a recovery candidate
- Staged recovery UUID, schema, counts, integrity and foreign keys matched production
- Production catalogue SHA-256 remained unchanged during recovery-readiness validation
- H:-loss recovery procedure is documented and owner-controlled
- X: is classified as a separate-device local disaster-recovery copy, not off-site or NAS protection
- Targeted production tests passed: 18 / 18
- Full automated suite passed: 104 tests, with 1 existing host long-path capability skip
- NAS/server was not contacted or used
- No media was scanned, hashed, copied, moved, renamed, quarantined or deleted during M22
- No production decisions, plans or executions were created
- Broad physical execution and delete remain unavailable
- Close-out record: `docs\M22_INDEPENDENT_BACKUP_DR_READINESS.md`
- Implementation commit: `9749804 M22: add independent backup and DR readiness`

### M23 close-out evidence

- First user-facing Personal Librarian desktop shell implemented with PySide6 / Qt for Python
- Desktop runs in the existing Python process with no browser frontend, local web server or second backend
- UI code delegates catalogue, review, decision, planning, backup and safety behavior to existing application services
- Desktop launch supports explicit production application-data root and independent-backup root
- Navigation includes Overview, Exact Duplicates, Similar Images, Decisions, Plans, Quarantine and Backups / Recovery
- Overview shows production health, catalogue identity/schema, catalogue counts, backup readiness and operational state without scanning media
- Exact-duplicate review provides paginated group browsing, status filters, lazy detail loading and physical-instance evidence without automatic ranking
- Near-duplicate review preserves the distinction between similarity and exact identity and exposes pHash/dHash evidence plus large-group warnings
- Read-only JPEG, PNG, GIF first-frame and WebP previews are implemented with bounded decoding and background Qt workers
- Derived thumbnail cache is stored under production application state and remains rebuildable/non-authoritative
- Greek/Unicode paths, invalid images and zero-byte files are handled without crashing the desktop application
- M17 canonical-decision workflow is exposed with separate nominate and approve actions; archival and display/export scopes remain independent
- Every decision write requires explicit owner/actor input and confirmation
- Append-only decision history is visible with no edit/delete controls
- M18 Plans, M19 Quarantine and M20-M22 backup/recovery state remain read-only in the desktop UI
- No physical execution, restore, delete or production-catalogue recovery controls were added to the GUI
- Health/database failure states fail closed for decision writes while safe diagnostic visibility remains available
- Catalogue queries, health checks, detail loading and thumbnail decoding run outside the Qt UI thread where appropriate
- Exact and similarity review use bounded pagination and lazy detail loading
- M23-specific tests passed: 9 / 9
- Focused M17-M23 regression tests passed: 55 / 55
- Full automated suite passed: 113 tests, with 1 existing Windows long-path capability skip
- Real production desktop smoke loaded all sections successfully
- Exact production smoke loaded 50 of 7,707 groups; first selected group had 3 representations
- Similar production smoke loaded 50 of 5,067 groups; first selected group had 2 contents and 1 relationship
- Production health displayed PASS and independent disaster-recovery readiness displayed PASS
- Three distinct real images decoded successfully and five preview slots were populated during bounded smoke validation
- Checked source sizes and mtimes were unchanged
- No real production owner decisions were created; production decision-event count remains 0
- No media was scanned, hashed, copied, moved, renamed, quarantined, restored or deleted
- Production catalogue SHA-256 remained unchanged during smoke validation
- Close-out record: `docs\M23_DESKTOP_REVIEW_INTERFACE_FOUNDATION.md`
- Implementation commit: `a38c683 M23: add desktop review interface foundation`

### M24 close-out evidence

- Desktop usability improvements implemented over the existing PySide6 architecture
- Exact-duplicate review now includes richer comparison data, clearer canonical-state badges, copy-path/hash controls and keyboard navigation
- Near-duplicate review retains exact/similarity separation while providing larger previews, relationship evidence and large-group filtering
- Read-only image detail viewer supports zoom, fit-to-window, 100% view and panning
- Metadata comparison exposes existing source/path/size/time/hash/content/canonical evidence without inventing quality scoring or date precedence
- Versioned harmless UI preferences are stored under production application state rather than repository or catalogue truth
- Keyboard navigation and accessibility labels/tooltips were added for normal review workflows
- Exact filters support All, Pending, Decided and Abstained
- Similar filters support All, Pending, Decided and Large groups
- Nomination and approval remain separate explicit owner actions
- PyInstaller was added as an optional build dependency rather than normal runtime dependency
- Windows one-folder packaging was implemented with source-controlled build specification and PowerShell build script
- Standalone executable: `PersonalLibrarian.exe`
- Validation distribution contained 221 files and measured 164,785,584 bytes
- Packaged application does not require Python, editable installation, repository presence or repository working directory
- Production and independent-backup roots remain external and are not embedded in the packaged application
- Startup configuration supports explicit owner-selected roots and never bootstraps a catalogue silently
- Packaged application retained all M13-M23 safety boundaries
- No generic execute, delete, quarantine, restore or production-recovery controls were added to the desktop UI
- Focused M24/M23/review tests passed: 24 / 24
- Full automated suite passed: 121 tests, with 1 existing Windows long-path capability skip
- Normal desktop smoke loaded all operational sections successfully
- Packaged production smoke exited successfully and loaded 50 of 7,707 exact groups and 50 of 5,067 similarity groups
- Production health remained PASS and independent DR readiness remained PASS
- Real image preview and zoom behavior worked through the frozen application without modifying source size or mtime
- Production decision events, plans, executions, execution events, recovery-required executions and quarantine records remained unchanged at zero
- Production catalogue SHA-256 remained unchanged
- No media was scanned, hashed, copied, moved, renamed, quarantined, restored, overwritten or deleted
- Build and distribution outputs remain ignored and are not committed to Git
- Current distribution is unsigned, has no installer/updater, uses one-folder deployment and has no custom icon
- Close-out record: `docs\M24_DESKTOP_USABILITY_WINDOWS_PACKAGING.md`
- Implementation commit: `3ec5d09 M24: improve desktop usability and add Windows packaging`

### M25 close-out evidence

- Release candidate engineering completed for Personal Librarian 0.1.0 release-candidate series
- First technical release candidate RC1 was built, checksummed and validated as a portable one-folder Windows distribution
- Owner usability testing began against the real production catalogue
- Owner pass discovered a release-blocking stale asynchronous preview-binding defect in RC1
- Exact duplicate group 41904 displayed unrelated preview content despite identical SHA-256 evidence
- Catalogue and source media were verified correct; defect was isolated to desktop asynchronous preview/detail binding
- Preview requests were hardened with context, generation, physical-instance ID and source-path identity checks
- Stale detail, thumbnail and enlarged-preview callbacks are now discarded
- Per-instance thumbnail cache evidence was strengthened and cache version advanced
- Regression coverage was added for out-of-order completion, stale-group results, refresh/reselection and preview identity alignment
- RC2 superseded RC1 and passed focused, full-suite and packaged validation
- RC2 exact group 41904 showed all three physical representations correctly aligned to identical rendered content
- Additional real exact groups remained correctly aligned during owner testing
- Similar Images preview binding remained correct during owner testing
- Owner manually reviewed Overview, Exact Duplicates, Similar Images, Decision History, Plans, Quarantine and Backups / Recovery
- Decision nomination confirmation was inspected and cancelled; no production owner decision was written
- Production decision events, plans, executions, recovery-required executions and quarantine records remained unchanged at zero
- No media was scanned, re-hashed, moved, renamed, quarantined, restored, overwritten or deleted
- Production catalogue SHA-256 remained unchanged during RC2 technical validation
- Production health remained PASS and independent DR readiness remained PASS
- Owner usability findings were recorded in `docs\M25_OWNER_USABILITY_FEEDBACK.md`
- Remaining issues are non-blocking desktop UX refinements: layout density, technical terminology, path/hash prominence, preview emphasis, decision-dialog wording, similarity explanation and Overview presentation
- RC1 is retired from owner testing
- Accepted release candidate: 0.1.0rc2
- Accepted RC2 fix commit: `8fb254e M25: fix stale preview binding and release RC2`

### M26 close-out evidence

- Desktop UX refinement completed from the real M25 owner usability findings
- Exact Duplicates now uses available width effectively and prioritises owner-facing evidence
- Exact group state is separated into clear Archival, Display and Review status fields
- Exact groups now visibly explain that verified SHA-256 matches are byte-for-byte identical
- Physical-copy detail prioritises filename, source, readable size/date and canonical state while keeping IDs, hashes and paths available as secondary evidence
- Preview evidence is larger, better spaced and uses shorter owner-facing captions
- Similar Images now uses owner-facing review terminology and retains an explicit warning that similarity is not exact identity
- pHash/dHash help text explains perceptual-distance meaning without implying automatic canonical selection
- Preview viewer metadata now prioritises owner-facing information and de-emphasises technical identifiers
- Decision controls are reorganised into clearer nomination and resolution workflows while preserving separate nomination/approval events
- Decision confirmation uses human-readable wording and keeps technical identifiers secondary
- Overview is grouped into Catalogue, Library, Review, Safety / Actions and Backups sections
- Backups / Recovery prioritises class, created time, size and verification while retaining hashes/manifest evidence
- Decisions, Plans and Quarantine have explicit owner-facing empty states
- Sidebar width and navigation labels remain stable and readable across sections
- Exact and Similar table column sizing now uses available width without allowing technical fields to dominate
- Exact and Similar splitter preferences are stored independently with compatibility fallback
- Exact default group/detail split was adjusted so common three-copy groups are comfortably visible without sacrificing preview space
- RC2 stale-preview protections remain intact: context/generation/instance/path validation, stale-callback rejection, preview reset behavior and per-instance cache evidence
- Owner review of RC3 passed across Overview, Exact Duplicates, Similar Images, Decisions, Plans, Quarantine and Backups / Recovery
- Exact group 41904 showed all three physical rows and correctly bound identical previews during owner review
- Similar group 2634 showed two correctly bound visually similar but non-identical files
- No release-blocking issue remained after owner review
- Canonical local release candidate: 0.1.0rc3
- Final RC3 ZIP SHA-256: `A83818D65546CE4B109DBD777BF196439ECFA4379003277EF9BAD763CA70C324`
- Final RC3 EXE SHA-256: `14F35262CCBC2619694ED75D75F65EFB5BE254BE208EF5151461ECBCAA561E2D`
- Production health and independent disaster-recovery readiness remained PASS
- Production decision/action/quarantine counters remained unchanged at zero during validation
- No media was scanned, re-hashed, moved, renamed, quarantined, restored, overwritten or deleted
- Close-out record: `docs\M26_DESKTOP_UX_REFINEMENT.md`
- Implementation commit: `1e1c42c M26: refine desktop UX and finalise RC3`

### M27 close-out evidence

- M27 completed as a documentation-first organisation and AI-governance milestone
- Physical custody and logical organisation are now explicitly separate architectural concepts
- Future authoritative physical storage is approved as `Photos/Videos -> YYYY -> MM`
- Year is the primary owner-facing browse axis
- Semantic concepts such as event, place, people, project, topic and album do not determine authoritative physical paths
- Logical albums may contain zero, one or many content identities without duplicating physical media
- Smart albums are defined as versioned catalogue queries rather than materialised copies
- Events, places, people, tags, classifications and owner-curated collections are defined as independent catalogue dimensions
- Unknown date/location/person/topic state remains valid and must not be guessed into certainty
- Imports are approved as temporary batch-based staging with provenance, retained until verified ingestion and required backup coverage
- Scanned photographs remain Photos; document photographs/receipts/forms route conceptually to Documents
- Album presentation may use shallow hierarchy while semantic membership remains independent
- Optional future local face clustering is approved, with anonymous clustering permitted and identity assignment owner-controlled initially
- Optional external geocoding is approved only as explicit opt-in coordinate-only enrichment; image contents must not be uploaded
- AI confidence is task-specific and evidence-dependent rather than one global threshold
- AI confidence alone never grants physical authority
- Automation authority is staged from Observe through Suggest, Batch Suggest and explicitly owner-authorised reversible catalogue automation
- Any future physical move/quarantine authority requires a separate milestone and must reuse existing action/quarantine safeguards
- Destructive Level-5 authority remains unavailable
- Dumpster is a reversible logical disposition and does not mean delete
- No automatic Dumpster expiry or deletion timer is approved
- Personal Librarian is approved to eventually maintain its own managed authoritative library root
- Migration into the managed root must use copy -> verify -> backup -> owner approval before legacy-source retirement review
- AI suggestions are designed to retain model/runtime, policy version, confidence, evidence, explanation, targets and separate owner resolution
- Owner learning is defined through explicit approved/rejected examples, rules, exceptions and provenance rather than opaque autonomous memory
- Local processing remains the default for organisation and AI analysis
- Future AI work must be incremental, cached, checkpointed, pausable and resource-bounded
- Canonical choice, album membership, semantic classification, Dumpster disposition and physical custody remain separate concepts
- Exact-duplicate album membership should normally target shared content identity rather than every physical representation
- Near-duplicate identities remain separate and are never merged merely because they are visually similar
- No code, schema migration, production catalogue change, AI execution or physical media reorganisation occurred during M27
- Authoritative policy document: `docs\M27_LIBRARY_ORGANISATION_ALBUMS_AI_POLICY.md`
- Implementation commit: `953edb9 M27: define library organisation and AI suggestion policy`

### M28 close-out evidence

- Production catalogue migrated explicitly from schema 8 to schema 9
- Historical migrations 1-8 remained unchanged
- New migration `manual_logical_organisation` is deterministic and transactional
- Catalogue UUID remained unchanged at `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Physical-instance count remained 69,444
- Content-identity count remained 56,127
- Exact-duplicate group count remained 7,707
- Similarity-group count remained 5,067
- Existing decision, plan, execution, quarantine and location-event counts remained unchanged
- Manual albums are now first-class catalogue entities with stable UUID identity
- Album membership targets content identities rather than physical instances
- Exact duplicate physical representations therefore map to one logical album member
- Near-duplicate content identities remain independent
- Album lifecycle supports create, rename, archive and restore without hard delete
- Membership lifecycle supports add, remove and restore with immutable organisation history
- Organisation events preserve actor, timestamp, operation, provenance, optional reason and structured details
- Minimal manual tag/content-tag foundation was added
- Broad classification dimensions remain deferred
- Organisation mutations require an explicit actor
- CLI support added for bounded manual album lifecycle and membership operations
- No bulk wildcard organisation operations were added
- Desktop Organisation support was deliberately deferred
- No AI inference, Ollama execution, face clustering, geocoding, smart albums or physical organisation occurred
- Fresh pre-migration operational backup accepted: `cbb7f04a-a235-4524-9e31-1ba17cff89a8`
- Fresh pre-migration independent backup accepted: `91747653-6f9a-4238-84b2-4531f48a9941`
- Independent H:/X: device separation was verified before migration
- Production integrity check returned `ok`
- Foreign-key violations remained 0
- Production health remained PASS
- Independent disaster-recovery readiness remained PASS
- Post-migration M9/M10 and M11 reconciliation remained MATCH
- Production albums, memberships, tags, content tags and organisation events remained at 0 after migration
- No production seed/test organisation data was created
- Ordered catalogue path-evidence digest remained `E9BAE20EF4E17E594D2D9D5B1838CA38D56C81CE8D23BEA50A3ADEB0711816E2`
- No media was scanned, hashed, copied, moved, renamed or deleted
- Existing packaged RC3 predates schema 9 and must not be used against the migrated production catalogue until a schema-9-compatible package is built
- Close-out record: `docs\M28_CATALOGUE_ORGANISATION_SCHEMA_MANUAL_ALBUMS.md`
- Implementation commit: `ff7114f M28: add catalogue organisation and manual albums foundation`

### M29 close-out evidence

- Year-first desktop Library implemented and owner-approved; Years remain the primary browse axis
- Logical albums remain catalogue-only and do not create Windows folders
- Album create, rename, archive and restore are supported
- Album membership operates at content-identity level, so exact-duplicate physical instances resolve to one logical identity while similar-content identities remain independently organisable
- Manual tags foundation is available and organisation history remains immutable and auditable
- Collections were intentionally deferred rather than emulated on schema 9, and preferred-date authority remains deferred
- Production schema remains 9
- Production owner test created album `Christmas` with UUID `5336a05a-2148-4891-9d86-bb04a2db7e06`, 2 active logical members and 3 immutable organisation events
- Existing `Christmas.description = owner-test` is harmless pre-fix test residue and was intentionally not mutated
- Create-album description binding defect found during owner testing and fixed
- Packaged Qt6Core access-violation crash reproduced, traced to Library worker lifetime handling and fixed
- Final targeted validation passed 42 relevant tests; final RC4 clean-extraction packaged smoke passed
- Canonical RC4 ZIP: `H:\PersonalLibrarian\release\PersonalLibrarian-0.1.0rc4-win64.zip`
- Canonical RC4 ZIP size: 66,856,709 bytes; packaged files: 221; schema compatibility: 9
- Canonical RC4 ZIP SHA-256: `8A05DEC4FB68F122ED21871F052C9C91451EF722A9577EAFCE70E9220436D719`
- Canonical RC4 EXE SHA-256: `9B6CA85D0CB5AC3D912611A6426F5762F970577D1C0E6C1C4B0EBE46EC6F8A49`
- No media mutation occurred
- Implementation commit: `ae24a81 M29: add year-centred desktop organisation and finalise RC4`

### M30 production-readiness gate

- Canonical RC7 (`0.1.0rc7`) is built from base `5cc9cb6` and validated with the second preferred-date count optimisation and corrected desktop History timestamp contract; RC6 remains the previous schema-10 release, RC5 the earlier schema-10 release, and RC4 the schema-9 generation
- Fresh H operational backup `8e43788d-be27-43d6-afbb-07ee214bb72e` and X independent-local backup `8af99610-db43-4e5e-990b-33210fe1028b` are accepted and verified
- A verified production clone migrated 9 to 10 with preserved identity/domain state and passed the bounded deterministic date-pipeline and packaged-desktop checks
- At the readiness checkpoint production remained unchanged at schema 9 with no date evidence, preferred dates, Collections or Collection memberships
- The separately approved production migration is recorded below

### M30 production schema-10 migration

- The owner explicitly approved the production structure-only migration from schema 9 to schema 10
- Migration `preferred_date_evidence_and_collections` applied at `2026-08-26T11:11:18.485Z`
- Catalogue UUID remained `613affe5-a00b-49bc-9ad9-99b95adeec33`; all legacy counts, Christmas, and the three existing organisation events were preserved exactly
- Production date evidence, preferred dates, preferred basis, Collections, Collection memberships, and date-pipeline job rows remain zero
- First schema-10 recovery points: H operational `2367efcd-4c55-4b93-9141-f3766b5ac663`; X independent-local `ea42f315-2cad-47ad-b16c-3ebd70996b8b`; both accepted, with X DR health PASS
- RC7 is the canonical schema-10 production desktop candidate; RC6 and RC5 are preserved as its schema-10 predecessors and RC4 is retained as historical schema-9 release and recovery evidence only
- M30 remains open; production preferred-date evidence population is the next separate explicit owner gate

### M30 production preferred-date Batch 1

- The owner explicitly approved the first bounded production preferred-date population batch
- Job `m30-production-preferred-date-batch1-v1` processed exactly physical-instance IDs 1 through 5000 under `m30c-v1` / `preferred-date-policy-v1`
- The batch created 5,373 catalogue-only evidence rows: 5,000 filesystem-modified and 373 allow-listed filename-derived; no media bytes were read by the pipeline
- Final projection for the 4,571 represented identities is 373 resolved and 4,198 Unknown/`weak_evidence_only`, with no needs-review, conflict, or job errors
- Same-job checkpoint rerun was idempotent with zero database/event-count delta
- Production remains integrity/FK clean; legacy counts and Christmas are preserved; Collections remain empty
- Populated-state recovery points: H `f8adccdb-74d7-4f1b-9ad3-23b4121c3fe0`; X `cd2373fb-cbfe-4aeb-8b00-f1cca14fa4dc`; both accepted, with X DR health PASS
- M30 remains open; Batch 2 requires separate approval and a reviewed deterministic next-window selection because the current pipeline always selects the first 5,000 physical IDs

### M30 production preferred-date population completion

- The owner-approved initial catalogue-only population completed at authoritative `end_of_catalogue=true` in Batch 14; final cursor and physical-instance ID are 69,444
- All 69,444 eligible physical instances have exactly one checkpoint across 14 non-overlapping jobs; missing, duplicate, excess, invalid, and overlapping checkpoints are zero
- Final cumulative state: 80,381 date-evidence rows, 56,127 preferred projections, 64,977 basis rows, 14 jobs, 69,444 job items, and 56,136 organisation events
- Final preferred state: 8,843 resolved (15.755%), 47,284 Unknown/weak-evidence-only (84.245%), and zero needs review
- Final Year shelves: 2012 14; 2013 30; 2014 258; 2015 290; 2016 789; 2017 2,658; 2018 686; 2019 1,069; 2020 3; 2021 19; 2022 244; 2023 763; 2024 604; 2025 216; 2026 1,200; Unknown Date 47,284
- Canonical corrected RC7 remains the schema-10 production desktop; fresh frozen production smoke passed all eight main sections, production/DR health, Year/Unknown browsing, Exact/Similar, backup/recovery, History validation, and read-only preview with source unchanged
- Nine frozen final timing runs measured combined Library refresh at 45.564–58.696 ms, median 49.840 ms; every run passed the 160-ms continuation/release gate
- Final production integrity is `ok`, foreign keys zero, and catalogue UUID remains `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Legacy counts remain physical 69,444; identities 56,127; exact groups 7,707; similarity groups 5,067; Album 1 with 2 active memberships; Tags/content tags 0; Collections/memberships 0
- Christmas remains active with UUID `5336a05a-2148-4891-9d86-bb04a2db7e06`, description `owner-test`, two active members, and its exact original three events
- Final accepted backups: H operational `00b11a07-fef8-4c2d-8cc9-bc6d5e42aa7c`; X independent-local `e581b8c3-b696-4cc4-8e6b-9ab02994047f`; X physical independence and DR health are `PASS`
- The pipeline remained catalogue-only: no media-byte/EXIF/video/sidecar extraction, media mutation, rehash, similarity generation, AI/Ollama, Z, NAS, or server access occurred; normal RC7 preview alone read media read-only
- M30 was formally closed on 27 August 2026 with no remaining defined-scope engineering or production-data blocker
- Richer trusted capture-date extraction, semantic/AI analysis, and physical media reorganisation remain future work and do not block this completed M30 scope
- Future date work includes EXIF DateTimeOriginal, video capture timestamps, trusted Google Photos metadata/sidecars, and approved OneDrive capture metadata only under a separately approved milestone
- Close-out record: `docs\M30_PREFERRED_DATE_COLLECTIONS.md`
- Completed implementation and production-state commit: `47fcfef M30: complete production preferred-date population`

## 17. Current immediate objective

1. M30 is complete; preserve its catalogue, release, recovery, audit, authority and media-safety evidence.
2. Perform a separate GitHub publication-safety review only with explicit owner approval; do not create a remote, publish, push, tag or release as part of M30 close-out.
3. Do not begin another milestone or richer metadata, semantic/AI or physical-media work without separate scope and owner approval.

## 18. Permanent safety statement

The former Z: device is not trusted storage.

Do not use Z: as an authoritative source, working library, backup target, Git repository or staging destination.

Where recoverable data exists in an independent source such as OneDrive, reacquire it from that source rather than relying on Z:.

## Recovery provenance

The living Project Truth was reconstructed as Version 0.7 on 17 August 2026 using known milestone records, surviving project files, surviving Git metadata and observed recovery evidence.

It is authoritative for work from this recovery point onward.
