# M27 - Library Organisation, Albums and AI Suggestion Policy

Date: 24 August 2026

Status: Draft architecture and policy for owner review; no implementation or operational authority

## Goals

This document is the authoritative design policy for long-term library organisation,
logical albums, low-value review, and future local-AI suggestions. It resolves the
architectural questions needed before schema design, AI classification, or physical
library restructuring begins.

The permanent organising principle is:

> Keep authoritative physical storage boring and stable. Put changing human meaning in
> the catalogue.

The governing sequence remains:

`Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act`

M27 defines future possibilities through Recommend and Approve. It performs none of
them. It creates no catalogue records, runs no AI, and authorises no physical action.

## Non-goals and authority boundary

M27 does not:

- move, copy, rename, delete, quarantine, or otherwise modify media;
- create physical album, semantic, event, person, place, or Dumpster folders;
- change schema 8 or implement the proposed entities below;
- classify production media, create embeddings, recognise faces, geocode items, or run
  Ollama;
- rescan, re-hash, or regenerate similarity evidence;
- grant AI authority to approve its own suggestion or alter owner metadata;
- change the M12 canonical model, M17 owner-decision lifecycle, M18 planning gates, or
  M19 quarantine/restore boundary; or
- make destructive action available at any automation level.

Unknown, uncertain, and deliberately unclassified are valid states. Organisation must
not require every item to have a date, place, event, person, topic, or album.

## Physical and logical organisation are different systems

### Physical authoritative storage

Physical organisation describes where the actual bytes are kept. It must be stable,
predictable, reconstructable from retained evidence, and minimally dependent on
interpretation. A change in an event name, AI model, place inference, person identity,
or owner preference must not cause continual file relocation.

Physical paths are custody facts, not the sole source of meaning. Original source and
path observations remain provenance even after a future authorised custody change.

### Logical organisation

Logical organisation is catalogue-driven. Albums, collections, dates, places, events,
people, types, topics, roles, classifications, review states, and AI suggestions are
relationships or metadata. One content identity may appear in many logical views while
its physical representations remain unchanged.

The two systems may be rebuilt independently: a catalogue can be reconstructed from
authoritative files and evidence, while logical organisation can change without
rewriting media paths.

### No rigid semantic folder hierarchy

Personal Librarian must not require structures such as:

`Year > Country > City > Event > People`

A photograph can involve two cities, several people, multiple events, and several
topics. Forcing those dimensions into one path creates arbitrary precedence, duplicate
copies, unstable moves, and information loss. Semantic organisation therefore belongs
in catalogue relationships by default. Physical paths may use only simple operational
dimensions with deterministic placement rules.

## Recommended future physical storage

The recommended managed layout is:

```text
PersonalLibrary
  Authoritative
    Photos
      YYYY
        MM
        UnknownMonth
      UnknownDate
    Videos
      YYYY
        MM
        UnknownMonth
      UnknownDate
  Imports
    <import-batch>
  Controlled
    Quarantine
```

This is a proposal, not an instruction to create or populate these folders.

### Recommendation and reasoning

- Use **year/month**, rather than year-only, when a sufficiently supported date is
  available. With more than 69,000 catalogue rows, month partitions avoid very large
  directories while remaining simple and familiar.
- Use `YYYY/UnknownMonth` when only a reliable year is known. Do not invent January or
  day precision.
- Use `UnknownDate` when no date has enough authority for physical placement. Unknown is
  preferable to a false date.
- Separate Photos and Videos because tooling, previewing, storage profiles, and future
  specialist applications differ. This is a stable technical distinction, not a
  semantic judgement.
- Keep `Imports/<import-batch>` as verified ingress before any separately approved
  promotion into authoritative storage. Import provenance continues in the catalogue
  after promotion.
- Treat `Controlled/Quarantine` as a separately governed custody area. It is not an
  album and it is not the Dumpster classification. Any movement must reuse the M18/M19
  safety architecture or a future explicitly approved extension.
- Do not encode source provider, country, event, people, topic, quality, canonical role,
  or Dumpster state in authoritative physical paths.

### Special-material placement

- **Screenshots:** store with Photos by a supported creation/capture date, or
  `UnknownDate`; expose Screenshot logically. Project screenshots and disposable UI
  captures share the same physical rule.
- **Scans:** the scan/digitisation timestamp is not automatically the depicted date.
  Use a reliable owner-supported original date if one exists; otherwise use
  `Photos/UnknownDate` and retain digitisation time separately.
- **Edited/exported variants:** remain separate content identities and follow the same
  time-based physical rule. Their original/edit/export relationships belong in the
  catalogue, not folder names.
- **Videos:** use the parallel Videos hierarchy and the same evidence policy.
- **Unknown or conflicting dates:** remain in `UnknownDate` until an authoritative
  catalogue decision supports a later, separately planned physical change.
- **Source/provenance:** never decides the final folder. It remains retained metadata
  and may drive logical views such as `Google Photos imports` or `Historical HDD`.

Physical promotion and later relocation require a future idempotent plan, collision
policy, verification, audit history, rollback strategy, and explicit owner authority.

## Organisation terminology and taxonomy

These concepts are distinct:

- **Tag:** one descriptive label, such as `pets` or `animation`.
- **Album:** explicit curated membership chosen by an owner or accepted from a
  suggestion.
- **Smart album:** stored query whose membership is computed from current catalogue
  facts.
- **Collection:** presentation-level grouping of albums or a broader thematic grouping;
  it need not create media membership of its own.
- **Event:** structured temporal/logical entity with dates, places, people, and notes.
- **Place:** structured geographic entity or place assertion with evidence.
- **Person:** structured owner-controlled identity, distinct from a detected face or
  anonymous cluster.
- **Classification:** owner/system assertion about media type, role, quality, or review
  disposition.

Not everything should become a generic tag. Structured concepts retain constraints,
evidence, confidence, and useful relationships.

### Independent organisation dimensions

| Dimension | Examples and required evidence treatment |
|---|---|
| Date/time | Capture date, precision, timezone state, source, confidence, and competing observations |
| Place | Country, region, city, venue, coordinates, source, confidence, and owner confirmation |
| Event | Holiday, birthday, trip, wedding, project, or owner-defined event; optional range and relationships |
| People | Named person, family, friend group, unknown person, or anonymous future cluster |
| Type | Photo, video, screenshot, scan, document photo, meme, artwork, download, edit/export, or unknown |
| Topic | Travel, home, pets, cars, work, animation, game development, hobbies, or owner-defined topic |
| Provenance | Camera/phone, OneDrive, Google Photos, Dropbox, historical HDD, messaging export, archive, and import batch |
| Role/quality | Original, edit, export, favourite, low-value, possible discard, archival canonical, or display/export canonical |

Dimensions are many-to-many where appropriate. Absence of a classification means
unknown, not false and not low-value.

## Date evidence policy

All observed dates remain separate evidence. A future preferred date is a reversible,
auditable catalogue assertion; it must not overwrite observations.

Potential evidence includes:

1. owner override with stated precision and rationale;
2. format-native capture metadata, including timezone state and parse provenance;
3. trusted source sidecars such as Google Takeout metadata;
4. source-system metadata retained during acquisition;
5. filename-derived dates with recorded parser and ambiguity;
6. filesystem creation and modification timestamps.

This order is not an unconditional precedence list. Owner override is authoritative for
the asserted scope, but each technical source must be assessed for reliability in
context. Embedded metadata can be wrong; sidecars can describe exports; filenames can
be ambiguous; filesystem times often describe copying rather than capture.

Every date assertion should record value, precision (year/month/day/time), timezone or
timezone-unknown, evidence source, confidence, extraction method/version, and conflicts.
Conflicting high-quality evidence routes to review. A year-only date remains year-only.
Filesystem modified time must never silently become capture truth.

## Places

Future place evidence may come from EXIF GPS, trusted sidecar/source metadata, an owner
assertion, an accepted event relationship, or low-confidence visual inference.

Coordinates and named places should be related but separately evidenced. Reverse
geocoding is an optional future enrichment and must retain provider/version and the
original coordinates. A visual statement such as “this looks like London” is only an AI
suggestion. It must not silently become authoritative location metadata. Owner-confirmed
places and reliable embedded/source evidence rank above inference.

## People and privacy

People are optional owner-controlled entities. Media may reference zero, one, or many
people; unknown people and unnamed groups are valid. Owner naming is distinct from
future face detection or clustering.

M27 does not authorise facial recognition. A future local-only, opt-in feature may
suggest anonymous clusters, but it must not silently assign a person's identity. The
owner confirms, rejects, splits, or merges clusters and may keep them unnamed. Person
tagging must never be required for ordinary organisation.

## Events

Events are first-class logical concepts. An event may have a stable ID, owner-visible
name, optional date range, places, people, description, provenance, and status such as
owner-created or AI-suggested. Media may belong to multiple events where reality
overlaps.

AI may suggest event clusters from temporal proximity, location, visual context, and
source context. Initially, only the owner may create/accept the event and its bounded
membership. For example, `Greece Trip - July 2025` may connect a date range, several
places, people, and an album without imposing those concepts on physical paths.

## Albums and collections

Albums are first-class logical entities. A content identity may belong to zero, one, or
many albums. Membership normally targets the content identity so exact physical copies
do not produce duplicate album entries. An explicit rendition/instance target may be
used only when presentation genuinely requires one and must not imply canonical status.

Initial album types are:

- manual owner album;
- event album;
- place album;
- people/family album;
- topic album;
- smart/dynamic album; and
- AI-suggested album pending owner resolution.

Albums may be shown inside presentation folders or collections. Do not require nested
album semantics: album membership remains direct and stable, while presentation
hierarchy may change independently. Avoid cyclic collection hierarchy.

Creating or accepting an album creates no physical media copy. Rename and description
changes are ordinary owner edits with audit history; membership additions/removals are
recorded or superseded rather than silently erased.

## Smart albums

A smart album stores a versioned, inspectable catalogue query and computes membership
dynamically. It does not materialise duplicate files or freeze AI guesses as facts.

Examples:

- `London 2024`: confirmed/preferred place is London AND preferred year is 2024;
- `Christmas 2023`: accepted event is Christmas 2023;
- `Screenshots`: effective media classification is Screenshot;
- `Possible Dumpster candidates`: unresolved effective disposition is Dumpster
  candidate; and
- `Undated scans`: effective type is Scan AND preferred date is unknown.

Query definitions require a version, owner/creator, creation time, included evidence
authority, and understandable explanation. Query changes preserve history. Results may
change as catalogue facts are approved, rejected, or superseded.

## Dumpster policy

Dumpster is initially a **logical, reversible review disposition**, never a synonym for
delete. Candidate material may include screenshots, memes, accidental captures, blurry
unusable images, duplicate exports, temporary downloads, app/UI captures, and low-value
generated/reference images. Category membership is evidence, not automatic judgement:
an app screenshot may be important project evidence and a technically poor family image
may be irreplaceable.

The proposed lifecycle is:

1. `Keep`
2. `Review`
3. `Dumpster candidate`
4. `Dumpster approved`
5. `Quarantined / physically isolated` through an authorised custody workflow
6. `Delete eligible` only under a separate future owner-approved deletion policy

States 1–4 are catalogue classifications. They do not move bytes. `Dumpster approved`
does not authorise M19 quarantine, and M19 quarantine does not mean low-value. A future
bridge must create an explicit action plan and satisfy the applicable M18/M19 or later
safety gates. There must be no second move/delete mechanism. Automatic deletion is
unavailable.

## AI suggestion policy

AI is a librarian assistant. Its default authority is suggestion only.

AI may eventually suggest media type/topic, albums, events, places, anonymous people
clusters, Dumpster candidates, rationale, and repeated owner patterns. It must not by
default move, copy, rename, delete, quarantine, approve its own suggestion, create
irreversible state, or silently replace owner metadata.

An album suggestion such as `Greece Trip - July 2019` should present bounded evidence:
284 target content IDs, a 7–18 July date cluster, Athens/Piraeus location evidence,
visual/source context, uncertainty, and exclusions. Owner actions are Accept, Rename,
Edit membership, Split, Merge, Reject, or Ignore. Rejection informs future suggestions
but does not become a hidden universal rule.

### Confidence bands

Confidence is policy-configurable and evidence-dependent. It is not a universal model
score or a blind numeric threshold.

| Band | Review treatment |
|---|---|
| Low | Show as an individual suggestion with uncertainty; no prioritised action |
| Medium | Prioritise for owner review and expose conflicting evidence |
| High | Permit a bounded batch recommendation for one explicit owner resolution |
| Very high plus explicit owner policy | May qualify for future reversible catalogue automation at the authorised scope only |

Confidence must account for evidence quality, model calibration, class-specific error
cost, novelty, contradictions, and similarity to reviewed owner examples. A confidence
band never increases physical-action authority by itself.

### Automation authority levels

| Level | Authority | M27 status |
|---|---|---|
| 0 — Observe | Local analysis may produce ephemeral diagnostics but no catalogue suggestion | Defined, not enabled |
| 1 — Suggest | Create auditable review suggestions | Defined, not enabled |
| 2 — Batch suggest | Group bounded similar suggestions for one owner approval | Defined, not enabled |
| 3 — Approved-rule automation | Apply only reversible catalogue classification where a versioned owner-created rule explicitly permits it | Future only |
| 4 — Reversible physical action | Use an explicitly authorised action plan and quarantine/rollback safety path | Future only; not granted to AI by M27 |
| 5 — Destructive action | Delete or otherwise irreversibly reduce custody | Unavailable and outside the current roadmap unless separately designed and approved |

Authority is capability- and scope-specific. Approval for screenshot classification does
not authorise place assignment, album creation, quarantine, or deletion. Promotion
between levels requires reviewed cases, validation, an explicit owner policy, audit and
rollback where applicable, and a fail-closed implementation milestone.

## Owner learning is explicit policy evidence

Personal Librarian must not rely on vague autonomous “AI memory.” Learning inputs are
versioned, inspectable evidence:

- approved and rejected classification/suggestion examples;
- owner-authored rules and exceptions;
- scoped preferences by media type, source, project, date range, or album;
- decision provenance and model/rule version; and
- superseded policies retained for audit.

Examples include “generic app screenshots usually go to Dumpster review,” “World of
Mayden screenshots are Keep,” “old family scans are Keep,” “unique low-resolution family
photos are not penalised,” and “exports may be secondary but are not disposable.”

The system should explain a recommendation in terms such as: “Suggested because 18
similar owner decisions under rule version 3 were approved; two project-related
exceptions were excluded.” It must show counter-evidence and permit rule correction,
scope narrowing, or deletion of a prospective rule without erasing historical decisions.

## AI provenance and auditability

Each future suggestion is immutable and should record:

- stable suggestion ID and suggestion type;
- model/runtime, model artefact identity, and relevant configuration;
- feature extractor, deterministic-analysis, prompt, policy, and rule versions;
- creation timestamp and processing run/checkpoint;
- confidence value/band and calibration context;
- target content identities and, only when needed, physical instances;
- evidence and source metadata used, including conflicts and missing data;
- concise human explanation;
- supersession/replacement links; and
- owner resolution as a separate immutable event.

Model changes create new observations or suggestions; they never overwrite prior AI
evidence or owner decisions. Current state is derived from retained history, consistent
with the M17 philosophy.

## Local AI architecture and visual-analysis safeguards

Ollama is locally available but is not integrated by M27. The likely future flow is:

```text
Catalogue and media evidence
  -> deterministic metadata / bounded feature extraction
  -> local AI analysis
  -> immutable suggestion record
  -> owner review
  -> resolution and explicit policy evidence
```

Deterministic evidence should be used before expensive inference. Future local visual
analysis may support screenshot detection, broad subject/category, blur/technical
quality, OCR/text presence, scene similarity, and event clustering.

## Resource policy

Safeguards are mandatory:

- local processing by default;
- bounded CPU/GPU/memory and concurrency;
- incremental unresolved/new-content queues;
- cached, versioned results rather than repeated whole-library processing;
- pause, resume, checkpoints, cancellation, and truthful progress;
- no silent reinterpretation after model upgrades;
- confidence, provenance, and explanation for every persisted suggestion; and
- no cloud dependency for core organisation.

The resource governor should make cost visible per run, prevent duplicate concurrent
work, and prioritise new or unresolved content over repeatedly processing the full
library.

## Privacy and local-first policy

People and location metadata are sensitive. Any future external AI, geocoder, or
integration must be optional, explicit about data sent, narrowly scoped, and separately
approved. Core albums, classifications, search, and owner review must remain usable
without a cloud AI service. Local processing is the default, not merely a fallback.

## Proposed future catalogue model — no migration in M27

The proposal extends schema 8 without replacing physical/content identity or M17–M19
history.

| Entity | Primary identity and purpose | History / authority policy |
|---|---|---|
| `albums` | Stable album ID; type, name, description, owner, lifecycle | Owner-visible fields mutable through append-only audit/supersession; AI proposal is not an accepted album |
| `album_memberships` | Album + content identity, optionally explicit rendition | Add/remove as immutable membership events or superseded intervals; record owner/rule/suggestion provenance |
| `collections` / `collection_albums` | Presentation hierarchy over albums | Mutable presentation with audit; prevent cycles; no implicit media semantics |
| `smart_albums` | Stable ID plus versioned query definition | Query revisions immutable/superseding; derived membership is not materialised truth |
| `tags` / `content_tags` | Stable tag ID and content relationship | Owner assignments authoritative; AI assignments remain suggestions until allowed by policy |
| `events` / `event_memberships` | Stable event ID, optional range/description, content membership | Owner edits audited; AI event proposals immutable; membership append/supersede |
| `places` / `content_places` | Stable place ID and evidence-backed content assertion | Preserve coordinates, names, source, confidence, authority, and supersession |
| `people` / `content_people` | Owner-controlled identity and content relationship | Sensitive/local; AI clusters distinct from named people; assignments audited |
| `metadata_observations` | Immutable date, type, place, source, technical, or extracted observation | Append-only with extractor/source/version; never overwritten by a preferred value |
| `preferred_metadata_values` | Owner/rule selection among observations or an explicit override | Append/supersede history; owner authority and rationale retained |
| `classifications` | Type, topic, role/quality, or Dumpster disposition assertion | Immutable assertion plus separate resolution/supersession; distinguish owner/system/AI authority |
| `ai_suggestions` | Stable immutable suggestion, target set, model/policy/confidence/explanation | Never updated into approval; owner resolution is a separate event |
| `ai_suggestion_evidence` | Suggestion-linked structured facts and conflicts | Immutable; references retained catalogue observations and versions |
| `ai_suggestion_resolutions` | Accept/rename/edit/split/merge/reject/ignore event | Append-only owner event; may create separately identified album/classification records |
| `owner_policy_rules` | Stable rule ID with scope, conditions, permitted effect, authority level | Versioned and superseded; enabled/disabled state audited; cannot exceed global capability gates |

Foreign keys should target content identities for semantic membership wherever possible.
Physical-instance references are reserved for provenance, custody, or explicit rendition
selection. Confidence, source, actor, timestamps, policy version, and unknown values must
be first-class rather than encoded in free text alone.

Normal organisation should remain usable: owner album renames and membership edits may
be presented as ordinary edits while the catalogue records compact append/supersede
history underneath. Immutable AI evidence and owner resolutions must never be rewritten.

## Interaction with canonical decisions and duplicate evidence

- **Canonical decisions** answer which physical/content representation is preferred for
  archival or display/export use.
- **Albums, tags, events, places, and people** answer what content means and where it
  appears logically.
- **Dumpster state** records owner review disposition.
- **Custody/quarantine** records where a physical instance is and how it moved.

These dimensions do not imply one another. Album membership never selects a canonical
copy. Dumpster approval never withdraws canonical status or authorises quarantine.

For exact duplicates, semantic membership normally belongs to the shared content
identity, producing one logical album item while all physical instances retain source
and custody evidence. A display/export canonical instance may be chosen later by the
existing M17 workflow, independently of membership.

Near duplicates remain separate content identities. AI may suggest that they share an
event/subject, or that they are alternate shots, edits, exports, or a burst series. It
must not merge them or copy album membership automatically merely because pHash/dHash
distances are low. Any multi-item membership suggestion remains reviewable and bounded.

## Example scenarios

| Scenario | Physical placement concept | Logical dimensions / albums | AI suggestion and owner action | Dumpster? |
|---|---|---|---|---|
| A. Family Christmas photo | `Photos/2023/12` when supported | Family, Christmas 2023 event, people, favourites | Suggest event album; owner confirms people and membership | No; technical quality alone cannot reduce personal value |
| B. Greece holiday | `Photos/2019/07` and parallel Videos path | Greece/Athens/Piraeus, travel, date range, trip event | Suggest `Greece Trip - July 2019`; owner renames to `Athens & Piraeus 2019`, edits membership | No by default |
| C. Random mobile screenshot | Date-based Photos path | Screenshot, phone provenance, no required album | Suggest Dumpster review based on bounded similar approvals; owner accepts/rejects | Candidate only until explicit owner resolution |
| D. Valuable game/app screenshot | Date-based Photos path, same as other screenshots | Screenshot, World of Mayden, game development, project album | Initial generic candidate is excluded by owner project rule; owner marks Keep | No |
| E. Downloaded meme | Date-based path if source date is supported, otherwise `UnknownDate` | Meme, downloaded image, web provenance | Suggest topic and Dumpster review with low personal-value evidence; owner decides | Possible candidate, never automatic delete |
| F. Old scanned family photograph | Usually `Photos/UnknownDate`; retain digitisation date separately | Scan, family, approximate decade, named people if confirmed | Suggest broad era/anonymous cluster; owner supplies year precision and names | No; unique scan remains valuable despite uncertainty/resolution |
| G. Edited/exported copy | Date-based Photos path as its own content identity | Edit/export role, relation to original, same event/albums where approved | Suggest original/edit relationship and possibly separate archival/display candidates; owner reviews | Not merely because it is an export |
| H. Blurry accidental photo | Date-based Photos path | Photo, technical blur observation, possible accidental-capture classification | Suggest Dumpster candidate with blur rationale; owner may Keep if meaningful | Possible candidate after owner review |

## Example AI conversations

### Bounded Dumpster review

**AI:** “I found 83 screenshots similar to files you previously marked as low-value.
Would you like me to create a Dumpster review group?”

**Owner:** “Yes, but keep screenshots related to World of Mayden.”

**System:** Creates one bounded catalogue suggestion, excludes project-related examples,
records the supporting decisions and exception rule version, and moves no files.

### Suggested trip album

**AI:** “284 photos appear to belong to a Greece trip in July 2019. The date cluster is
7–18 July and available location evidence points to Athens and Piraeus. Create album?”

**Owner:** “Yes, call it Athens & Piraeus 2019.”

**System:** Records the accepted/renamed suggestion and logical memberships. No physical
copies or folders are created.

## Staged implementation roadmap

1. **Policy approval:** resolve the deferred owner choices below and accept M27 without
   changing schema or media.
2. **Catalogue design milestone:** specify and migrate the smallest manual organisation
   foundation—metadata observations, preferred values, albums, memberships, events,
   classifications, and audit history—using temporary validation before production.
3. **Manual desktop workflow:** owner-created albums, tags/classifications, smart-album
   queries, explicit corrections, and read-only provenance; no AI required.
4. **Deterministic enrichment:** bounded date/type/provenance extraction with cached,
   versioned observations and conflict review.
5. **Local AI pilot:** Level 1 suggestions on a small reviewed sample, with resource
   limits, immutable provenance, calibration, and no production-wide analysis.
6. **Owner-learning pilot:** explicit examples/rules, explanations, exception handling,
   and evaluation against held-out reviewed cases.
7. **Optional authority review:** consider Level 2 or narrowly scoped Level 3 catalogue
   automation only after real evidence and separate owner approval.
8. **Physical organisation planning:** only after logical organisation is proven; design
   a dry-run, verified, reversible promotion/move workflow. Level 4 remains a separate
   future authority decision. Level 5 remains unavailable.

## Deferred decisions requiring owner input

None of these decisions blocks acceptance of M27 as a policy foundation. They must be
resolved before the corresponding implementation is authorised:

1. **DEFERRED — physical date gate:** exact evidence/confidence needed before a date may
   determine `YYYY/MM` physical placement, including timezone and conflict rules.
2. **DEFERRED — managed-root timing:** whether and when existing staging material should
   ever be promoted into the proposed authoritative layout.
3. **DEFERRED — import retention:** how long verified import-batch structure remains
   physically intact after any future promotion.
4. **DEFERRED — scans/documents:** whether document-like images remain in the media
   library, receive a specialist logical view, or later integrate with Paperless-ngx.
5. **DEFERRED — album presentation:** exact collection-folder depth and naming rules;
   semantic album nesting is not required.
6. **DEFERRED — people features:** whether local anonymous face clustering is acceptable
   at all, and the opt-in/privacy/retention rules if introduced.
7. **DEFERRED — geocoding:** whether any external reverse-geocoding provider may be used;
   local/embedded evidence remains sufficient for the core system.
8. **DEFERRED — confidence calibration:** model/class-specific validation sets, numeric
   thresholds, and error tolerances. No universal thresholds are approved here.
9. **DEFERRED — automation promotion:** evidence and owner approval needed to enable any
   Level 1–4 capability operationally. M27 enables none.
10. **DEFERRED — Dumpster retention/deletion:** retention time, quarantine eligibility,
    restore expectations, and any future destructive policy. Delete remains unavailable.

## M27 completion boundary

This document proposes policy and future catalogue architecture only. Schema remains 8.
No AI model, catalogue suggestion, album, classification, decision, plan, file action,
or physical layout is created. Production media and application data remain unchanged.

## Owner-approved policy decisions

Approved by the owner on 24 August 2026.

These decisions resolve the principal owner-policy questions deferred during the initial M27 draft.

### 1. Authoritative physical structure

The future managed authoritative media library will use a stable date-based physical structure.

Preferred layout:

Authoritative/
  Photos/
    YYYY/
      MM/
  Videos/
    YYYY/
      MM/

Special handling will exist for uncertain or unavailable dates, including UnknownMonth and UnknownDate.

Semantic concepts such as place, event, people, project, topic, holiday or family grouping do not determine authoritative physical paths.

They belong to the logical catalogue layer.

### 2. Imports are temporary batch-based staging

New acquisitions will enter through batch-oriented import staging.

Example:

Imports/
  <ingestion-batch>/

An import batch remains intact until:

1. ingestion has completed;
2. resulting catalogue evidence has been verified;
3. authoritative media custody has been verified where applicable;
4. required backup coverage exists.

Original import material does not become eligible for cleanup merely because ingestion completed.

Any later retirement of an import batch requires a separately approved retention policy and explicit safety workflow.

### 3. Scans and document photographs are routed by meaning

Routing depends on what the material fundamentally represents rather than the capture mechanism.

Examples:

- scanned family photograph -> Photos;
- scanned historical photographic print -> Photos;
- photograph of a letter -> Documents;
- receipt photograph -> Documents;
- official form/document photograph -> Documents;
- screenshot retained primarily for documentary information -> Documents.

Ambiguous material remains reviewable rather than being forced automatically.

### 4. Year is the primary owner-facing browse axis

Year is the most important high-level organisational view for the owner.

Within a year, Personal Librarian may present logical sub-groupings such as:

- trips;
- events;
- places;
- family occasions;
- projects;
- topics;
- albums.

Example logical presentation:

2025
  Greece Trip
  Christmas
  London
  Family
  World of Mayden

These are logical catalogue groupings and do not imply equivalent physical folders.

Album presentation hierarchy should remain shallow and flexible.

The owner retains final approval when physical organisation is eventually implemented.

### 5. Optional local face clustering is permitted

Future local face clustering may group visually recurring faces anonymously.

Rules:

- feature is optional;
- processing remains local by default;
- anonymous clusters may be suggested automatically;
- actual identity assignment is owner-controlled initially;
- AI must not silently name people;
- face recognition is not required for core library operation.

### 6. Optional external geocoding is permitted

Future external reverse-geocoding may be supported on an explicit opt-in basis.

Rules:

- embedded GPS/local metadata is preferred first;
- external requests should use coordinates only;
- image contents must not be uploaded for geocoding;
- returned place information is derived evidence, not unquestioned truth;
- owner correction overrides derived location evidence;
- core organisation must remain usable without an external geocoding service.

### 7. AI confidence is task-specific

Personal Librarian will not use one universal confidence threshold for all AI work.

Confidence must be calibrated per task and evidence type.

Conceptual bands remain:

- Low -> suggestion only;
- Medium -> prioritised owner review;
- High -> batch suggestion may be appropriate;
- Very High -> still does not grant physical authority by itself.

A confidence value alone never permits physical action.

Any future automation additionally requires an explicit owner-approved policy rule.

### 8. Automation authority is promoted gradually

Automation authority follows staged promotion.

Conceptual progression:

- Level 0 - Observe;
- Level 1 - Suggest;
- Level 2 - Batch suggest;
- Level 3 - owner-authorised reversible catalogue automation;
- Level 4 - separately approved reversible physical action through the established action/quarantine safety architecture;
- Level 5 - destructive action remains unavailable.

Catalogue-only automation may therefore mature before any physical authority is considered.

Any move/quarantine authority requires a separate future milestone and explicit owner approval.

### 9. Dumpster remains reversible indefinitely

Dumpster does not mean delete.

Current intended progression:

Keep
Review
Dumpster candidate
Dumpster approved
Quarantined

No automatic retention expiry is approved.

No 30-, 60- or 90-day deletion timer is approved.

Items may remain recoverable indefinitely.

Any future delete-eligibility or retention policy requires a separate design and explicit owner approval.

### 10. Personal Librarian will eventually own the managed authoritative root

The long-term objective is for Personal Librarian to maintain its own managed authoritative media root rather than permanently depending on historical source locations.

Migration will occur only through a separate verified milestone.

Required migration principle:

Discover / select
  ->
Copy into managed authoritative root
  ->
Verify content and metadata evidence
  ->
Verify backup coverage
  ->
Owner approval
  ->
Only then may legacy source copies become eligible for separate retirement review

Migration must never be implemented as an unverified bulk move.

Historical source locations remain evidence until their retirement is explicitly approved.

## Resulting M27 policy baseline

The approved baseline is therefore:

- stable physical custody;
- Photos/Videos -> YYYY -> MM;
- year-centred owner browsing;
- logical albums and semantic groupings independent of physical paths;
- temporary provenance-preserving Imports;
- semantic Photos/Documents routing;
- optional local face clustering;
- optional opt-in coordinate-only geocoding;
- task-specific AI confidence;
- staged and explicitly authorised automation;
- indefinitely reversible Dumpster handling;
- eventual managed authoritative custody through a separately approved migration milestone.

No part of these approvals authorises production-media reorganisation during M27.
