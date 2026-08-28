# M30 — Preferred Date Evidence and Cross-Year Collections

## Status and boundary

M30 is formally complete as of 27 August 2026. M30A locked the owner-approved policy;
M30B implemented the schema-10 structure; M30C implemented deterministic preferred-date
services and catalogue-only evidence extraction; M30D implemented owner-managed Collection
services and audited membership lifecycle; and M30E integrated preferred dates, review
controls, Collections, and filtered history into the desktop. Schema-10 production
migration, canonical RC7 packaging, and the initial catalogue-only production population
also completed with accepted H/X recovery evidence.

EXIF DateTimeOriginal, video capture timestamps, trusted Google Photos metadata/sidecars,
approved OneDrive capture metadata, richer semantic/AI analysis, and physical media
reorganisation are future separately approved work, not unfinished M30 scope.

M30 performs no AI analysis or physical media action. It does not copy, move, rename, or
delete media; alter raw media metadata or hashes; or change similarity evidence.

## Preferred-date principle

A preferred date is an explicit catalogue interpretation of preserved evidence. Raw and
source metadata is never overwritten. A selected preferred date references preserved
evidence, records provenance and selection method, remains auditable, and never
manufactures missing date components. An owner-set date has the highest authority.

## Date precision

Supported precision is:

- year;
- year-month;
- date; and
- datetime.

Partial dates remain partial. The system must not substitute January for an unknown
month, day 1 for an unknown day, or midnight for an unknown time.

## Source authority

Authority tiers are:

1. Owner-set date.
2. Embedded capture metadata: EXIF `DateTimeOriginal` and equivalent embedded video
   capture metadata.
3. Trusted source capture metadata: Google Photos/Takeout and approved OneDrive or other
   source capture metadata.
4. Explicitly approved deterministic filename-derived dates.
5. Filesystem created/modified evidence.

No numeric confidence score grants preferred-date authority.

## Filename-only authority

The owner approves automatic resolution from filename-derived evidence only when no
stronger valid evidence exists, the filename matches an explicitly allow-listed and
unambiguous deterministic pattern, the parser has a stable name/version, and the result
is calendar-valid. A broad or fuzzy filename parser is not authorised.

The initial design should support a versioned allow-list such as:

- `IMG_YYYYMMDD_HHMMSS`;
- `VID_YYYYMMDD_HHMMSS`;
- `YYYY-MM-DD_HH-MM-SS`; and
- `YYYYMMDD_HHMMSS`.

The exact production allow-list may be refined during implementation and testing. Every
filename-derived evidence row retains the original filename/raw value, parser or pattern
identifier, parser version, and provenance.

## Filesystem-only authority

The owner rejects automatic preferred-date resolution from filesystem created/modified
timestamps when they are the only available evidence. They remain preserved evidence,
but the result is `unknown` with reason concept `weak_evidence_only`.

Filesystem timestamps do not challenge stronger capture, source, or approved filename
evidence merely because media was copied, downloaded, or restored later.

## Agreement and conflict rules

Values agree when they identify the same calendar date even if time-of-day differs, or
when known timezone offsets prove that they represent the same instant. Partial values
are compatible when the more precise candidate falls within the less precise candidate's
known interval. Missing components must never be combined from separate evidence rows.

A one-day discrepancy is timezone-plausible only when both values have datetime
precision, their local calendar dates differ by exactly one day, and their wall-clock
difference is no more than 14 hours. A strictly stronger source may win; the weaker
evidence remains recorded as timezone-adjacent. Equal-authority strong sources require
`needs_review`. Date-only values differing by one day are not automatically timezone
shifts.

Material disagreement between strong embedded/source metadata produces `needs_review`.
A nominally higher tier must not silently win a material strong-source conflict. For
example, EXIF 2018 against Google Photos 2021 requires review.

## Owner override and Unknown Date

An owner-set date always controls the current preferred-date selection. Contradictory
evidence remains preserved. Automated reruns may add evidence, report conflicts, and
update basis relationships, but may not replace an active owner selection. Only an
explicit owner action may replace or clear another owner selection.

`Unknown Date` is valid and preferable to false precision. Use it when no reliable
evidence exists, only weak filesystem evidence exists, strong evidence is materially
conflicting, or evidence is malformed or ambiguous.

## Year browsing

Year remains the primary browse axis. A resolved preferred date's selected year controls
Year placement, and year-only precision is sufficient. `needs_review`, `unknown`, and no
preferred-date record all appear under `Unknown Date`.

Album names never determine year. Physical paths do not determine semantic year except
where an explicitly recorded source-evidence rule produces date evidence.

## Collections

Collections are explicit cross-year logical groupings such as Family, World of Mayden,
Holidays, Old Family Photos, and Favourites.

M30 Collections contain content identities directly. Album containment is not supported
in M30. Direct content membership preserves stable semantics and the same exact-duplicate
behaviour as Albums while avoiding transitive membership complexity. A separate
album-containment relationship may be designed later if a real use case requires it.

Collections have stable integer IDs and UUIDs. Duplicate names are allowed but never
merge. They support create, rename, archive, restore, and reversible add/remove/restore
membership. Their organisation history is immutable, and they have no physical
filesystem effect.

## Migration and population policy

Schema 9 to 10 migration creates structure only. It must preserve all existing production
state and create no Collections, date evidence, preferred dates, or organisation events.
Evidence extraction and population is a separate reproducible pipeline.

Production migration requires separate owner approval.

## AI policy

No AI is authorised in M30. Future local AI enters through a suggestion layer and may
suggest dates, events, Albums, Collections, or semantic categories. Suggestions remain
non-authoritative until explicitly accepted or governed by a future owner-approved
automation policy. AI scoring is not preferred-date authority.

## Approved implementation sequence

1. M30A - Policy lock.
2. M30B - Schema 10.
3. M30C - Preferred-date services and deterministic evidence pipeline.
4. M30D - Collections services.
5. M30E - Desktop integration.
6. M30F - Packaging, clone validation, backups, and production readiness.

## M30B implementation — schema 10

M30B implements the schema-only foundation in migration 10,
`preferred_date_evidence_and_collections`. It adds immutable content-date evidence,
the current preferred-date projection, preferred-date basis links, reproducible date
evidence job bookkeeping, manual Collections and direct content memberships, and the
expanded immutable organisation event history. The migration adds no seed or domain
rows and implements no extraction, preferred-date selection, Collection service, CLI,
or desktop behaviour.

Focused migration tests prove that a schema-9 production-like fixture preserves its
catalogue UUID, Album and membership rows, Christmas fixture, and every existing
organisation event ID, UUID, timestamp, reason, provenance, and details JSON value.
A deliberate schema collision proves that migration failure rolls the whole transaction
back to schema 9 without leaving schema-10 tables behind.

On 2026-08-25 a disposable read-only backup clone of the production catalogue was
migrated from schema 9 to schema 10. Before and after, `integrity_check` returned `ok`,
`foreign_key_check` returned no rows, and catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33` was unchanged. Preserved counts were 69,444
physical instances, 56,127 content identities, 7,707 exact-duplicate groups, 5,067
similarity groups, 1 Album, 2 active Album memberships, 0 Tags, 0 content tags, and 3
organisation events. The Christmas Album remained UUID
`5336a05a-2148-4891-9d86-bb04a2db7e06`, name `Christmas`, description `owner-test`,
state `active`, with 2 active members. Collections, Collection memberships, content
date evidence, preferred dates, and preferred-date basis rows all remained empty.

The production catalogue itself was not migrated or modified. No media was read,
written, moved, copied, renamed, rehashed, or used for similarity regeneration. No AI,
Ollama, NAS/server, retired-drive, packaging, or rebuild action was used. The disposable
catalogue clone was used only for migration validation.

M30 remains open. M30C is documented below; M30D must implement Collection services,
M30E must integrate completed behaviour into the desktop, and M30F must complete
packaging, final clone validation, backup, and separately approved production-readiness
work.

## M30C implementation — preferred-date services and deterministic evidence

M30C implements typed partial dates, immutable evidence recording/reuse, policy
evaluation, current preferred-date projection, basis reconciliation, owner overrides,
bounded read queries, minimal CLI seams, and a resumable catalogue-only evidence job.
The named policy is `preferred-date-policy-v1`; it uses explicit authority tiers rather
than numeric confidence. It implements partial compatibility, same-calendar-date and
known-offset same-instant agreement, strong-source conflict review, the bounded
adjacent-day rule, filename authority, and filesystem-only `weak_evidence_only` Unknown
results. Missing components are never manufactured or borrowed.

The initial extractor scope is deliberately limited to `observed_created_at` and
`observed_modified_at` values already stored in the catalogue, plus exact allow-listed
filename stems. No media file is opened or statted. The filename parsers are version 1:

- `filename-img-yyyymmdd-hhmmss`;
- `filename-vid-yyyymmdd-hhmmss`;
- `filename-iso-date-time`; and
- `filename-yyyymmdd-hhmmss`.

Extensions are ignored, but other prefixes, suffixes, fuzzy matches, and locale-based
interpretation are not accepted. Calendar-invalid matches are reported as invalid.
EXIF, embedded-video, Google Photos, OneDrive, and specialist extractors remain typed
service seams; M30C does not read media bytes or introduce a source-metadata scan.

Owner date actions require an actor and deterministic action ID. Retrying the same
action is idempotent. A new action ID explicitly replaces the current override by adding
new immutable owner evidence, superseding the prior current basis, updating the current
projection, and appending immutable organisation history. Automated policy runs cannot
replace an active owner selection. Clearing an override is deferred because safe
recomputation and explicit owner semantics require a separately reviewed action design.

Evidence identity includes content, physical/source context where applicable,
source field and locator, exact raw value, extractor identity/version, and normalisation
version. Identical jobs reuse evidence, basis, preferred state, and events. A changed
extractor version may append evidence; a changed policy version may update the current
projection and append an auditable event. Jobs use deterministic configuration
fingerprints, per-physical-instance checkpoints, bounded batches, resume, item-level
failure isolation, and JSON-friendly reconciliation metrics.

On 2026-08-25 a disposable clone of the schema-9 production catalogue was migrated to
schema 10 and processed with a 5,000-physical-instance bound. The batch represented
4,571 content identities, completed without job errors, created 5,373 evidence rows
(5,000 filesystem-modified and 373 filename-derived), and produced 373 resolved and
4,198 Unknown preferred states. All Unknown results were `weak_evidence_only`; there
were no needs-review or strong-conflict results in this limited batch. The distribution
is architecture validation only and is not a statement of final library date quality.

The batch took approximately 176.9 seconds (28.3 physical items/second). The status/year
aggregate took 31.1 ms, one bounded evidence detail took 2.4 ms, and a 50-row
needs-review page took 8.1 ms. A disposable year-only owner override was then added to
one clone identity; policy rerun preserved it and added no duplicate event. Clone
`integrity_check` returned `ok` and `foreign_key_check` returned no rows.

Production remained schema 9 with zero date-evidence and preferred-date rows and exactly
3 organisation events before and after validation. Its file size and nanosecond
modification timestamp were unchanged. No production evidence population, production
migration, media action, AI/Ollama, server/NAS, retired-drive access, packaging, or
rebuild occurred.

M30 remains open. M30D is documented below; M30E must integrate completed date and
Collection behaviour into the desktop, and M30F must complete packaging, final clone
validation, backups, and separately approved production-readiness work.

## M30D implementation — Collections services and audited membership lifecycle

M30D implements owner-managed cross-year Collections as direct groupings of
`content_identity_id` values. Collections never contain Albums, physical instances,
other Collections, or automatically classified semantic content. Duplicate names are
allowed and always retain separate integer IDs and UUIDs.

The dedicated Collection service implements create, rename, archive, restore, content
add, logical remove, and explicit membership restore. New Collections are manual and
active. Archived Collections reject rename and membership mutation until restored.
Membership removal sets `ended_at`; restoration clears it. Add does not silently revive
a removed membership, and neither Collections nor memberships are hard-deleted.

Every owner mutation requires an actor and explicit action ID. Actual state changes and
their immutable `organisation_events` row commit atomically. The action ID and useful
before/after values are retained in `details_json`. Retrying an audited action reuses its
original target and creates no duplicate entity, membership, or event. No-op lifecycle,
rename, and membership requests make no history claim. Reusing an action ID for a
different actor, operation, target, or requested value is rejected.

History uses the schema-10 target shapes: Collection lifecycle events target only the
Collection; membership events target the Collection, membership row, and content
identity. Actor type/identifier, provenance, optional reason, UUID, timestamp, and JSON
details remain append-only.

Bounded services and CLI commands support Collection list/show, member list, Collections
for one content identity, and Collection history. Lists support lifecycle filters,
pagination, active/removed counts, and duplicate-name counts. Member rows include one
representative stored physical path/metadata snapshot, total physical-instance count,
and preferred-date projection when available, using one bounded SQL query rather than
per-row service lookups. CLI mutation commands require
`--confirm-collection-action`, `--actor`, and `--action-id`.

On 2026-08-25 the required disposable schema-10 validation sequence created Family,
Holidays, and a second distinct Family. It produced 3 Collections with 3 distinct UUIDs,
2 Family names, 2 active logical memberships, and 9 organisation events: 3 creates,
2 member adds, 1 member remove, 1 member restore, 1 archive, and 1 restore. Adding the
same exact-duplicate content identity twice remained one membership and produced no
second add event; a different similar content identity was independent. Archived
membership mutation was rejected. `integrity_check` returned `ok` and
`foreign_key_check` returned no rows. The disposable catalogue was removed afterwards.

Production remains schema 9 with no Collections tables or Collection events. No
production migration or logical-organisation mutation occurred. No media was opened,
written, moved, copied, renamed, deleted, rehashed, or used for similarity regeneration;
no AI/Ollama, server/NAS, retired-drive, packaging, or rebuild action occurred.

M30 remains open. M30E is documented below, and M30F must complete packaging, final
clone validation, backups, and separately approved production-readiness work.

## M30E implementation — desktop preferred dates and Collections

M30E extends the desktop service facade without moving date or Collection policy into
Qt widgets. The facade exposes schema compatibility, bounded preferred-date detail,
evidence and basis rows, status pages, owner set/replacement, Collection lifecycle and
membership actions, and broad-domain History pages. Owner mutations retain explicit
actor, reason, and per-action identifiers.

On schema 10, Years now use only the indexed current preferred-date projection. A
resolved row appears on its `selected_year` shelf at any genuine precision, including
year-only. Needs-review, unknown, and missing preferred rows appear under Unknown Date;
observed filesystem timestamps are never a fallback. Shelf counts and bounded pages are
computed in SQL, with one logical tile per content identity. Schema 9 remains available
only as an explicit legacy compatibility view: preferred-date and Collection controls
are disabled, schema-10 tables are not queried, and launch never migrates the catalogue.

Tiles show a concise preferred value, evidence source or owner-set label, and status.
The bounded evidence dialog separates preserved raw candidates from the current
interpretation and shows precision, source field/provenance, physical source/path when
applicable, current basis roles, and timezone evidence. Needs-review and Unknown-only
controls remain within the Year-first browser. A single-content owner dialog supports
year, year-month, date, and datetime values, shows the current interpretation, requires
an actor and exact confirmation, and requires explicit replacement of an existing
owner-set selection. Successful changes refresh Year shelves and content.

The former placeholder is now a bounded Collections tab with active, archived, and all
filters; UUID-disambiguated duplicate names; Collection detail and counts; representative
member previews; preferred-date, physical-instance, source/path, extension, and cheap
Album-count summaries; and create, rename, archive, restore, add, logical remove, and
explicit membership restore actions. The creation dialog contains only name and
description, so actor and reason cannot leak into entity fields. Adds operate on at most
50 selected Year content identities and generate individually audited actions. No
nested Collection, Album containment, or physical action is exposed.

History is bounded and filterable by Albums/Tags, Collections, Preferred Dates, or All.
Rapid Year, Collection, content-detail, and History callbacks reject stale selection or
generation results. Library workers remain retained with auto-delete disabled until
their terminal signal releases them, and preview callbacks retain the existing
generation/content/instance/path guards. Dialogs remain parent-owned and media preview
continues to use stored physical paths read-only.

On 2026-08-26 a disposable schema-10 offscreen Qt validation used six logical content
identities, including a two-instance exact identity and a separate similar identity. It
provided resolved date and year-only shelves, one needs-review row, Unknown/missing
rows, an owner-set replacement, two distinct Collections both named Family, logical
add/remove/restore, and Collection archive/restore. The UI loaded 3 Year shelves, 2
Collection rows, and 2 member tiles; duplicate UUIDs remained distinct, duplicate exact
add was a no-op, the similar identity remained independent, stale preview delivery was
rejected, and the process remained responsive. The catalogue held 2 Collections, 2
active memberships, 4 preferred rows, and 11 organisation events. Integrity was `ok`
with no foreign-key violations, and all disposable files were removed.

Approximate small-catalogue timings were 8.616 ms for Year shelves, 2.955 ms for one
25-item Year page, 6.257 ms for preferred-date detail, 1.732 ms for the Collection list,
3.076 ms for one 25-member Collection page, and 2.886 ms for one filtered 25-event
History page. These are validation measurements, not production-scale benchmarks.

Production remained schema 9 with 1 Album, 2 active Album memberships, 0 Tags, 0 content
tags, 3 organisation events, and no preferred-date, date-evidence, Collection, or
Collection-membership tables/rows. Its size and modification timestamp were unchanged.
No production migration/population, media mutation or metadata write, rehash, similarity
regeneration, AI/Ollama, server/NAS, retired-drive, packaging, or rebuild occurred.

M30 remains open. M30F must complete packaging, final clone validation, backups, and
separately approved production-readiness work.

## M30F readiness — RC5, backups, and production migration gate

RC5 (`0.1.0rc5`) is the schema-10 desktop successor to RC4. The canonical artefact is
`H:\PersonalLibrarian\release\PersonalLibrarian-0.1.0rc5-win64.zip`: 66,926,494 bytes,
221 packaged files, ZIP SHA-256
`2C870EFDD2A996483148349ECE57C44C64B987AE56BB4F33442584F7340A1976`, and EXE
SHA-256 `DE8AB6153666554C37A183819F029FE3AFB9B91A6438F9198DC941F3FCE4AFB1`.
The prior RC4 ZIP remains present with its original SHA-256
`8A05DEC4FB68F122ED21871F052C9C91451EF722A9577EAFCE70E9220436D719`.
RC4 remains the schema-9 generation and must not be used after a catalogue reaches
schema 10. RC5 expects schema 10 and desktop launch does not migrate a catalogue.

The RC5 ZIP was extracted to a fresh directory and launched first against a disposable
schema-10 root. The frozen process detected schema 10 and exercised Overview, Library,
Years, resolved and year-only values, Unknown Date, needs review, evidence and owner
replacement, two UUID-distinct same-name Collections, membership remove/restore,
Collection archive/restore, filtered History, Exact, Similar, Decisions, Plans,
Quarantine, and Backups/Recovery. Blank Collection description remained SQL `NULL` and
an explicit description persisted. Integrity was `ok` with no foreign-key violations.

The clean package also completed a bounded real-input stability pass against the
populated production clone: 12 rapid Year switches, 8 Collection switches, 8 preview
selections, 3 owner-dialog open/cancels, 3 Collection-create open/cancels, 3 membership
confirmation cancels, 4 History filter switches, and navigation through all eight main
sections. The process remained responsive; a separate close check exited normally with
code 0. The packaged smoke exposed no physical-action controls. The final M30-focused
regression set contains 93 tests and passed, and compilation passed.

Fresh schema-9 backups were created before the gate. H operational backup
`8e43788d-be27-43d6-afbb-07ee214bb72e` and X independent-local backup
`8af99610-db43-4e5e-990b-33210fe1028b` both returned `ACCEPTED`, integrity `ok`, zero
foreign-key violations, catalogue UUID `613affe5-a00b-49bc-9ad9-99b95adeec33`, and the
same SHA-256 `c19e3c6f612f12337ef26661da82f7c372b363f587f007460c77909d4cd64a17`.
The X manifest records `device_independence=confirmed`, with production on Windows
storage device 2 and X on device 1. X is an independent local DR backup, not offsite.

The exact production baseline remained schema 9: 69,444 physical instances; 56,127
content identities; 7,707 exact groups; 5,067 similarity groups; 1 Album; 2 active
Album memberships; no Tags/content tags; 3 organisation events; and zero date evidence,
preferred dates, Collections, or Collection memberships. Christmas remains active with
UUID `5336a05a-2148-4891-9d86-bb04a2db7e06`, name and description `Christmas` and
`owner-test`, and 2 members. The database remained 271,876,096 bytes with UTC mtime
`2026-08-25T09:33:41.360939+00:00` before and after M30F.

A clone made from the new verified H backup migrated 9 to 10 transactionally. Before
and immediately after the structure-only migration, all baseline counts, catalogue UUID,
Christmas values, and the original three organisation-event IDs, UUIDs, and details were
preserved. Integrity was `ok`, foreign keys were clean, and Collections, Collection
memberships, date evidence, preferred dates, and preferred basis rows were all zero.

The current M30C extractor was then run on the clone at its maximum bounded batch of
5,000 physical instances, representing 4,571 identities. In approximately 160 seconds
(about 31 physical items/second), it created 5,000 `filesystem_modified` and 373
`filename_derived` evidence rows with zero item errors. It reported 373 resolved
outcomes, 4,198 unknown/`weak_evidence_only`, no needs-review or strong conflicts, and
preserved one disposable owner year override. The final clone projection contained 372
filename-selected resolved identities plus that owner selection, with 55,754 identities
under Unknown Date because unprocessed identities have no preferred row.

For comparison, the complete M29 catalogue-timestamp view placed 54,647 identities in
resolved years and 1,480 under Unknown Date. The populated schema-10 preferred view
placed 373 in resolved years and 55,754 under Unknown Date. This is a bounded pipeline
readiness result, not final date quality. There were zero filename-derived year shifts
relative to a differing M29 year in this batch, zero invented selected values, and zero
automatic resolutions from filesystem-only evidence. Policy was not weakened to reduce
Unknown counts.

Clean-extracted RC5 then detected the populated clone as schema 10, used preferred-only
Years, exposed Collections and History, loaded Unknown/review paths, accepted an owner
action and a disposable Collection/member action, remained responsive, and showed no
out-of-scope physical controls. The clone was never treated as production.

At the M30F readiness gate, production was not migrated or populated. No production Collection was created; no media
was moved, copied, renamed, deleted, rehashed, regenerated for similarity, or written;
no AI/Ollama, Z drive, NAS, or server was used. The M30F evidence establishes a migration
gate only. M30 remains open, and any production schema-10 migration requires a separate,
explicit owner approval.

## Production schema-10 migration — owner-approved structure-only cutover

The owner separately approved the production schema 9 to 10 migration. Before cutover,
the production catalogue and the named M30F H and X schema-9 backups were revalidated.
Production was schema 9 with integrity `ok`, no foreign-key violations, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, the exact M30F baseline counts, unchanged
Christmas, and the same three comparison-safe organisation events. Both backups returned
`ACCEPTED`; no Personal Librarian desktop or write-capable CLI process was active.

Migration `preferred_date_evidence_and_collections` was applied through the established
`connect_existing_catalogue` plus `apply_migrations` mechanism at
`2026-08-26T11:11:18.485Z`. Immediate and post-smoke checks returned schema 10,
integrity `ok`, and no foreign-key violations. Catalogue UUID, 69,444 physical instances,
56,127 content identities, 7,707 exact groups, 5,067 similarity groups, 1 Album, 2 active
Album memberships, zero Tags/content tags, and 3 organisation events were preserved.
Christmas retained its UUID, name, `owner-test` description, active state, and 2 members.
Every original organisation-event ID, UUID, type, timestamp, JSON detail, actor,
provenance, reason, and target field compared equal to the schema-9 recovery point.

The cutover was structure-only. Production contains zero date evidence, preferred dates,
preferred basis, Collections, Collection memberships, date-evidence jobs, and job items.
No organisation event was added by migration.

The first schema-10 production recovery points are H operational backup
`2367efcd-4c55-4b93-9141-f3766b5ac663` and X independent-local backup
`ea42f315-2cad-47ad-b16c-3ebd70996b8b`. Both are `ACCEPTED`, schema 10, integrity `ok`,
and foreign-key clean; X physical-device independence and disaster-recovery health are
`PASS`. The earlier schema-9 backups remain preserved.

A fresh extraction of canonical RC5 passed production smoke with production and DR
health `PASS`. It exposed Overview, Library, one Unknown Date shelf containing all 56,127
identities, empty Collections, History, Exact, Similar, Decisions, Plans, Quarantine,
and Backups/Recovery without schema errors or forbidden physical controls. A bounded
real-input navigation pass remained responsive. The preview smoke read one stored media
path without changing the source and wrote only the normal thumbnail cache.

Production is now schema 10. RC5 is the canonical production desktop; RC4 must no longer
be used against production and remains preserved only as historical schema-9 release and
recovery evidence. No date pipeline, owner-date action, Collection action, Album action,
media mutation, rehash, similarity regeneration, AI/Ollama, Z drive, NAS, or server use
occurred. M30 remains open. Production preferred-date evidence population requires the
next separate explicit owner approval.

## Production preferred-date population — Batch 1

The owner separately approved the first production preferred-date population batch with
a hard maximum of 5,000 physical instances. Preflight confirmed schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, zero
date evidence/preferred/basis/job rows, zero Collections/memberships, the three existing
organisation events, and unchanged legacy counts and Christmas. Pre-population schema-10
backups H `2367efcd-4c55-4b93-9141-f3766b5ac663` and X
`ea42f315-2cad-47ad-b16c-3ebd70996b8b` revalidated as `ACCEPTED`.

Job `m30-production-preferred-date-batch1-v1` used pipeline `m30c-v1`, policy
`preferred-date-policy-v1`, normalisation `partial-date-v1`, catalogue timestamp extractor
version 1, filename allow-list version 1, and configuration fingerprint
`3dd16904089187421caa0e18cbef21979e4e01e38cca57409d0ad5d9ec1723d6`. Selection was
deterministic: content-linked physical instances ordered by `physical_instance_id`
ascending with `LIMIT 5000`, producing IDs/item keys 1 through 5000 and representing
4,571 content identities. No random sampling or extractor widening occurred.

The first run completed in 193.398 seconds at 25.853 physical items/second. It created
5,373 evidence rows: 5,000 `filesystem_modified` and 373 `filename_derived`; no evidence
was reused on the first pass. It recorded 5,000 job items under one job, found 373 valid
filename matches, no invalid/ambiguous filename matches, and no job errors. The report
contained 373 resolved, 4,198 Unknown, zero needs-review, 4,198
`weak_evidence_only`, zero strong conflicts, 4,575 preferred-state changes, 425 unchanged
item outcomes, and zero owner overrides.

The same job/config rerun completed in 0.222 seconds and skipped all 5,000 existing
job-item checkpoints. Evidence, preferred projections, basis links, jobs/items,
organisation events, and every unrelated count had zero delta. The report is cumulative
over stored first-pass payloads and therefore still displays 5,373 created and zero
reused; the meaningful rerun result is zero new/reused processing and zero database
change. No duplicate evidence, projection, basis, or event was created.

Production now has 5,373 evidence rows, 4,571 preferred projections, 4,948 basis links,
one job, and 5,000 job items. The policy appended 4,575 immutable events: 373
`preferred_date_resolved` and 4,202 `preferred_date_unknown` events. The original three
Album events remain field-for-field preserved; no Collection event or new Album/Tag event
exists. There are zero filesystem-only automatic resolutions and zero selected values
that differ from their referenced evidence.

The preferred Year distribution is 373 identities in 2026 and 55,754 under Unknown
Date, with zero needs-review. Thus 373 identities moved from Unknown into a resolved
year in Batch 1. This bounded result is not a final date-quality assessment. Measured
query times were 35.623 ms for Year shelves, 19.459 ms for one resolved 25-item page,
836.018 ms for one Unknown 25-item page, and 32.847 ms for one preferred-date detail.

A fresh canonical RC5 extraction passed the packaged production smoke. It showed the
2026 resolved shelf and Unknown shelf, a `Filename-derived · Resolved` tile with
`selected_by_authority` detail, an Unknown tile with `weak_evidence_only` detail, empty
Collections, and a read-only preview whose source remained unchanged. Production and DR
health were `PASS`, no forbidden physical controls appeared, and the process remained
responsive.

The first populated-state recovery points are H operational backup
`f8adccdb-74d7-4f1b-9ad3-23b4121c3fe0` and X independent-local backup
`cd2373fb-cbfe-4aeb-8b00-f1cca14fa4dc`. Both are schema 10, `ACCEPTED`, integrity `ok`,
and foreign-key clean; X device independence and DR health are `PASS`. Earlier
pre-population and schema-9 backups remain preserved.

The pipeline read only stored catalogue fields. It did not open media bytes, read EXIF or
video metadata, use external source metadata, write/move/copy/rename/delete media, change
metadata, rehash, regenerate similarity, run AI/Ollama, or access Z, NAS, or server.
Normal RC5 preview read one source read-only and wrote only the normal thumbnail cache.

M30 remains open and full date population is not complete. At Batch-1 close, Batch 2 was
blocked because the selection query always returned physical IDs 1 through 5000, so a
different job would revisit Batch 1 instead of selecting the next window. The cursor fix
is documented below; Batch 2 nevertheless remains separately owner-gated.

## Deterministic cursor/range batching

The M30C pipeline now accepts an explicit non-negative
`after_physical_instance_id` cursor and a bounded positive `limit` (maximum 5,000). It
selects content-linked rows with `physical_instance_id > cursor`, orders by
`physical_instance_id ASC`, and applies the limit. It never uses OFFSET. Consequently,
gaps are harmless: the report records the actual selected count, first and last IDs,
end-of-catalogue state, and the actual last ID as `next_cursor`; an empty batch completes
with zero changes, null first/last/next IDs, and `end_of_catalogue=true`.

Cursor, limit, deterministic ordering, extractor versions, normalisation, pipeline, and
policy are all retained in config JSON and its fingerprint. Identical job/cursor/config
reruns retain checkpoint idempotency; changing a cursor changes the fingerprint and a
reused job ID is rejected. Cursor zero preserves first-page semantics. Existing jobs
whose stored config predates the explicit cursor remain resumable only under the
equivalent cursor-zero/legacy-limit definition.

A disposable clone of populated production validated sequential 5,000-item windows.
Batch A selected actual IDs 1–5000 and reused the existing 5,373 evidence rows. Batch B
used A's reported cursor 5000 and selected actual IDs 5001–10000, with zero overlap. Its
same-job rerun completed in 0.189 seconds with no count change. Legacy counts were
preserved, integrity was `ok`, and foreign keys were clean. The selection plan was
`SEARCH physical_instances USING INTEGER PRIMARY KEY (rowid>?)`; direct selection took
approximately 3.398 ms for A and 4.872 ms for B, confirming indexed cursor access rather
than an OFFSET scan.

No production pipeline job was run during cursor implementation or clone validation.
At that validation gate, Production Batch-1 state remained the last populated state and
Batch 2 still required a new, explicit owner-approved runbook. That separate approval
and bounded production run are recorded below.

## Production preferred-date population — Batch 2

The owner separately approved exactly one additional deterministic production window.
Preflight at HEAD `ddbef21` found a clean worktree, schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact Batch-1 and legacy counts recorded above. Populated-state backups H
`f8adccdb-74d7-4f1b-9ad3-23b4121c3fe0` and X
`cd2373fb-cbfe-4aeb-8b00-f1cca14fa4dc` both revalidated as `ACCEPTED` before the run.
Christmas and its three original Album events were unchanged.

Job `m30-production-preferred-date-batch2-v1` used cursor 5000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Configuration fingerprint
`5bbce04f03423e23ae84995502d5df6beb3fef3bdf77d220a32f25f661cd4e25` selected
exactly 5,000 content-linked physical instances, actual IDs 5001–10000, with next cursor
10000 and `end_of_catalogue=false`. Stored checkpoints independently confirmed 5,000
distinct IDs and zero overlap with Batch 1.

The first run completed in 212.890 seconds at 23.486 physical items/second and
represented 3,561 content identities. It created 5,000 `filesystem_modified` evidence
rows and reused none. There were no filename-derived matches, invalid or ambiguous
filenames, errors, strong conflicts, needs-review states, or owner overrides. All 3,561
represented identities were Unknown with `weak_evidence_only`; no identity was newly
resolved. The policy recorded 3,560 preferred-state changes and 1,440 unchanged
physical-item applications. One represented identity overlapped Batch 1 and already had
an unchanged Unknown projection; the remaining repeated physical instances did not
append repeated-state events.

The identical job/cursor/config rerun completed in 0.417 seconds and skipped all 5,000
checkpoints. Evidence, preferred projections, basis links, jobs, job items, organisation
events, and unrelated counts had zero delta. As in Batch 1, the returned report is
cumulative over stored first-run payloads and therefore still displays the original
created counts despite doing no new work.

Cumulative production totals after Batches 1 and 2 are 10,373 evidence rows, 8,131
preferred projections, 8,508 preferred-basis links, two jobs, 10,000 job items, and
8,138 organisation events. Batch 2 appended exactly 3,560
`preferred_date_unknown` events. No Collection, new Album, or Tag event was added, and
the original Album events remain field-for-field exact. Cumulative evidence comprises
10,000 `filesystem_modified` and 373 `filename_derived` rows.

The cumulative preferred Year distribution remains 373 identities in 2026, 55,754
under Unknown Date, and zero needs-review. Batch 2 newly resolved zero identities, so
the cumulative resolved count remains 373. This bounded population result is not a final
date-quality assessment. Measured query times were 46.477 ms for Year shelves, 18.444 ms
for one resolved 25-item page, 889.411 ms for one Unknown 25-item page, and 31.686 ms for
one preferred-date detail. The Unknown page was approximately 6.4% slower than Batch 1,
which was not treated as a significant regression during this production run.

A fresh canonical RC5 extraction passed the frozen production smoke. Production and DR
health were `PASS`; the cumulative 2026 and Unknown shelves loaded; a resolved detail
showed filename-derived selected evidence; a Batch-2 weak-evidence detail remained
Unknown; Collections were empty; History filters worked; the process remained
responsive; and the read-only preview source was unchanged. No forbidden desktop
controls appeared.

New cumulative-state recovery points are H operational backup
`e8ed422c-acd3-457a-b1fd-f433df6f6014` and X independent-local backup
`32c0136b-fa31-4659-87d0-206b6343fe26`. Both independently verify as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence and current DR
health are `PASS`; all earlier backups remain preserved.

The Batch-2 pipeline read catalogue fields only. It did not open media bytes, read EXIF
or video metadata, widen extractors, invent selected date components, resolve from
filesystem-only evidence, write/move/copy/rename/delete media, alter metadata, rehash,
regenerate similarity, run AI/Ollama, or access Z, NAS, or server. Normal RC5 preview
read one source read-only and wrote only its normal thumbnail cache.

M30 remains open and full preferred-date population is not complete. At the Batch-2
close, Batch 3 had not run and remained separately owner-gated; its deterministic
candidate was cursor 10000 with a maximum batch size of 5000. The subsequent separate
approval and bounded production run are recorded below.

## Production preferred-date population — Batch 3

The owner separately approved exactly one further deterministic production window.
Preflight at HEAD `c110326` found a clean worktree, schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact cumulative Batch-2 and legacy counts. Batch-2 recovery points H
`e8ed422c-acd3-457a-b1fd-f433df6f6014` and X
`32c0136b-fa31-4659-87d0-206b6343fe26` both independently revalidated as `ACCEPTED`.
Christmas and its three original Album events remained field-for-field exact.

Job `m30-production-preferred-date-batch3-v1` used cursor 10000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Configuration fingerprint
`ab5e64e7100e25f75d2a921d987ed62f17649fe39cbefbfc47c6d569bda2655b` selected
exactly 5,000 content-linked physical instances, actual IDs 10001–15000, with next
cursor 15000 and `end_of_catalogue=false`. Stored checkpoints independently confirmed
three contiguous, non-overlapping 5,000-ID windows from physical ID 1 through 15000.

The first run completed in 233.680 seconds at 21.397 physical items/second and
represented 3,851 content identities. It created 5,000 `filesystem_modified` evidence
rows and reused none. There were no filename-derived matches, invalid or ambiguous
filenames, errors, strong conflicts, needs-review states, or owner overrides. All 3,851
represented identities were Unknown with `weak_evidence_only`; Batch 3 newly resolved
zero identities and therefore found no dates outside 2026. The policy recorded 3,850
preferred-state changes and 1,150 unchanged physical-item applications. One represented
identity already had an Unknown projection; repeated or existing states did not append
duplicate events.

The identical job/cursor/config rerun completed in 0.432 seconds and skipped all 5,000
checkpoints. Evidence, preferred projections, basis links, jobs, job items, organisation
events, and unrelated counts had zero delta. The returned report remains cumulative over
the stored first-run payloads and therefore still displays the original created counts.

Cumulative production totals after Batches 1–3 are 15,373 evidence rows, 11,981
preferred projections, 12,358 preferred-basis links, three jobs, 15,000 job items, and
11,988 organisation events. Batch 3 appended exactly 3,850
`preferred_date_unknown` events. No Collection, Album, or Tag event was added.
Cumulative evidence comprises 15,000 `filesystem_modified` and 373
`filename_derived` rows.

The cumulative Year distribution remains 373 identities in 2026, 55,754 under Unknown
Date, and zero needs-review. Batch 3 newly resolved zero identities, leaving the
cumulative resolved count at 373. This remains a bounded population result, not a final
date-quality assessment. Measured query times were 57.782 ms for Year shelves, 21.990 ms
for one resolved 25-item page, 953.787 ms for one Unknown 25-item page, and 32.977 ms for
one preferred-date detail. The Unknown page was approximately 7.2% slower than Batch 2
and 14.1% slower than Batch 1; this upward trend was recorded without optimizing during
the production run.

A fresh canonical RC5 extraction passed the frozen production smoke and exited cleanly.
Production and DR health were `PASS`; Year and Unknown shelves loaded; zero needs-review
remained visible in the cumulative state; a resolved filename-derived detail and a
Batch-3 `weak_evidence_only` Unknown detail loaded; Collections were empty; History
filters worked; and the read-only preview source remained unchanged. No forbidden
desktop controls appeared.

New cumulative-state recovery points are H operational backup
`31842983-31f3-41fa-a15b-bb2313d06083` and X independent-local backup
`aaa0d333-6c3c-4e08-ac11-47f0dd5a18db`. Both independently verify as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence and current DR
health are `PASS`; all earlier recovery points remain preserved.

The Batch-3 pipeline read catalogue fields only. It did not open media bytes, read EXIF
or video metadata, widen extractors, use confidence as authority, fabricate date
components, replace owner selections, resolve from filesystem-only evidence,
write/move/copy/rename/delete media, alter metadata, rehash, regenerate similarity, run
AI/Ollama, or access Z, NAS, or server. Normal RC5 preview read one source read-only and
wrote only its normal thumbnail cache.

M30 remains open and full preferred-date population is not complete. At the Batch-3
close, Batch 4 had not run and remained separately owner-gated. The implementation
maximum and recommended bounded size remained 5,000, with candidate cursor 15000. The
subsequent separate approval and bounded production run are recorded below.

## Production preferred-date population — Batch 4

The owner separately approved exactly one further deterministic production window.
Preflight at HEAD `3ecbb86` found a clean worktree, schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact cumulative Batch-3 and legacy counts. Batch-3 recovery points H
`31842983-31f3-41fa-a15b-bb2313d06083` and X
`aaa0d333-6c3c-4e08-ac11-47f0dd5a18db` independently revalidated as `ACCEPTED`.
Christmas and its three original Album events remained field-for-field exact.

Job `m30-production-preferred-date-batch4-v1` used cursor 15000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Configuration fingerprint
`d48b57ae1928f6c5800ec5a0663a82ee704a12171e18a1425079f554a81de9ca` selected
exactly 5,000 content-linked physical instances, actual IDs 15001–20000, with next
cursor 20000 and `end_of_catalogue=false`. Stored checkpoints independently confirmed
four contiguous, non-overlapping 5,000-ID windows from physical ID 1 through 20000.

The first run completed in 240.913 seconds at 20.755 physical items/second and
represented 4,639 content identities. It created 5,941 evidence rows and reused none:
5,000 `filesystem_modified` and 941 `filename_derived`. All 941 filename matches were
valid and allow-listed; invalid or ambiguous matches, job errors, strong conflicts,
needs-review states, and owner overrides were zero. Filename evidence resolved 941
identities: 588 in 2024, 216 in 2025, and 137 in 2026. The remaining 3,698 represented
identities stayed Unknown with `weak_evidence_only`. The policy recorded 4,627 state
changes and 373 unchanged physical-item applications. Twelve represented identities
already had preferred projections, so the event/projection delta was smaller than the
distinct-identity count without creating duplicates.

The identical job/cursor/config rerun completed in 0.446 seconds and skipped all 5,000
checkpoints. Evidence, preferred projections, basis links, jobs, job items, organisation
events, and unrelated counts had zero delta. The returned report remains cumulative over
stored first-run payloads and therefore still displays the original created counts.

Cumulative production totals after Batches 1–4 are 21,314 evidence rows, 16,608
preferred projections, 17,926 preferred-basis links, four jobs, 20,000 job items, and
16,615 organisation events. Batch 4 appended 941 `preferred_date_resolved` and 3,686
`preferred_date_unknown` events. No Collection, Album, or Tag event was added.
Cumulative evidence comprises 20,000 `filesystem_modified` and 1,314
`filename_derived` rows.

The cumulative preferred Year distribution is 588 identities in 2024, 216 in 2025,
510 in 2026, 54,813 under Unknown Date, and zero needs-review. Batch 4 newly resolved
941 identities, bringing the cumulative resolved count to 1,314. This remains a bounded
population result, not a final date-quality assessment. Measured query times were
92.727 ms for Year shelves, 21.929 ms for one resolved 25-item page, 1,060.391 ms for
one Unknown 25-item page, and 33.040 ms for one preferred-date detail. Unknown-page
latency was approximately 11.2% slower than Batch 3 and 26.8% slower than Batch 1,
crossing one second; this meaningful upward trend was recorded without optimizing during
the production run.

A fresh canonical RC5 extraction passed the frozen production smoke and exited cleanly.
Production and DR health were `PASS`; four Year shelves loaded; the 2024 resolved page,
a Batch-4 filename-derived resolved detail, a Batch-4 `weak_evidence_only` Unknown
detail, and zero needs-review state were verified; Collections were empty; History
filters worked; and the read-only preview source remained unchanged. No forbidden
desktop controls appeared.

New cumulative-state recovery points are H operational backup
`bed203a2-f5f8-43f6-aec2-a1764dc8d0f0` and X independent-local backup
`37021bda-76e2-4b6e-afc3-7f5bfc456978`. Both independently verify as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence and current DR
health are `PASS`; all earlier recovery points remain preserved.

The Batch-4 pipeline read catalogue fields only. It did not open media bytes, read EXIF
or video metadata, widen extractors, use confidence as authority, fabricate date
components, replace owner selections, resolve from filesystem-only evidence,
write/move/copy/rename/delete media, alter metadata, rehash, regenerate similarity, run
AI/Ollama, or access Z, NAS, or server. Normal RC5 preview read one source read-only and
wrote only its normal thumbnail cache.

M30 remains open and full preferred-date population is not complete. At the Batch-4
close, Batch 5 had not run and remained separately owner-gated. Its candidate was cursor
20000 with the unchanged maximum size of 5,000. The subsequent separate approval and
bounded production run are recorded below.

## Production preferred-date population — Batch 5

The owner separately approved exactly one further deterministic production window.
Preflight at HEAD `fb2ab33` found a clean worktree, schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact cumulative Batch-4 and legacy counts. Batch-4 recovery points H
`bed203a2-f5f8-43f6-aec2-a1764dc8d0f0` and X
`37021bda-76e2-4b6e-afc3-7f5bfc456978` independently revalidated as `ACCEPTED`.
Christmas and its three original Album events remained field-for-field exact.

Job `m30-production-preferred-date-batch5-v1` used cursor 20000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Configuration fingerprint
`320d5d7b65bf6ff957b6e05f9cc16ff624f014c64cf2b92f865ef2b2ac3600d4` selected
exactly 5,000 content-linked physical instances, actual IDs 20001–25000, with next
cursor 25000 and `end_of_catalogue=false`. Stored checkpoints independently confirmed
five contiguous, non-overlapping 5,000-ID windows from physical ID 1 through 25000.

The first run completed in 235.387 seconds at 21.241 physical items/second and
represented 4,589 content identities. It created 5,277 evidence rows and reused none:
5,000 `filesystem_modified` and 277 `filename_derived`. All 277 filename matches were
valid and allow-listed; invalid or ambiguous matches, job errors, strong conflicts,
needs-review states, and owner overrides were zero. The report contained 277 represented
resolved identities and 4,312 Unknown identities with `weak_evidence_only`. Of the 277
resolved identities, 161 were newly resolved—3 in 2020, 19 in 2021, and 139 in 2022—
while 116 already-resolved 2024 identities were represented again. Years 2020, 2021,
and 2022 are new cumulative shelves. The policy recorded 4,471 state changes and 529
unchanged physical-item applications.

The identical job/cursor/config rerun completed in 0.425 seconds and skipped all 5,000
checkpoints. Evidence, preferred projections, basis links, jobs, job items, organisation
events, and unrelated counts had zero delta. The returned report remains cumulative over
stored first-run payloads and therefore still displays the original created counts.

Cumulative production totals after Batches 1–5 are 26,591 evidence rows, 21,079
preferred projections, 22,558 preferred-basis links, five jobs, 25,000 job items, and
21,086 organisation events. Batch 5 appended 161 `preferred_date_resolved` and 4,310
`preferred_date_unknown` events. No Collection, Album, or Tag event was added.
Cumulative evidence comprises 25,000 `filesystem_modified` and 1,591
`filename_derived` rows.

The cumulative preferred Year distribution is 3 identities in 2020, 19 in 2021, 139 in
2022, 588 in 2024, 216 in 2025, 510 in 2026, 54,652 under Unknown Date, and zero
needs-review. Batch 5 newly resolved 161 identities, bringing the cumulative resolved
count to 1,475. This remains a bounded population result, not a final date-quality
assessment.

Measured query times were 95.828 ms for Year shelves, 17.862 ms for one resolved 25-item
page, 1,023.902 ms for one Unknown 25-item page, and 33.895 ms for one preferred-date
detail. Unknown-page latency was 22.5% above Batch 1, 15.1% above Batch 2, 7.4% above
Batch 3, and 3.4% below Batch 4. It remains above one second and confirms the broader
upward trend despite the small improvement from Batch 4.

Read-only `EXPLAIN QUERY PLAN` and isolated timings identified the likely cause. The
Unknown service performs two expensive passes: its count and page queries each took
approximately 0.51 seconds. Both scan all content identities, probe the unique
preferred-date content-identity index, and execute the correlated representative-
physical-instance lookup, whose path uses `ix_physical_instances_content` but also a
temporary B-tree for its preferred-path ordering. The page then uses another temporary
B-tree for the preferred-month/day/content ordering before applying `LIMIT 25`. The
same page without global ordering took approximately 0.1 ms; preferred-field sorting
without the presentation joins took approximately 75 ms. Thus pagination and Album,
Tag, or Collection aggregation are not the primary cause. Increasing preferred rows can
add secondary index-probe cost, and the missing-or-non-resolved predicate prevents a
simple status-index range, but the dominant issue is duplicated full-path count/page
work plus correlated representative selection and sorting before the limit.

A fresh canonical RC5 extraction passed the frozen production smoke and exited cleanly.
Production and DR health were `PASS`; seven Year shelves loaded; a Batch-5
filename-derived resolved detail, a Batch-5 `weak_evidence_only` Unknown detail, and zero
needs-review state were verified; Collections were empty; History filters worked; and
the read-only preview source remained unchanged. No forbidden desktop controls appeared.

New cumulative-state recovery points are H operational backup
`ade478d6-0112-46df-a07f-292af193843a` and X independent-local backup
`921bb87f-d34a-4288-8a1c-12ea4cb40cd6`. Both independently verify as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence and current DR
health are `PASS`; all earlier recovery points remain preserved.

The Batch-5 pipeline read catalogue fields only. It did not open media bytes, read EXIF
or video metadata, widen or modify extractors, use confidence as authority, fabricate
date components, replace owner selections, resolve from filesystem-only evidence,
write/move/copy/rename/delete media, alter metadata, rehash, regenerate similarity, run
AI/Ollama, or access Z, NAS, or server. Normal RC5 preview read one source read-only and
wrote only its normal thumbnail cache.

M30 remains open and full preferred-date population is not complete. Batch 6 is not
automatically approved and was not run. Population pauses for owner review of the
Unknown-page performance trend. At the Batch-5 close, optimisation and clone validation
were required before any separately approved Batch 6. That work is recorded below.

## Unknown Date query optimisation before Batch 6

At HEAD `88bb2ec`, the schema-10 Unknown path in
`DesktopDataService._preferred_year_content` reused one enriched `FROM` clause for both
the authoritative count and the 25-row page. Consequently both queries scanned the
content-identity population, probed preferred projections, and ran correlated
representative-physical selection with a temporary sort. The page also globally sorted
the enriched Unknown population before applying its limit. On a disposable copy of the
accepted Batch-5 H backup, isolated legacy count runs took 523.981–562.137 ms, first-page
queries took 526.073–536.131 ms, and second-page queries took 518.626–535.336 ms. The
combined service path was approximately 1.0–1.1 seconds.

The query was restructured without a schema or index change. Unknown now means exactly
an explicit `unknown` preferred projection or no projection; `needs_review` remains on
its separate review path. The count query joins only content identities to the unique
preferred-date content-identity index and performs no representative, display,
aggregation, or sorting work. An ID-only query selects the deterministic
`content_identity_id ASC` page with `LIMIT/OFFSET`. A single third query enriches only
those bounded IDs. It retains the exact representative rule—prefer a non-null current
path, then the lowest physical-instance ID—and retains physical-instance and active-
Album counts without N+1 service calls. The three reads share one SQLite read
transaction. Schema-10 Year counts and derived Unknown Album presentation use the same
unknown-or-missing predicate.

Clone comparison against the legacy SQL was exact: total 54,652; first-page identities
374–398; second-page identities 399–423; all returned fields, statuses, representative
physical IDs and paths, pagination boundaries, and content-identity-level duplicate
semantics matched. Focused tests additionally cover missing and explicit Unknown rows,
resolved and needs-review exclusion, deterministic paging, unchanged representative
selection, empty results, and a 600-row synthetic extension that still uses exactly
three bounded SQL statements.

After optimisation, five-run count timings were 69.792–85.930 ms. Page-1 combined
service calls were 75.103–79.580 ms and page 2 was 76.330–86.456 ms. The isolated ID
stage took 0.079–0.240 ms and bounded enrichment 0.126–0.439 ms. A practical Library
refresh including Unknown content, derived year Albums, and all Albums took
82.798–87.692 ms. This meets the strong sub-150-ms target and is materially below the
Batch-5 production checkpoint of 1,023.902 ms.

Before optimisation, `EXPLAIN QUERY PLAN` showed full enriched scans, correlated
representative subqueries, a temporary B-tree inside representative selection, and a
second global temporary B-tree for page ordering; the count carried display joins it did
not need. After optimisation, the count retains the necessary content-identity scan and
indexed preferred-projection lookup but has no correlated subquery or temporary sort.
The ID stage scans identities in deterministic primary-key order, uses the same indexed
projection lookup, stops at the bounded page, and needs no temporary sort. Enrichment
operates as a co-routine over 25 constant rows. Its representative subquery and temporary
sort remain intentionally unchanged but are evaluated for only those 25 identities; its
final page-order sort is likewise bounded to 25 rows.

Thirty-two focused M30 desktop and usability tests passed, including rapid Year/Unknown
switching and stale-callback rejection, and Python compilation passed. Production was
read-only throughout: database size 329,912,320 bytes and UTC modification ticks
`639233591847645499` were unchanged, as were all Batch-5 evidence, projection, basis,
job/item, event, Year/Unknown, legacy, Collection, integrity, UUID, and Christmas values.
No preferred-date job or production evidence was added.

Canonical RC5 predates this source change and does not contain the optimisation. A
successor package/rebuild is required before owner-facing production testing or any
Batch-6 approval. No media was read by the optimisation or clone validation, and no
media mutation, rehash, similarity work, AI/Ollama, Z, NAS, or server access occurred.

M30 remains open. Batch 6 remains separately gated and was not run. After commit,
successor packaging, frozen/source read-only validation, and explicit owner approval,
the deterministic candidate remains cursor 25000 with a maximum size of 5,000.

## RC6 rebuild and frozen validation

RC6 (`0.1.0rc6`, Windows file/product version `0.1.0.6`) was built from base commit
`7544f72` as the schema-10 successor containing the Unknown Date query optimisation.
The canonical archive is
`H:\PersonalLibrarian\release\PersonalLibrarian-0.1.0rc6-win64.zip`: 66,927,533 bytes,
221 packaged files, ZIP SHA-256
`18F674E0D6D6E51C37FB7EB5F8BC2C3DCD1E44B661354866F8CC7D90CCF8613A`, and EXE
SHA-256 `74475F648E126DAE28A506544D2E2510CCE30E76E8D666901235135915E51554`.
RC6 expects schema 10 and introduces no migration. RC5 remains preserved as the
previous schema-10 release; RC4 remains historical schema-9 only.

A clean RC6 extraction passed frozen smoke against a disposable copy of the accepted
Batch-5 H backup. Overview, Library/Years, resolved shelves, Unknown Date, review state,
Collections, History, Exact, Similar, Decisions, Plans, Quarantine, and Backups/Recovery
were exercised; the process exited cleanly and read-only preview left its source
unchanged. Five frozen runs measured Unknown count at 89.495–115.815 ms, page 1 at
97.115–101.312 ms, page 2 at 95.954–106.790 ms, and the combined Library service
refresh at 123.897–129.676 ms. All are below the preferred 200-ms target.

Source/frozen comparison on that clone was exact: total 54,652; first-page identities
374–398; second-page identities 399–423; deterministic order, identity keys,
representative physical IDs and paths, preferred status/reason, and physical-instance
counts matched. Resolved and needs-review exclusion and content-identity duplicate
semantics remained unchanged. Bounded frozen Qt stress covered three rapid passes over
all eight main sections and all Library tabs plus repeated open/cancel of Album,
Collection, and preferred-date dialogs. Focused worker, preview-generation, stale-
callback, schema-10, M30 desktop, and packaging regressions passed 55 tests.

The same clean RC6 extraction then passed the production read-only smoke: schema 10,
production health `PASS`, DR health `PASS`, seven Year shelves, empty Collections,
Exact/Similar and history-backed sections, responsive process, and unchanged preview
source. Production frozen measurements were 82.544–89.171 ms for Unknown count,
89.856–94.894 ms for page 1, 90.255–94.338 ms for page 2, and 112.036–122.539 ms for
combined refresh. Before/after database size and mtime were identical at 329,912,320
bytes and `1787762384764549900` ns. Evidence 26,591; projections 21,079; basis 22,558;
jobs 5; job items 25,000; events 21,086; resolved 1,475; Unknown 54,652; needs review
zero; all legacy, Christmas, Album, Tag, and Collection values remained exact.

RC6 is therefore the canonical schema-10 production desktop candidate. No Batch 6,
date pipeline, catalogue/media mutation, rehash, similarity generation, AI/Ollama, Z,
NAS, or server access occurred. Normal preview alone read a source read-only and used
the existing thumbnail cache. M30 remains open, and Batch 6 remains a separate explicit
owner gate at cursor 25000 with a maximum size of 5,000.

## Production preferred-date population — Batch 6

The owner separately approved exactly one further deterministic production window at
clean HEAD `759f492`, using canonical RC6. Preflight confirmed schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact Batch-5, legacy, Christmas, Album, Tag, and empty-Collection baselines. The
post-Batch-5 recovery points H `ade478d6-0112-46df-a07f-292af193843a` and X
`921bb87f-d34a-4288-8a1c-12ea4cb40cd6` freshly reverified as `ACCEPTED` before the run.

Job `m30-production-preferred-date-batch6-v1` used cursor 25000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Its configuration fingerprint was
`3758f12fbc3fb4b77f52e43663896ef905619e649db81608ac24e748832b9a06`.
The deterministic selection contained exactly physical-instance IDs 25001–30000,
ordered ascending, with no overlap with Batches 1–5, next cursor 30000, and
`end_of_catalogue=false`.

The first run completed in 222.684 seconds at approximately 22.453 physical
items/second. It represented 4,713 content identities and created 7,208 evidence rows,
reusing none: 5,000 `filesystem_modified` and 2,208 valid allow-listed
`filename_derived`. Invalid or ambiguous filename matches, job errors, strong conflicts,
needs-review states, and owner overrides were zero. The represented final state was
1,934 resolved identities and 2,779 Unknown/`weak_evidence_only` identities. The policy
recorded 1,739 preferred-state changes and 3,261 unchanged physical-item applications.
No filesystem-only automatic resolution occurred.

The identical job/cursor/config rerun took approximately 0.09 seconds and skipped all
5,000 stored checkpoints. Evidence, projections, basis links, jobs, job items,
organisation events, and unrelated state had zero delta. The returned report is the
stored cumulative first-run report and therefore retains its original created metrics.

Batch 6 appended 1,739 preferred-date events: 1,134 `preferred_date_resolved` and 605
`preferred_date_unknown`. No Collection, Album, Tag, or other event was added. The
original three Christmas events and Christmas fields/members remained exact.
Cumulative totals after Batches 1–6 are 33,799 evidence rows, 22,818 preferred
projections, 25,431 basis links, six jobs, 30,000 job items, and 22,825 organisation
events. Cumulative evidence comprises 30,000 `filesystem_modified` and 3,799
`filename_derived` rows.

Batch 6 newly resolved 1,134 identities: 428 into the newly appearing 2023 shelf, 16
additional identities into 2024, and 690 additional identities into 2026. Cumulative
resolved distribution is 3 in 2020, 19 in 2021, 139 in 2022, 428 in 2023, 604 in 2024,
216 in 2025, and 1,200 in 2026. Total resolved is now 2,609, Unknown Date is 53,518,
and needs review remains zero.

A fresh clean RC6 extraction passed the post-Batch-6 production read-only smoke and
exited normally. Production and DR health were `PASS`; eight Year shelves loaded;
representative new resolved content 21081 showed policy-selected filename evidence;
representative new Unknown content 21080 showed `weak_evidence_only`; Collections were
empty; preferred-date History loaded; and preview left its source unchanged. Five-run
service timings were 102.204–104.615 ms for Year shelves, 16.789–20.763 ms for a
resolved 2023 page, 95.494–105.880 ms for an Unknown page, 27.426–31.638 ms for
preferred detail, and 120.360–125.495 ms for combined Library refresh. Additional frozen
checks measured Unknown count at 90.883–101.417 ms, first page at 101.987–118.615 ms,
second page at 100.200–102.070 ms, and combined refresh at 122.560–126.685 ms. The
optimisation remains materially faster than the former approximately one-second path.

New cumulative-state recovery points are H operational backup
`09503ac6-f59f-44ed-97a6-f42e83d218b1` and X independent-local backup
`491d2b0d-d978-4277-b581-e109f15cbb11`. Both independently reverified as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence is confirmed
and current DR health is `PASS`; earlier recovery points remain preserved.

The Batch-6 pipeline read catalogue fields only. It did not read media bytes or
EXIF/video metadata, widen extractors, invent date components, use confidence as
authority, replace owner selections, write/move/copy/rename/delete media, alter media
metadata, rehash, regenerate similarity, run AI/Ollama, or access Z, NAS, or server.
Normal RC6 preview was the only permitted media read and used the existing thumbnail
cache. M30 remains open. Batch 7 was not run and remains separately owner-gated; after
review, its deterministic candidate is cursor 30000 with the unchanged maximum size of
5,000.

## Production preferred-date population — Batch 7

The owner separately approved exactly one further deterministic production window at
clean HEAD `db4d530`, using canonical RC6. Preflight confirmed schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact Batch-6, legacy, Christmas, Album, Tag, and empty-Collection baselines. The
post-Batch-6 recovery points H `09503ac6-f59f-44ed-97a6-f42e83d218b1` and X
`491d2b0d-d978-4277-b581-e109f15cbb11` freshly reverified as `ACCEPTED`; production and
physically independent local DR health were `PASS` before the run.

Job `m30-production-preferred-date-batch7-v1` used cursor 30000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Its configuration fingerprint was
`0d53a52328ad7415e8050bf911a630ccfc63306610c694a982ab2449db6847ed`.
The deterministic selection contained exactly physical-instance IDs 30001–35000,
ordered ascending, with no overlap with Batches 1–6, next cursor 35000, and
`end_of_catalogue=false`.

The first run completed in 217.015 seconds at approximately 23.039 physical
items/second. It represented 4,852 content identities and created 5,438 evidence rows,
reusing none: 5,000 `filesystem_modified` and 438 valid allow-listed
`filename_derived`. Invalid or ambiguous filename matches, job errors, strong conflicts,
needs-review states, and owner overrides were zero. The represented final state was 438
resolved identities and 4,414 Unknown/`weak_evidence_only` identities. The policy
recorded 4,810 preferred-state changes and 190 unchanged physical-item applications.
No filesystem-only automatic resolution occurred.

The identical job/cursor/config rerun took approximately 0.123 seconds and skipped all
5,000 stored checkpoints. Evidence, projections, basis links, jobs, job items,
organisation events, and unrelated state had zero delta. The returned report is the
stored cumulative first-run report and therefore retains its original created metrics.

Batch 7 appended 4,810 preferred-date events: 436 `preferred_date_resolved` and 4,374
`preferred_date_unknown`. No Collection, Album, Tag, or other event was added. The
original three Christmas events and Christmas fields/members remained exact. Cumulative
totals after Batches 1–7 are 39,237 evidence rows, 27,627 preferred projections, 30,677
basis links, seven jobs, 35,000 job items, and 27,635 organisation events. Cumulative
evidence comprises 35,000 `filesystem_modified` and 4,237 `filename_derived` rows.

Batch 7 represented 438 resolved identities, of which 436 became newly resolved: 101
additional identities in 2022 and 335 additional identities in 2023. No new Year shelf
appeared. Cumulative resolved distribution is 3 in 2020, 19 in 2021, 240 in 2022, 763
in 2023, 604 in 2024, 216 in 2025, and 1,200 in 2026. Total resolved is now 3,045,
Unknown Date is 53,082, and needs review remains zero.

A fresh clean RC6 extraction passed the post-Batch-7 production read-only smoke and
exited normally. Production and DR health were `PASS`; eight Year shelves loaded;
representative newly resolved content 23227 showed policy-selected filename evidence;
representative new Unknown content 22819 showed `weak_evidence_only`; Collections were
empty; preferred-date History loaded; and preview left its source unchanged. Five-run
service timings were 123.307–128.103 ms for Year shelves, 15.887–18.608 ms for a
resolved 2022 page, 117.804–138.784 ms for an Unknown page, 27.411–31.661 ms for
preferred detail, and 144.093–153.946 ms for combined Library refresh. Additional frozen
checks measured Unknown count at 109.527–119.547 ms, first page at 118.520–135.150 ms,
second page at 118.198–125.481 ms, and combined refresh at 140.448–148.574 ms. This is a
modest increase from Batch 6 but remains well below 200 ms and materially faster than
the former approximately one-second path; no optimisation was performed during the
batch.

New cumulative-state recovery points are H operational backup
`69545c67-e92e-40e0-bc7f-ed0cdb4213e4` and X independent-local backup
`4fbb3246-2d46-453d-94d7-e00fc0f01666`. Both independently reverified as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence is confirmed
and current DR health is `PASS`; earlier recovery points remain preserved.

Exactly 35,000 of 69,444 physical instances, or 50.4%, have now been processed, leaving
34,444. The Batch-7 pipeline read catalogue fields only. It did not read media bytes or
EXIF/video metadata, widen extractors, invent date components, use confidence as
authority, replace owner selections, write/move/copy/rename/delete media, alter media
metadata, rehash, regenerate similarity, run AI/Ollama, or access Z, NAS, or server.
Normal RC6 preview was the only permitted media read and used the existing thumbnail
cache. M30 remains open. Batch 8 was not run and is not automatically approved; after
review, its deterministic candidate is cursor 35000 with the unchanged maximum size of
5,000.

## Production preferred-date population — Batch 8

The owner separately approved exactly one further deterministic production window at
clean HEAD `bcf0829`, using canonical RC6. Preflight confirmed schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact Batch-7, legacy, Christmas, Album, Tag, and empty-Collection baselines. The
post-Batch-7 recovery points H `69545c67-e92e-40e0-bc7f-ed0cdb4213e4` and X
`4fbb3246-2d46-453d-94d7-e00fc0f01666` freshly reverified as `ACCEPTED`; production and
physically independent local DR health were `PASS` before the run.

Job `m30-production-preferred-date-batch8-v1` used cursor 35000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Its configuration fingerprint was
`4f0cedd55a752721f5adb1c6c8b23eb01ccbcc502f16adc9d0191779fe931a12`.
The deterministic selection contained exactly physical-instance IDs 35001–40000,
ordered ascending, with no overlap with Batches 1–7, next cursor 40000, and
`end_of_catalogue=false`.

The first run completed in 219.123 seconds at approximately 22.818 physical
items/second. It represented 4,997 content identities and created 5,000 evidence rows,
reusing none, all `filesystem_modified`. Filename matches, invalid or ambiguous filename
matches, job errors, strong conflicts, needs-review states, and owner overrides were
zero. All 4,997 represented identities remained Unknown/`weak_evidence_only`; none
resolved. The policy recorded 4,990 preferred-state changes and 10 unchanged
physical-item applications. This window demonstrates the conservative rule directly:
filesystem-only evidence did not resolve any identity.

The identical job/cursor/config rerun took approximately 0.106 seconds and skipped all
5,000 stored checkpoints. Evidence, projections, basis links, jobs, job items,
organisation events, and unrelated state had zero delta. The returned report is the
stored cumulative first-run report and therefore retains its original created metrics.

Batch 8 appended 4,990 `preferred_date_unknown` events and no resolved event. No
Collection, Album, Tag, or other event was added. The original three Christmas events
and Christmas fields/members remained exact. Cumulative totals after Batches 1–8 are
44,237 evidence rows, 32,617 preferred projections, 35,667 basis links, eight jobs,
40,000 job items, and 32,625 organisation events. Cumulative evidence comprises 40,000
`filesystem_modified` and 4,237 `filename_derived` rows.

Batch 8 newly resolved zero identities, so no Year shelf or resolved count changed.
Cumulative resolved distribution remains 3 in 2020, 19 in 2021, 240 in 2022, 763 in
2023, 604 in 2024, 216 in 2025, and 1,200 in 2026. Total resolved remains 3,045,
Unknown Date remains 53,082, and needs review remains zero.

A fresh clean RC6 extraction passed the post-Batch-8 production read-only smoke and
exited normally. Production and DR health were `PASS`; eight Year shelves loaded; no
Batch-8 resolved representative existed; representative Batch-8 content 27628 showed
Unknown/`weak_evidence_only` with filesystem-modified evidence; Collections were empty;
preferred-date History loaded; and preview left its source unchanged. Five-run service
timings were 144.601–152.569 ms for Year shelves, 20.434–21.942 ms for a resolved 2023
page, 144.617–147.185 ms for an Unknown page, 29.471–34.382 ms for preferred detail,
and 164.546–172.930 ms for combined Library refresh. Additional frozen checks measured
Unknown count at 134.809–145.373 ms, first page at 143.211–156.796 ms, second page at
144.158–155.460 ms, and combined refresh at 166.569–192.578 ms. Latency continues its
upward trend, but every combined run remained below the stated 200-ms guard and far
below the former approximately one-second path. No optimisation was performed.

New cumulative-state recovery points are H operational backup
`24562844-4e1a-46d3-9216-c46c45f0979f` and X independent-local backup
`ba661fbf-1592-467b-b04b-c7e92b540182`. Both independently reverified as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence is confirmed
and current DR health is `PASS`; earlier recovery points remain preserved.

Exactly 40,000 of 69,444 physical instances, or approximately 57.6%, have now been
processed, leaving 29,444. The Batch-8 pipeline read catalogue fields only. It did not
read media bytes or EXIF/video metadata, widen extractors, invent date components, use
confidence as authority, replace owner selections, write/move/copy/rename/delete media,
alter media metadata, rehash, regenerate similarity, run AI/Ollama, or access Z, NAS,
or server. Normal RC6 preview was the only permitted media read and used the existing
thumbnail cache. M30 remains open. Batch 9 was not run and is not automatically
approved; after review, its deterministic candidate is cursor 40000 with the unchanged
maximum size of 5,000.

## Production preferred-date population — Batch 9

The owner separately approved exactly one further deterministic production window at
clean HEAD `141e452`, using canonical RC6. Preflight confirmed schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, no foreign-key violations, and
the exact Batch-8, legacy, Christmas, Album, Tag, and empty-Collection baselines. The
post-Batch-8 recovery points H `24562844-4e1a-46d3-9216-c46c45f0979f` and X
`ba661fbf-1592-467b-b04b-c7e92b540182` freshly reverified as `ACCEPTED`; production and
physically independent local DR health were `PASS` before the run.

Job `m30-production-preferred-date-batch9-v1` used cursor 40000, limit 5000, pipeline
`m30c-v1`, policy `preferred-date-policy-v1`, normalisation `partial-date-v1`, and the
unchanged version-1 catalogue and filename extractors. Its configuration fingerprint was
`a3ae1e7ce6aa1bb8de253ae0b5ef5419b56d55d079332088e7040c4cb093cb33`.
The deterministic selection contained exactly physical-instance IDs 40001–45000,
ordered ascending, with no overlap with Batches 1–8, next cursor 45000, and
`end_of_catalogue=false`.

The first run completed in 220.767 seconds at approximately 22.648 physical
items/second. It represented 4,992 content identities and created 5,000 evidence rows,
reusing none, all `filesystem_modified`. Filename matches, invalid or ambiguous filename
matches, job errors, strong conflicts, needs-review states, and owner overrides were
zero. All 4,992 represented identities remained Unknown/`weak_evidence_only`; none
resolved. The policy recorded 4,991 preferred-state changes and nine unchanged
physical-item applications. Filesystem-only evidence did not resolve any identity.

The identical job/cursor/config rerun took approximately 0.126 seconds and skipped all
5,000 stored checkpoints. Evidence, projections, basis links, jobs, job items,
organisation events, and unrelated state had zero delta. The returned report is the
stored cumulative first-run report and therefore retains its original created metrics.

Batch 9 appended 4,991 `preferred_date_unknown` events and no resolved event. No
Collection, Album, Tag, or other event was added. The original three Christmas events
and Christmas fields/members remained exact. Cumulative totals after Batches 1–9 are
49,237 evidence rows, 37,608 preferred projections, 40,658 basis links, nine jobs,
45,000 job items, and 37,616 organisation events. Cumulative evidence comprises 45,000
`filesystem_modified` and 4,237 `filename_derived` rows.

Batch 9 newly resolved zero identities, so no Year shelf or resolved count changed.
Cumulative resolved distribution remains 3 in 2020, 19 in 2021, 240 in 2022, 763 in
2023, 604 in 2024, 216 in 2025, and 1,200 in 2026. Total resolved remains 3,045,
Unknown Date remains 53,082, and needs review remains zero.

A fresh clean RC6 extraction passed the post-Batch-9 production read-only smoke and
exited normally. Production and DR health were `PASS`; eight Year shelves loaded; no
Batch-9 resolved representative existed; representative Batch-9 content 32618 showed
Unknown/`weak_evidence_only` with filesystem-modified evidence; Collections were empty;
preferred-date History loaded; and preview left its source unchanged.

The required 200-ms checkpoint did not pass. Nine service runs measured Year shelves at
183.166–205.634 ms with median 185.175 ms, a resolved 2023 page at 21.274–23.942 ms
with median 23.057 ms, an Unknown page at 181.575–261.047 ms with median 224.695 ms,
and preferred detail at 35.248–39.923 ms with median 37.217 ms. All nine combined
Library refresh runs exceeded 200 ms: range 278.432–296.764 ms, median 285.489 ms.
Frozen RC6 corroborated the result: all five combined refresh runs exceeded 200 ms,
range 270.506–291.126 ms, median 282.487 ms. Frozen Unknown count was
172.810–184.415 ms with median 174.654 ms; first page 183.326–204.219 ms with median
188.040 ms; second page 180.780–189.505 ms with median 186.079 ms. This is repeated,
consistent regression rather than an isolated outlier. No optimisation was performed.

New cumulative-state recovery points are H operational backup
`bf830d17-00e9-460b-9375-9331e0fcacbc` and X independent-local backup
`3553dcbf-f7a3-43a7-9f5b-2d3851add8ad`. Both independently reverified as schema 10,
`ACCEPTED`, integrity `ok`, and foreign-key clean. X device independence is confirmed
and current DR health is `PASS`; earlier recovery points remain preserved.

Exactly 45,000 of 69,444 physical instances, or approximately 64.8%, have now been
processed, leaving 24,444. The Batch-9 pipeline read catalogue fields only. It did not
read media bytes or EXIF/video metadata, widen extractors, invent date components, use
confidence as authority, replace owner selections, write/move/copy/rename/delete media,
alter media metadata, rehash, regenerate similarity, run AI/Ollama, or access Z, NAS,
or server. Normal RC6 preview was the only permitted media read and used the existing
thumbnail cache.

M30 remains open. Batch 10 was not run and is not automatically approved. Because the
combined service and frozen refresh paths are now consistently above 200 ms, population
is paused before Batch 10 for performance review. If that separate review restores and
validates acceptable performance, the deterministic next-window candidate remains
cursor 45000 with a maximum size of 5,000.

## Performance remediation after Batch 9

At clean HEAD `7f8ac39`, preflight reconfirmed production schema 10, catalogue UUID
`613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, zero foreign-key violations,
and the exact Batch-9 state. The latest recovery points H
`bf830d17-00e9-460b-9375-9331e0fcacbc` and X
`3553dcbf-f7a3-43a7-9f5b-2d3851add8ad` independently reverified as `ACCEPTED`, with
schema 10, matching UUID, integrity `ok`, and zero foreign-key violations. No production
write or date-evidence pipeline was run.

The Batch-9 performance failure came from two repeated full identity/projection probe
passes, not from evidence, basis, organisation-event, representative-path, Album, Tag,
Collection, preview, or Python transformation growth. The Year-shelf query grouped
resolved projections efficiently through
`ix_content_preferred_dates_status_year_content`, but computed Unknown by scanning all
56,127 content identities and point-probing the unique preferred-projection index. The
Unknown page service repeated the same full scan and point probe for its authoritative
count before its already-bounded ID selection and 25-row enrichment. Across the Year
shelf plus selected Unknown refresh, ten SELECT/WITH statements ran; two were duplicated
expensive full identity/projection passes. Organisation events and preferred basis were
not referenced by either plan.

On a disposable copy of the accepted Batch-9 H backup, nine-run source baselines broadly
reproduced the production shape. Year shelves took 152.756–259.110 ms, median 163.999 ms;
a resolved 2023 page took 11.679–14.226 ms, median 12.942 ms; Unknown first page took
157.077–176.219 ms, median 165.418 ms; second page took 167.393–196.646 ms, median
177.733 ms; preferred detail took 29.244–35.500 ms, median 30.431 ms; and the complete
Unknown content/derived-Album/all-Album service refresh took 180.554–201.589 ms, median
190.356 ms. This corroborated the previously recorded production and frozen medians of
285.489 and 282.487 ms, respectively, while reflecting a warmer local file cache.

The smallest source-only fix replaces both normal Unknown counts with equivalent
projection arithmetic: total content identities minus preferred projections whose
status is `resolved` or `needs_review`. Schema 10 permits exactly one preferred
projection per content identity and exactly the three states `resolved`, `needs_review`,
and `unknown`; therefore the result remains precisely missing projection plus explicit
Unknown. The Year query uses that expression beside its unchanged indexed resolved-year
grouping. The normal Unknown page uses it only for the authoritative count. The
`unorganised_only` branch retains its existing filtered identity/Album join, and ID-only
pagination, bounded enrichment, representative-instance ordering, physical-copy and
active-Album counts, display fields, and page order are unchanged. No cross-refresh
cache or mutable shared state was introduced.

No schema, migration, partial index, or existing-index change was required. Before,
`EXPLAIN QUERY PLAN` showed a covering scan of `content_identities` followed by a unique
`content_preferred_dates(content_identity_id)` lookup for every identity in each of the
two expensive counts. After, each count performs a sequential covering scan of the
content-identity key and a covering status probe through
`ix_content_preferred_dates_status_year_content`; there is no identity-to-projection
join or correlated subquery. The Year query retains only its eight-row final temporary
sort. Unknown ID selection retains its deterministic primary-key scan and projection
probe but stops at the requested page. Bounded enrichment intentionally retains the
representative physical-instance correlated lookup and small temporary sorts for only
25 identities. Total refresh statement count remains ten, while duplicated expensive
full point-probe scans fall from two to zero.

After the change, nine clone runs measured Year shelves at 13.564–18.568 ms, median
15.014 ms; Unknown first page at 14.131–18.147 ms, median 15.258 ms; second page at
13.525–18.327 ms, median 14.373 ms; and combined refresh at 29.831–33.555 ms, median
30.537 ms. Resolved-page and preferred-detail timings remained stable at medians 13.457
and 30.426 ms. A final source read-only check against production measured Year shelves
at 13.494–19.391 ms, median 14.650 ms; first Unknown at 13.963–16.197 ms, median
15.580 ms; second Unknown at 14.718–16.702 ms, median 15.918 ms; and combined refresh
at 30.134–32.319 ms, median 31.582 ms. Every post-change run is comfortably below the
200-ms hard gate and the 120-ms strong combined target.

Clone equivalence was exact. Before/after JSON digests matched for all Year names,
counts and ordering; Unknown total 53,082; first-page IDs 374–398; second-page IDs
399–423; representative physical IDs and paths; all display fields; resolved 2023 page
and total 763; needs-review zero; derived Albums; all Albums; and the combined refresh
result. Focused regression coverage additionally compares the arithmetic count with the
legacy join semantics, proves the Year count uses no join, preserves exactly three
bounded Unknown statements with no N+1, and retains the existing 600-row synthetic,
deterministic-pagination, representative-instance, empty-Unknown, status-separation,
and schema-9 compatibility cases.

Thirty-three focused M30 desktop/usability tests and 68 relevant schema-10,
date-evidence, Collection, organisation, and catalogue tests passed. Python compilation
passed. Existing Qt tests reconfirmed worker retention, generation guards, stale callback
rejection, rapid Year/Unknown and Collection switching, and preview binding. A source Qt
smoke on the disposable clone exercised all eight sections, loaded eight Year shelves
and a 25-item resolved page, exposed no forbidden controls, exited normally, and left
the one read-only preview source unchanged. The clone correctly reported backup health
`WARN`/DR `NOT_ASSESSED` because its disposable backup directories were intentionally
empty; this was not a production health result.

Production remained read-only and exact throughout. Database size and mtime were
unchanged at 379,183,104 bytes and `1787819936878623500` ns. Evidence remained 49,237;
preferred projections 37,608; basis links 40,658; jobs nine; job items 45,000;
organisation events 37,616; resolved 3,045; Unknown 53,082; needs review zero. Physical
instances remained 69,444; content identities 56,127; exact groups 7,707; similarity
groups 5,067; one active Christmas Album with description `owner-test`, two active
members and its original three events; Tags/content tags zero; and
Collections/memberships zero. Integrity remained `ok`, foreign keys zero, and UUID
unchanged.

RC6 predates this source fix and does not contain it. A successor RC7 package, followed
by frozen clone/source equivalence, frozen performance validation, and owner review, is
required before Batch 10 can be considered. RC7 was not built in this task. Batch 10 was
not run and remains unapproved. After commit and successful RC7 handling, the separate
deterministic candidate remains cursor 45000 with a maximum size of 5,000.

No media bytes were read except the optional read-only Qt preview, whose source was
unchanged. There was no media write, move, copy, rename, delete, metadata change, rehash,
similarity regeneration, AI/Ollama, Z, NAS, or server access. M30 remains open.

## RC7 rebuild validation blocked by History timestamp mismatch

An RC7 candidate (`0.1.0rc7`, Windows file/product version `0.1.0.7`) was built from
base commit `5cc9cb6` to package the preferred-date catalogue-count optimisation. The
local unsigned archive is
`H:\PersonalLibrarian\release\PersonalLibrarian-0.1.0rc7-win64.zip`: 66,927,653 bytes,
221 packaged files, ZIP SHA-256
`04503E6A4D03EAA45F775BE03B2FD40F4CC316382E47A146E9399533B25A3D59`, and EXE
SHA-256 `B612A025063EB6199A3E755C917B3E9E0B90AB2D32A2570CAF150A6EDBA4E623`.
It expects schema 10 and introduces no migration. RC4, RC5, and RC6 remain preserved.

Fifty-six targeted M30 desktop, worker/preview, schema-10, and release-packaging tests
passed, and Python compilation passed. A fresh extraction contained the expected 221
files. Its initial frozen clone smoke exited with code zero, reported frozen runtime,
loaded eight Year shelves and a resolved 2026 page, exposed all eight main navigation
sections, reported exact/Similar totals 7,707/5,067, exposed no forbidden controls, and
left its read-only preview source unchanged.

Seven-run source/frozen comparison on a disposable Batch-9-shaped clone was exact. The
complete semantic payloads had matching SHA-256
`6d641aaa618e5016becebe311658b8422922a2685a82601f2d95736ad3c76e92` and equal Year
names/counts/order, Unknown total and first/second pages, resolved sample page,
representative IDs/paths, preferred fields, Album presentation, empty Collections,
preferred-date History service output, and combined Library result. Frozen timings were
13.868–19.853 ms for Year shelves (median 15.285 ms), 14.205–16.828 ms for first
Unknown (median 15.412 ms), 13.698–18.578 ms for second Unknown (median 15.420 ms),
12.599–15.109 ms for the resolved page (median 13.785 ms), 28.854–34.067 ms for
preferred detail (median 29.535 ms), and 29.439–31.906 ms for combined refresh (median
29.918 ms). The performance and semantic gates therefore passed comfortably.

The required packaged high-risk Qt pass nevertheless found a release-blocking existing
History renderer mismatch. Schema-10 `organisation_events` and every populated
`DesktopDataService.desktop_history` domain return the timestamp as `recorded_at`, while
`LibraryPage._history_loaded` indexes `row["occurred_at"]`. Switching History to a
populated domain raised `KeyError: 'occurred_at'`. The service probe confirmed 37,616
all-domain and 37,613 preferred-date events have `recorded_at` and no `occurred_at`;
Albums/Tags has three rows with the same shape, while Collections is empty. The process
remained responsive, all eight dialog cancellations completed, and no worker remained,
but History rendering did not satisfy the RC7 acceptance criteria.

No application-code fix was made because this packaging task permits only required
release/version metadata and release-state documentation beyond the already committed
count optimisation. Per the required validation order, production RC7 smoke and
production RC7 performance measurements were not run after clone validation failed.
Production remained unchanged and was not opened by RC7.

This RC7 artefact is therefore a blocked local candidate, not canonical and not ready to
commit. RC6 remains the canonical schema-10 desktop; RC5 remains its earlier schema-10
predecessor and RC4 remains historical schema-9 only. A separately approved minimal
History timestamp-normalisation fix, focused regression, RC7 rebuild, full frozen clone
validation, and production read-only validation are required before RC7 can become
canonical. Batch 10 was not run and remains separately owner-gated at cursor 45000 with
a maximum size of 5,000. M30 remains open.

## Corrected RC7 History contract and final validation

The owner separately approved the minimal History timestamp-contract repair and rebuild
of the never-canonical blocked RC7. The stored schema-10 event contract remains
`organisation_events.recorded_at`; core organisation and Collection services continue
to expose that storage field. The established desktop presentation contract is
`occurred_at`, used by the Library renderer and other desktop history tables. The defect
was that `DesktopDataService` passed core rows through without normalising the field.

The narrow fix adds one desktop-facade normaliser. General/domain, Album, and Collection
History results now move the exact `recorded_at` text to `occurred_at` before returning
to Qt. The stored column, historical rows, ordering, filters, timestamp text, time zone,
and core services are unchanged; no schema migration, parsing, conversion, fabricated
time, or duplicate SQLite data was introduced. A defensive mismatch check rejects a row
only if both keys unexpectedly exist with different values.

Focused regression coverage uses populated preferred-date, Album, and synthetic
Collection histories. It verifies the desktop key, byte-equivalent source timestamp,
descending event-ID ordering, no duplicate event rows, empty compatibility behavior,
and direct Qt rendering without a timestamp exception. Fifty-four focused History,
M30 desktop, usability/worker-preview, organisation, and Collection tests passed before
rebuild, and Python compilation passed. Source Qt stress rendered default,
preferred-date, Albums/Tags, and Christmas Album histories; rapidly switched History
filters and main sections; exercised Year/Unknown and preview selection; rejected eight
dialogs; exited responsively; and drained all workers without an exception.

The superseded blocked-build evidence remains the ZIP SHA-256
`04503E6A4D03EAA45F775BE03B2FD40F4CC316382E47A146E9399533B25A3D59` and EXE
SHA-256 `B612A025063EB6199A3E755C917B3E9E0B90AB2D32A2570CAF150A6EDBA4E623`.
Those hashes are not canonical. The corrected RC7 (`0.1.0rc7`, raw Windows version
`0.1.0.7`) replaced the blocked output at
`H:\PersonalLibrarian\release\PersonalLibrarian-0.1.0rc7-win64.zip`. The final ZIP is
66,927,996 bytes with 221 packaged files, ZIP SHA-256
`8CB6621E0D02CA7B328E6B69466F5D31A7A35E0177E430D1E980C364D75E7FE8`, and EXE
SHA-256 `9A3A023C29610B4B6324FD46CD9C86C3EAA565022CE72CB4032D3EDC6C41FD4A`.
It is built from base `5cc9cb6`, expects schema 10, and introduces no migration. Both
final hashes differ from the blocked build.

A clean extraction contained 221 files. Frozen clone smoke exited with code zero,
reported frozen RC7, exposed all eight main sections and four Library tabs, loaded eight
Year shelves and a 25-item 2026 page, reported exact/Similar totals 7,707/5,067, exposed
no forbidden controls, and left the preview source unchanged. Source/frozen Library
payloads matched exactly with SHA-256
`b34872599d7f287ed1b5550ae18db9027e2003a0ddfe65281eec510e7d6e6540`.
Source/frozen History payloads also matched exactly with SHA-256
`42971b12f747be6a5a77f800b6250fed69c335a31015ed90cb8e93d0a8c27823`:
37,616 all-domain events, three Albums/Tags events, zero Collection events, 37,613
preferred-date events, and three Christmas Album events, with identical IDs, order,
timestamp text, types, actors, provenance, and details.

Seven frozen clone runs measured Year shelves at 15.018–19.111 ms, median 15.279 ms;
first Unknown at 16.727–24.779 ms, median 20.173 ms; second Unknown at
15.933–23.563 ms, median 17.359 ms; resolved 2023 at 11.996–14.880 ms, median
12.985 ms; and combined refresh at 31.292–34.709 ms, median 33.242 ms. Every combined
run remained far below the 100-ms preferred and 160-ms hard limits. The corrected
packaged high-risk pass repeated the formerly failing populated History path, rapid
domain switching, navigation away/back, all main sections, Year/Unknown switching,
previews, and eight dialog cancellations. It exited code zero with no traceback, exact
`occurred_at` presentation, responsive process, and zero remaining workers.

Only after all clone gates passed, fresh corrected RC7 ran against production read-only.
Production and independent-local DR health were `PASS`; eight Year shelves, resolved and
Unknown content, empty Collections, populated preferred-date and Christmas Album
History, Exact/Similar, preview, and all main sections loaded; preview left its source
unchanged; and the process exited normally. Seven production frozen runs measured Year
shelves at 13.870–19.308 ms, median 15.056 ms; first Unknown at 14.265–17.181 ms,
median 15.754 ms; second Unknown at 14.517–16.983 ms, median 15.206 ms; resolved 2023
at 12.060–14.707 ms, median 12.225 ms; and combined refresh at 28.808–34.086 ms,
median 30.433 ms.

Production remained exact. Database size and mtime stayed 379,183,104 bytes and
`1787819936878623500` ns. Evidence remained 49,237; projections 37,608; basis 40,658;
jobs nine; items 45,000; events 37,616; resolved 3,045; Unknown 53,082; needs review
zero; physical instances 69,444; identities 56,127; exact groups 7,707; similarity
groups 5,067; Album one with two active memberships; Tags/content tags zero;
Collections/memberships zero; and Christmas UUID, description `owner-test`, active
state, two members, and three events unchanged. Integrity remained `ok`, foreign keys
zero, and catalogue UUID unchanged.

Corrected RC7 is eligible to become the canonical schema-10 desktop after commit. RC6
and RC5 remain preserved schema-10 predecessors; RC4 remains historical schema-9 only.
Batch 10 was not run and remains a separate explicit owner gate. After commit, its
deterministic candidate remains cursor 45000 with a maximum size of 5,000. No production
evidence/job/event or catalogue mutation, media mutation, metadata change, rehash,
similarity work, AI/Ollama, Z, NAS, or server access occurred. Normal preview alone read
media read-only and wrote its normal cache. M30 remains open.

## Complete remaining production preferred-date population

The owner approved the remaining deterministic production windows from cursor 45000
through end of catalogue, with a maximum of 5,000 physical instances per independently
validated window. Preflight at clean HEAD `d02cc34` confirmed canonical corrected RC7,
schema 10, catalogue UUID `613affe5-a00b-49bc-9ad9-99b95adeec33`, integrity `ok`, zero
foreign-key violations, the exact Batch-9 cumulative and legacy baselines, unchanged
Christmas, and accepted post-Batch-9 H/X recovery points. Production and independent
local DR health were `PASS`.

### Batch 10

Job `m30-production-preferred-date-batch10-v1`, fingerprint
`77332945ae9b97bc52d7c23b18b282b830ccfe0b985d1d917ca6bc1f015de316`, used cursor
45000 and limit 5000. It selected exactly IDs 45001–50000 in ascending order, with zero
prior-checkpoint overlap, next cursor 50000, and `end_of_catalogue=false`. The first run
took 239.385 seconds, approximately 20.887 items/second. It represented 4,542 identities
and created 5,005 evidence rows: 5,000 `filesystem_modified` and five valid
`filename_derived`; it reused none and reported zero invalid/ambiguous matches. Four
represented identities resolved, 4,538 remained Unknown/`weak_evidence_only`, and none
needed review. There were 4,459 preferred-state changes, 541 unchanged applications,
four `preferred_date_resolved` events, and 4,455 `preferred_date_unknown` events. Strong
conflicts, job errors, owner overrides, and filesystem-only resolutions were zero.

The identical rerun took approximately 0.440 seconds and produced zero evidence,
projection, basis, event, job, or job-item delta. Post-window production health passed;
five combined Year/Unknown service runs were 46.392–55.538 ms. Recovery checkpoints H
`cb9f272b-f69a-4060-8f0d-bffb6429d2f9` and canonical X
`d7721324-8113-45b9-a03c-fd1a9f2a9f35` independently verified schema 10, `ACCEPTED`,
integrity `ok`, and FK zero; X device independence and DR health passed. An additional
valid independent backup `24194a70-64f4-4ef8-aa2f-386d0c9e310f` was conservatively
preserved after an initially over-specific X root placed it below the canonical DR
directory; it was not used as the canonical checkpoint and nothing was overwritten.

### Batch 11

Job `m30-production-preferred-date-batch11-v1`, fingerprint
`aa6242a8d0637f3d7c1a578f775057d3f8489c52d42197c290598797f5620f75`, used cursor
50000 and limit 5000. It selected exactly IDs 50001–55000 with zero overlap, next cursor
55000, and `end_of_catalogue=false`. The first run took 219.747 seconds, approximately
22.754 items/second. It represented 3,711 identities and created 6,251 evidence rows:
5,000 filesystem and 1,251 valid filename rows. It resolved 1,251 represented identities;
2,460 remained Unknown/weak-only; needs review, invalid matches, conflicts, errors,
owner overrides, and filesystem-only resolutions were zero. There were 3,201 state
changes, 1,799 unchanged applications, 1,251 resolved events, and 1,950 Unknown events.
The identical rerun took 0.425 seconds with every tracked delta zero. Production health
passed and combined refresh was 19.985–21.916 ms.

### Batch 12

Job `m30-production-preferred-date-batch12-v1`, fingerprint
`e1cb2dd5be6c1c2cf67f18d9d290ebae5a867f26479c0b26d6b90fcd76b8885c`, used cursor
55000 and limit 5000. It selected exactly IDs 55001–60000 with zero overlap, next cursor
60000, and `end_of_catalogue=false`. The first run took 219.468 seconds, approximately
22.782 items/second. It represented 4,886 identities and created 5,916 evidence rows:
5,000 filesystem and 916 valid filename rows. The represented final state was 922
resolved and 3,964 Unknown/weak-only. It recorded 3,307 state changes, 1,693 unchanged
applications, 916 resolved events, and 2,391 Unknown events. Invalid matches, review,
conflicts, errors, owner overrides, and filesystem-only resolutions were zero. The
identical rerun took 0.433 seconds with zero tracked delta. Health passed; combined
refresh was 19.750–25.297 ms.

Post-Batch-12 recovery points H `cddea950-8da6-4229-968b-b3d00b4b7abd` and X
`cfbc215c-8f74-4cda-a797-bc81699b5473` independently verified schema 10, `ACCEPTED`,
integrity `ok`, FK zero, matching SHA-256, and confirmed X device independence. DR
health passed with no rejected canonical independent backup.

### Batch 13

Job `m30-production-preferred-date-batch13-v1`, fingerprint
`c15cb7606fe76764d45ebdc210f345f4051e2de8b31074d393f48d0e11f8e59d`, used cursor
60000 and limit 5000. It selected exactly IDs 60001–65000 with zero overlap, next cursor
65000, and `end_of_catalogue=false`. The first run took 231.059 seconds, approximately
21.639 items/second. It represented 4,949 identities and created 7,394 evidence rows:
5,000 filesystem and 2,394 valid filename rows. The represented final state was 2,393
resolved and 2,556 Unknown/weak-only. It recorded 3,833 state changes, 1,167 unchanged
applications, 1,773 resolved events, and 2,060 Unknown events. Invalid matches, review,
conflicts, errors, owner overrides, and filesystem-only resolutions were zero. The
identical rerun took 0.434 seconds with zero tracked delta. Health passed; combined
refresh was 19.514–22.073 ms.

### Batch 14 and authoritative end of catalogue

Job `m30-production-preferred-date-batch14-v1`, fingerprint
`e235d9128753e953d2bd9bb40faee0e63994a753a0cd9189ae47e74f81eaa60a`, used cursor
65000 and limit 5000. The final partial window selected exactly 4,444 IDs 65001–69444,
with zero overlap, next cursor 69444, and the authoritative stored result
`end_of_catalogue=true`. The first run took 211.356 seconds, approximately 21.027
items/second. It represented 4,435 identities and created 6,578 evidence rows: 4,444
filesystem and 2,134 valid filename rows. The represented final state was 2,134 resolved
and 2,301 Unknown/weak-only. It recorded 3,720 state changes, 724 unchanged applications,
1,854 resolved events, and 1,866 Unknown events. Invalid matches, review, conflicts,
errors, owner overrides, and filesystem-only resolutions were zero. The identical rerun
took 0.455 seconds and changed no tracked count. No additional job was created merely to
probe EOF.

### Final reconciliation, RC7 validation, and recovery

All 69,444 eligible physical instances have exactly one completed checkpoint across 14
non-overlapping jobs. Job-item count and distinct checkpoint count are both 69,444;
uncheckpointed eligible instances, duplicate/excess checkpoints, invalid checkpoint
references, and overlapping windows are all zero. Population completion is 100%.

Final cumulative state is 80,381 date-evidence rows (69,444 filesystem-modified and
10,937 filename-derived), 56,127 preferred projections, 64,977 basis rows, 14 jobs,
69,444 job items, and 56,136 organisation events. There are 8,843 resolved identities
(15.755%), 47,284 Unknown/`weak_evidence_only` identities (84.245%), and zero needs
review. The six additional Unknown events beyond the final Unknown projection count are
auditable intermediate state changes; idempotency reruns added no events.

Final resolved Year shelves are: 2012: 14; 2013: 30; 2014: 258; 2015: 290; 2016: 789;
2017: 2,658; 2018: 686; 2019: 1,069; 2020: 3; 2021: 19; 2022: 244; 2023: 763;
2024: 604; 2025: 216; and 2026: 1,200. Unknown Date is 47,284. Batches 10–14 gained
respectively 4, 1,251, 916, 1,773, and 1,854 net resolved identities, 5,798 total. New
shelves introduced by these windows are 2012–2019; 2022 gained four identities.

Final History contains 8,843 `preferred_date_resolved`, 47,290
`preferred_date_unknown`, one `album_created`, and two `album_member_added` events.
Event UUIDs are unique; required event types, timestamps, and preferred links are
present. No Collection, new Album, or Tag event exists. SQLite storage remains
`recorded_at`; every sampled desktop History domain presents `occurred_at` only, in
descending event order. Christmas remains UUID `5336a05a-2148-4891-9d86-bb04a2db7e06`,
active, description `owner-test`, with two active members and its exact original three
events. Physical/content/exact/similar counts remain 69,444/56,127/7,707/5,067; Album
and active membership counts remain 1/2; Tags/content tags and Collections/memberships
remain zero. Integrity is `ok`, FKs zero, and catalogue UUID unchanged.

A fresh clean extraction of canonical corrected RC7 reverified ZIP SHA-256
`8CB6621E0D02CA7B328E6B69466F5D31A7A35E0177E430D1E980C364D75E7FE8` and EXE
SHA-256 `9A3A023C29610B4B6324FD46CD9C86C3EAA565022CE72CB4032D3EDC6C41FD4A`.
Its bounded frozen production smoke exited cleanly, reported frozen RC7, exposed all
eight main sections, loaded 16 shelves and a 25-item 2026 page, reported production and
DR health `PASS`, Exact/Similar 7,707/5,067, empty Collections, valid backup/recovery
state, no forbidden controls, and preview `PASS` with its source unchanged. Bounded
service validation separately loaded first/second Unknown pages, resolved detail, empty
Needs Review, Album, Collections, and all History domains.

Nine frozen production timing runs measured Year shelves at 21.698–29.421 ms (median
25.338), first Unknown at 23.396–29.275 ms (median 25.389), second Unknown at
23.224–27.766 ms (median 25.138), resolved 2026 at 23.838–30.628 ms (median 24.651),
preferred detail at 32.433–39.932 ms (median 35.455), and combined Library refresh at
45.564–58.696 ms (median 49.840). All combined runs passed the 160-ms gate and remain
far below the pre-remediation approximately 285-ms median.

Final recovery points are H operational `00b11a07-fef8-4c2d-8cc9-bc6d5e42aa7c` and X
independent-local `e581b8c3-b696-4cc4-8e6b-9ab02994047f`. Both freshly reverified as
schema 10, `ACCEPTED`, integrity `ok`, FK zero, with matching catalogue SHA-256
`b0a8bbab913a4f2a0ddc48fd1604dbcf7c5a8cfe3cd3d018e28a3e07b9007512`. X physical
independence is confirmed and final DR health is `PASS` with 16 valid canonical
independent backups and none rejected.

Across Batches 10–14 the pipeline configuration explicitly retained
`media_bytes_read=false` and read catalogue fields only. It did not read media bytes,
EXIF, video metadata, Google sidecars, or OneDrive capture metadata; did not mutate,
move, copy, rename, delete, rehash, or regenerate similarity for media; did not run
AI/Ollama; and did not access Z, NAS, or server. The normal RC7 preview was the sole
permitted read-only media access and left the source unchanged.

The M30 foundation and initial catalogue-only preferred-date production population are
complete and have no remaining engineering or data blocker in the defined scope. M30 is
formally complete as of 27 August 2026. Completed implementation and production state are
recorded by `47fcfef M30: complete production preferred-date population`; this document is
the formal close-out record. EXIF DateTimeOriginal, video capture timestamps, trusted
Google Photos metadata/sidecars, approved OneDrive capture metadata, richer semantic/AI
analysis, and physical media reorganisation remain explicitly outside this completed scope.
