# M26 - Desktop UX Refinement

Status: implementation and local RC3 validation complete; pending owner review

## Scope and safety

M26 applies the completed M25 owner feedback to the existing PySide6 desktop. It changes
presentation, terminology, layout, and help text only. Catalogue schema 8, production
data, decision semantics, service boundaries, repository independence, and all physical
action restrictions are unchanged.

The RC2 preview correction remains mandatory: context/generation, physical-instance ID,
and source-path bindings are validated before every result is displayed; stale detail,
thumbnail, and enlarged-preview callbacks are discarded; preview widgets reset on
selection changes; and per-instance cache evidence remains isolated.

## Navigation and overview

The sidebar now has a consistent 190–230 pixel working range, padding, and spacing so
normal labels remain readable without consuming excessive width. Overview is grouped
into Catalogue, Library, Review, Safety / Actions, and Backups cards. It performs the
same bounded catalogue reads and starts no scan.

## Exact duplicate review

The group table fills its available width and prioritises Copies, Sources, Size,
Archival, Display, and Review status. Content ID remains available as a muted secondary
column. Compact backend state text is replaced by owner-facing labels.

Selecting a group displays the explicit statement that the files are byte-for-byte
identical according to verified SHA-256 evidence. The detail table prioritises filename,
source, readable size/date, and separate archival/display states. IDs, SHA-256, paths,
type, and raw timestamps remain accessible to the right and in tooltips/copy controls.

Preview space, grid spacing, selection contrast, and caption readability are increased.
Captions contain filename, source, size, and modified date rather than IDs, hashes, or
paths. New installations default to 256-pixel previews, with 128–320 pixel choices.
The Exact detail pane defaults to a larger vertical allocation and reserves enough table
height for three physical-copy rows. Exact and Similar splitter positions persist
independently as harmless UI preferences.

## Similar image review

Backend tier wording such as `review_only` is rendered as `Review only`. The table fills
available width while retaining raw pHash/dHash ranges. Inline help and header tooltips
explain that lower distances mean greater visual similarity, do not prove exact
identity, and the current review rule requires both hashes within threshold. Similar
detail uses the same owner-first hierarchy while keeping distinct content identities
and technical evidence available.

## Viewer and decisions

The read-only viewer presents filename, source, size, modified date, represented-copy
count, and plain-language archival/display state first. SHA-256, instance/content IDs,
and full path are available behind a collapsed technical-details control. Zoom, Fit,
100%, panning, and Escape are unchanged.

Decision controls use two rows: owner/reason/scope followed by separately labelled
nomination and nomination-resolution actions. Nomination and approval remain distinct.
Confirmation leads with a human question and filename/source/scope/owner/reason, may use
the already safely bound thumbnail, and places context ID, instance ID, and path in the
secondary details panel. No confirmation or health gate was weakened.

## Operational views

Backups / Recovery prioritises class, created time, readable size, and verification.
Backup ID, SHA-256, and manifest path remain secondary columns. Decisions, Plans, and
Quarantine now use explicit empty states while retaining their read-only safety notices.
No restore, quarantine, execution, or delete control was added.

## Accessibility and shortcuts

Existing accessible names and F5, Alt+Up/Down, Ctrl+PageUp/Down, Enter/double-click,
viewer zoom/Fit/100%, and Escape behavior are preserved. Tooltips now explain canonical
scope, exact/similar evidence, pHash/dHash, nomination, approval, and quarantine's
read-only boundary.

## Release candidate

- Version: `0.1.0rc3`
- Base source commit: `e1f0d8c`
- Source state: uncommitted M26 validation working tree, not a clean tagged release
- Archive: `PersonalLibrarian-0.1.0rc3-win64.zip`
- Schema compatibility: 8; no migration
- Signing/installer: unsigned portable one-folder ZIP, unchanged
- Archive size: `66,817,405 bytes` (approximately 63.7 MiB)
- Archive SHA-256: `A83818D65546CE4B109DBD777BF196439ECFA4379003277EF9BAD763CA70C324`
- Executable SHA-256: `14F35262CCBC2619694ED75D75F65EFB5BE254BE208EF5151461ECBCAA561E2D`
- Packaged files: `221`

RC3 is local only and is not published or tagged. RC2 should be retained temporarily as
the known-good rollback build until the owner accepts RC3.

## Known limitations

- Technical columns remain horizontally accessible rather than removed.
- Owner-adjusted individual table-column widths are not persisted; existing geometry,
  splitter, page-size, and preview-size preferences remain harmless and recoverable.
- The package remains unsigned, portable, and validated only on Windows 11 Pro 64-bit.
- Video previews remain placeholders and no custom application icon is present.
