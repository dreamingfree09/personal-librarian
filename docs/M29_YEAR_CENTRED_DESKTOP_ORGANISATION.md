# M29 — Year-Centred Desktop Organisation

## Status and boundary

M29 adds the first owner-facing Library section over the existing schema-9 catalogue.
It is logical catalogue organisation only. It does not scan the filesystem, rewrite date
evidence, create a media folder, or copy, move, rename, delete, hash, classify, or otherwise
alter media. The physical `Photos/Videos -> YYYY -> MM` direction remains separate and
unimplemented.

## Year-first design

`Library -> Years` is the primary browse route. It lists known years newest first and an
explicit `Unknown Date` shelf. Opening a shelf performs a bounded, paginated catalogue
query and displays one row per `content_identity_id`, with a lazily loaded preview,
filename, source, useful observed date, extension, and secondary content ID.

The browse year is deliberately conservative. All valid four-digit years (1900–2100)
from `physical_instances.observed_created_at` and `observed_modified_at` for an identity
must agree. Missing evidence or more than one distinct year places the identity in
`Unknown Date`. This is display evidence, not an authoritative capture-date decision;
M29 establishes no date precedence and writes no dates.

`All Photos & Videos` and `Unsorted / Not yet organised` use the same bounded query.
Unsorted means the identity has no active membership in an active album. Pagination
defaults to the harmless existing page-size preference and never loads a whole year.

## Albums within a year

Manual albums remain independent schema-9 entities. Their appearance within a year is
derived from active member date evidence; no album-year field or schema migration was
introduced. A newly created empty album is honestly shown as unplaced until content is
added. An owner may deliberately create a cross-year album, and its relevant member
count is shown in each derived year context.

The desktop supports confirmed create, rename, archive, restore, add-content, and
remove-content operations through `DesktopDataService` and the M28 organisation service.
There is no hard delete. Album UUID, membership, history, and media paths survive rename
and archive. The album detail shows its description, state, member count, bounded logical
members, representative previews, and secondary technical identity evidence.

Content selection never requires typing an ID. At most 50 selected identities may be
changed in one UI operation. An identity may belong to multiple albums without creating
another copy. Exact verified copies remain one logical album member because membership
targets `content_identity_id`; visually similar identities remain separate and may be
added independently.

## Tags, actor, and history

`Library -> Tags` exposes modest owner-created descriptive tags: create, add to selected
content, remove, and list for selected content. Tags are not albums, people, places,
events, or Collections, and M29 creates no AI tags.

Every mutation requires an explicit actor and offers an optional reason plus human
confirmation. The last actor is a harmless, recoverable UI preference; it is never
invented. `Library -> History` is read-only and shows the append-only schema-9 event
timestamp, actor, operation, album/tag/content reference, reason, provenance, and detail.

## Collections design gate

Collections are visible as an explanatory future area only. Schema 9 has no Collection
identity or audited membership and tags are not used as a substitute. A future schema-10
proposal should define a `collections` entity, content and/or album membership tables,
state/archive semantics, stable UUIDs, actor/provenance fields, append-only events, and
the rules for collections containing albums, content, or both. That design requires owner
review before migration.

## Preview and performance safety

The Library page reuses `ThumbnailService` and `ThumbnailTask`, including bounded image
decoding and the existing cache. Its binding token records generation, logical content,
physical instance, and source path. A callback is accepted only if every binding field
still matches a current widget item; stale generations and re-bound paths are rejected.
Only representative catalogue paths are read for previews, and source media is never
written.

## Validation and RC4

The mutation workflow is validated on disposable schema-9 catalogues: create, rename,
membership remove/re-add, archive/restore, manual tag add/remove, multi-album membership,
three-copy exact identity as one member, separate near identities, and append-only event
history. Automated production smoke is read-only and organisation counters must remain
unchanged.

M29 is packaged as `PersonalLibrarian-0.1.0rc4-win64.zip`, compatible with schema 9.
RC3 predates schema 9 and must not be used with the current production catalogue.

## Owner review and close-out

### Accepted owner model

The owner manually reviewed `Library -> Years` and positively accepted the Year-first
model. The year list felt natural as the main browse axis; the year supplies context so
album names need not repeat it; and 2025 remained usable at approximately 6,909 items
through bounded pagination. Logical catalogue organisation felt more natural than
exposing physical folders. In particular, the owner preferred albums existing only in
Personal Librarian rather than as Windows directories.

The owner-approved mental model is:

- Year = primary bookshelf.
- Album = meaningful logical group, usually viewed within a year.
- Collection = future cross-year grouping.

Physical storage remains separately directed as `Photos/Videos -> YYYY -> MM`; the
logical views neither implement nor mirror that structure on disk.

### First production album and memberships

The first real production album is active album `Christmas` (album ID 1, UUID
`5336a05a-2148-4891-9d86-bb04a2db7e06`), created by `owner-test` with
`owner-manual` provenance. The owner confirmed that catalogue-only creation—with no
Windows folder and no copied, moved, or renamed media—is correct and desirable.

The owner then added two active logical members successfully:

- Membership 1: content identity 13725, OneDrive `.gif`, created by `owner-test`.
- Membership 2: content identity 15461, OneDrive `.jpg`, created by `owner-test`.

These memberships demonstrate content-level semantics without media duplication. The
immutable production history contains exactly event 1 `album_created`, event 2
`album_member_added` for content 13725, and event 3 `album_member_added` for content
15461. All three have actor `owner-test`, provenance `owner-manual`, and no reason.

### Owner-review defects and outcomes

The initial Christmas creation unintentionally recorded `description = owner-test`.
The text was captured by the desktop input flow before the correctly keyword-wired
service call. The create flow now uses a dedicated form with separate Name and
Description fields, an explicitly blank Description default, `None` for blank input,
and actor/reason outside the form. Disposable packaged validation confirmed blank
description remains `NULL`, explicit description persists, and neither actor nor reason
populates description. The existing production value is harmless owner-test residue and
was intentionally not corrected automatically.

One packaged application exit was reported during the owner's first membership attempt.
The close-out investigation reproduced an exit on a disposable schema-9 copy after a
successful organisation mutation. Windows Application Error recorded a `Qt6Core.dll`
access violation (`0xc0000005`). Static review localized the packaged-only race to the
Library `QRunnable` wrapper not being retained while its queued completion callback
immediately scheduled a refresh. Library workers are now retained, native auto-delete is
disabled, terminal signal emission is guarded, and the worker is released only after its
terminal signal. Focused lifetime regression coverage was added. After rebuilding RC4,
the same disposable packaged mutation persisted correctly and the process remained alive
and responsive; clean-extraction production smoke also passed. This defect is therefore
confirmed fixed, while any future unexpected exits should still be monitored.

Owner review confirmed Year-first browsing, bounded year pages, logical albums rather
than folders, first real album creation, real content memberships, immutable history,
content-level membership, and explicit owner provenance.

## Known limitations and M30 recommendation

- Browse-year evidence is intentionally conservative and may leave many items Unknown.
- Empty albums have no year association until a dated member is added.
- Album membership batches use the existing per-identity audited service operation.
- Collections, preferred capture date, smart albums, AI classification, and physical
  organisation remain unavailable.

Recommended M30 scope: **Preferred Date Evidence and Cross-Year Collections
Design/Foundation**. Define an explicit auditable preferred-date model, improve
chronological browsing and reduce unnecessary Unknown Date population, and design
schema-10 Collections without weakening the accepted Year-first model. AI and physical
organisation remain separate, later milestones.
