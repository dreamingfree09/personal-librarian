# M23 - Desktop Review Interface Foundation

Date: 23 August 2026

Status: implementation and bounded production smoke complete; pending owner close-out

## Scope and technology

M23 adds the first local desktop interface for Personal Librarian using PySide6 / Qt
for Python. It runs in the existing Python process and calls the established catalogue,
review, decision, planning, quarantine, production-health, and backup services. It does
not introduce a web server, second backend, browser frontend, or duplicated domain
rules.

The interface is review/visibility/owner-decision software. Delete, generic
copy/move/rename, automatic canonical selection, bulk quarantine, GUI restore,
production recovery, scanning, and hashing remain unavailable.

## Launch

Both launch paths require an explicit application-data root; no H: default is embedded
in application code:

```powershell
personal-librarian desktop `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'

python -m personal_librarian.desktop `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

The optional independent root enables X: disaster-recovery visibility. No production
catalogue is bootstrapped when the supplied root is missing.

## Architecture

The desktop package contains:

- `app.py`: QApplication and main-window startup;
- `main_window.py`: presentation, navigation, bounded tables, confirmation dialogs,
  and Qt workers;
- `services.py`: the single desktop facade over existing backend services and the few
  centralized read-only dashboard count queries; and
- `thumbnails.py`: safe bounded preview generation and QThreadPool tasks.

Widgets do not contain catalogue SQL. Canonical writes call the existing append-only
M17 decision functions. Plans, quarantine, and backup views call their existing read
services.

## Navigation and safety signalling

The conventional left navigation contains:

1. Overview
2. Exact Duplicates
3. Similar Images
4. Decisions
5. Plans
6. Quarantine
7. Backups / Recovery

The header reports catalogue health and schema. The status bar distinguishes read-only
views, confirmed owner catalogue decisions, and unavailable physical actions. Styling
uses standard Qt controls with a small restrained stylesheet.

## Overview

Overview obtains production health without scanning media and shows catalogue UUID,
schema, size, physical/content counts, exact/similar group counts, operational and
independent backup state, recovery-required executions, decisions, plans, and
quarantine records.

Production and disaster-recovery readiness remain separate. A disconnected X: device
does not make an otherwise healthy production catalogue unusable.

## Exact duplicate review

The exact screen uses M17's deterministic review queue with a default page size of 50,
status filters, previous/next controls, and lazy detail loading. The group table shows
content identity, copy count, sources, size, canonical-scope state, and review status.

Detail shows physical instance/content IDs, source, raw/current representation, type,
size, timestamps, full SHA-256, and per-scope nominated/approved state. Table values can
be copied by double-click. Preview loading is limited to the first twelve physical
representations in the selected group.

No copy is ranked or preselected as best.

## Similar-image review

The similar screen uses M16/M17 deterministic similarity groups, separately labelled
from exact duplicates. It shows member count, review tier, pHash/dHash ranges, review
status, and explicit large/very-large low-confidence warnings. Lazy detail retains
distinct content identities, relationships, and physical representations.

Similarity alone offers no canonical or physical-action control.

## Thumbnail service and cache

Initial preview formats are JPEG, PNG, GIF first frame, and WebP. Source paths pass the
central read-safety policy before filesystem access; the retired Z: drive is rejected
before opening. Pillow opens sources read-only, rejects images over 50 million pixels,
applies orientation, converts a bounded frame, and produces at most a 192x192 PNG.
Decode errors, zero-byte files, missing media, and unsupported types return a placeholder
state rather than crashing a page.

Decoding runs through modest QThreadPool work items, not the UI thread. Derived previews
are stored under:

`<app-data-root>\state\thumbnails\`

Cache keys contain the exact content identity, thumbnail algorithm version, and target
dimensions. The cache is non-authoritative, rebuildable application state and is never
written beside originals.

## Owner canonical decisions

The exact-detail screen exposes separate actions for:

- nominate selected physical instance;
- approve a pending nomination;
- reject a pending nomination;
- supersede a current approval with a separately pending nomination; and
- abstain/withdraw where valid.

Archival and display/export scopes remain independent. Every write requires a visible,
explicit actor and a confirmation dialog that identifies the action, scope, and actor.
Nomination never implies approval, and backend stale/context validation remains
authoritative. Decision writes fail closed when catalogue integrity/foreign-key health
does not permit them.

The Decisions section renders append-only history with timestamp, action, actor,
context, target, scope, reason, and related event. It has no edit/delete controls.

## Plans, quarantine, backups, and recovery

Plans are read-only and show identifiers, policy, context, status, item/byte totals,
and destination. Selecting a plan loads its items, decision provenance, and complete
preflight history into a read-only detail panel. There is no execute control.

Quarantine is read-only and shows execution/result state, original and quarantine paths,
SHA-256, and failures/recovery state. Selection loads event and location history. Execute,
restore, and reconciliation remain CLI-only.

Backups / Recovery shows H: operational and X: independent-local backups, including
class, age/timestamp, size, hash, manifest, and verification state. Production catalogue
restore is unavailable in the GUI.

## Responsiveness, pagination, and state

Health, catalogue queries, detail loading, and image decoding run outside the Qt UI
thread. Review queues return at most 50 groups per page, children load only after
selection, and previews are capped. The application persists only harmless window size
and last-section preferences through QSettings. SQLite remains the sole authority for
decisions.

## Degraded and error states

- Missing catalogue: show bootstrap-required guidance; create nothing.
- Health WARN with safe integrity: retain review visibility and owner decisions.
- Integrity/foreign-key unsafe or FAIL: disable/fail closed for decision writes.
- Missing physical media or preview decode failure: show a local placeholder.
- Disconnected independent backup: show DR warning while retaining catalogue use.
- Backend stale-decision or validation error: show the backend error without recording an
  invalid event.

One failed worker or preview does not terminate the desktop application.

## Real production smoke

The Qt shell was launched offscreen against the approved `<data-root>` with the approved
X: root for a bounded, non-mutating smoke:

- Overview loaded production health `PASS`, UUID
  `613affe5-a00b-49bc-9ad9-99b95adeec33`, schema 8, and all baseline counts.
- Exact review loaded 50 of 7,707 groups; the first detail contained three physical
  representations.
- Similar review loaded 50 of 5,067 groups; the first detail contained two distinct
  contents, two physical representations, and one relationship.
- Five preview slots loaded across the two selected groups. Three distinct real H:
  source paths were explicitly checked; decoding succeeded and source sizes/mtimes were
  unchanged.
- Decision history, plans, and quarantine each correctly showed zero production rows.
- Backups showed two H: operational snapshots and one X: independent snapshot; DR
  readiness was `PASS`.
- Production decision count remained zero. No real owner decision was created.

The smoke did not execute quarantine/restore, scan or hash media, regenerate perceptual
hashes, contact a NAS/server, or access Z:.

## Limitations and next UI boundary

- There is no authentication; the owner supplies the recorded actor explicitly.
- Videos use a generic unavailable-preview state; no ffmpeg dependency exists.
- Thumbnail cache management is not exposed yet.
- Rich metadata/date comparison, album organisation, keyboard review workflows,
  accessible thumbnail zoom, and saved filters remain future UI work.
- Plans/quarantine/backup/recovery remain intentionally read-only.
- No installer or independently packaged desktop runtime is produced in M23.

M24 should focus on owner-reviewed usability refinements and safe packaging: richer
metadata comparison, keyboard/navigation accessibility, preview inspection, saved
review filters, and an independently installable Windows application. Physical-action
scope should remain separate and require its own owner approval.
