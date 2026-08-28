# M12 - Organisation & Canonical Copy Policy Foundation

Date: 20 August 2026

Status: Draft policy foundation; not authorised for file-changing operations

## Purpose and authority

This document defines the conservative policy foundation for logically organising verified library material and nominating preferred canonical copies. It is a design contract for later milestones, not an implementation specification or authority to change files.

The governing sequence remains:

`Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act`

The programme serves the library. The library does not belong to the programme.

Nothing in M12 authorises moving, renaming, deleting, consolidating, quarantining or altering source media. M10 exact-duplicate results and M11 perceptual-similarity results are evidence only.

Personal Librarian is not yet an application. M12 remains policy and design only; implementation begins in future application-foundation and catalogue milestones. Detailed scoring, date precedence, physical organisation and operational quarantine rules remain deferred.

## Policy principles

- Preservation and recoverability take priority over tidiness or storage savings.
- Logical catalogue decisions must remain separate from physical file operations.
- Recommendations must be explainable from retained evidence.
- Subjective or ambiguous decisions belong to the owner.
- No canonical nomination removes an original or weakens its provenance.
- File-changing operations require later, explicit authority, verification, audit and rollback controls.
- A failure to classify an item is safer than a confident but unsupported classification.

## Canonical-copy concept

A **content identity** represents a particular byte sequence, identified by a valid SHA-256 hash. A **physical instance** is one occurrence of that content at a source or staging path. Exact duplicates may therefore be multiple physical instances of one content identity.

A **canonical copy** is the preferred instance or preferred content identity for a defined purpose, such as display, export or logical organisation. It is not an instruction to delete, overwrite or hide alternatives.

The owner has approved two separate canonical scopes:

- **Archival canonical:** the preferred representation for preservation, generally intended to represent the best or original archival form.
- **Display/export canonical:** the preferred representation for normal viewing, sharing, export, albums or downstream applications.

The two scopes may reference the same file or different files. Both are reversible catalogue-metadata decisions; neither implies deletion. All source instances and provenance remain preserved. No ranking or automatic nomination is authorised.

Every canonical nomination requires explicit owner approval, including nominations among verified SHA-256-identical copies and nominations for either canonical scope. Exact SHA-256 identity is strong evidence of content identity but does not authorise a canonical decision. Future automation may be introduced only after real reviewed cases exist, the proposed behaviour has been validated, and explicit owner-approved automation rules have been defined.

- One item may be nominated as preferred while every original remains preserved.
- Canonical status is catalogue metadata and must be reversible.
- A canonical nomination must state its scope and rationale. A preferred instance for provenance or safekeeping need not be the preferred rendition for viewing.
- Replacing or withdrawing a nomination must preserve the earlier decision and reason in an append-only audit history.
- Every physical instance retains its original-source and path provenance regardless of canonical status.
- If evidence is insufficient or conflicting, no canonical item should be selected.

## Candidate-selection evidence

Evidence must be recorded separately from the decision derived from it. Missing evidence must be represented as unknown, not as a negative value.

### Reliable evidence

Reliable evidence is objective and reproducible, although it may not by itself determine preference.

- successful media parsing or decoding, including recorded tool and result
- valid SHA-256 identity for byte-for-byte equality
- pixel dimensions, duration and other format-native technical properties
- file size, when compared within an appropriate format and rendition context
- embedded metadata fields as observed, without assuming that their values are correct
- filesystem and embedded timestamps, each labelled by source and timestamp type
- acquisition source, import batch and original relative path
- number and location of physical instances for the same SHA-256 content
- M11 perceptual-hash values and distances as similarity measurements, not identity proof

### Weak or contextual evidence

Weak evidence may contribute to a recommendation but must not decide canonical status alone.

- a larger resolution or file size, which may indicate quality, upscaling, padding or inefficient encoding
- metadata richness, because exports and editing tools may add, remove or rewrite metadata
- EXIF capture time when not corroborated or when timezone information is absent
- filesystem created or modified times, which commonly change during copies and exports
- filename quality or apparent sequence
- source labels such as Google Takeout, OneDrive, Dropbox or historical storage
- apparent original versus exported, edited or recompressed status inferred from naming, encoding or metadata
- duplicate copy count, which measures prevalence rather than authenticity or quality
- close perceptual similarity, including low pHash and dHash distances

### Evidence requiring owner judgement

The following questions are semantic, personal or preference-dependent and require review unless the owner later approves a narrowly defined rule:

- whether an edit is preferable to the original capture
- which image best represents a burst, event or memory
- whether a crop, filter, annotation or lower-resolution shared copy has independent value
- whether a screenshot or document-like image should be retained and how it should be classified
- whether filenames, albums, source folders or historical arrangements carry meaningful context
- event, place or people labels when evidence is ambiguous
- conflicts between technical quality, historical provenance and aesthetic preference

Evidence from Google Takeout, OneDrive, Dropbox and historical sources must be treated as provenance context. No source class is inherently superior. Google Takeout sidecar metadata may help interpret an export but does not by itself make that export canonical. Likewise, a historical-source path may contain important context even when an exact copy exists elsewhere.

## Exact duplicates

M10 exact duplicates must eventually be modelled as:

- one content identity keyed by valid SHA-256;
- one or more physical instances, each with its own source and path provenance;
- zero or one preferred physical instance for a stated scope;
- retained provenance and status for every instance, including unavailable or later quarantined instances; and
- an explicit relationship between each instance and the shared content identity.

Canonical nomination does not change bytes or delete copies. A preferred physical instance may be suggested using operational evidence such as verified readability, stable availability and trustworthy provenance. Filename, location or source prestige alone is insufficient. If instances are byte-identical, image quality is also identical; preference is then about provenance and operational suitability, not media quality.

M10's potential reclaimable-space figure is planning evidence only. Space recovery requires a separate future policy and explicit approval.

## Near duplicates

M11 candidates remain separate content identities because their SHA-256 values differ. They must be represented by similarity relationships containing the methods, hash values, distances, thresholds, analysis version and group membership used to discover them.

- Near-duplicate grouping is a review aid, not a consolidation rule.
- Each candidate retains independent provenance and lifecycle state.
- A relationship may describe likely rendition, edit, burst, screenshot-layout similarity or an unknown similarity type; it must not assert identity without review.
- Large connected groups, especially screenshot and repeated-layout clusters, are low-confidence structural evidence.
- Transitive group membership does not mean that every member is similar to every other member.
- Perceptual hashes must never directly authorise deletion, replacement, quarantine or canonical selection.

## Logical organisation model

Organisation should first be expressed as catalogue metadata and views. An item may appear in several logical collections without being copied or moved, and no logical label should imply a physical path.

### Core logical facets

- **Capture date:** the best-supported date value plus its source, precision, timezone status and confidence.
- **Calendar views:** year and month/date views derived from the chosen date without embedding that choice into a physical path.
- **Events:** owner-defined or suggested collections with optional date ranges, places and notes; items may belong to multiple events.
- **Places:** structured or free-text location evidence with source and confidence; ambiguous coordinates or place names require review.
- **Media class:** photo, video, screenshot, scan/document-like image, other media, or unknown.
- **Source/import:** original source, acquisition batch and historical folder context.
- **Review collections:** exact-duplicate sets, near-duplicate groups, undated items, unreadable items and other exception queues.
- **People:** optional future classifications only, subject to separate privacy, consent and accuracy policy.

### Date handling

All candidate dates must be retained with their origins rather than collapsed into a single unexplained value. The catalogue may later nominate a preferred capture date, but it must preserve competing EXIF, sidecar, filename-derived and filesystem values. Unknown dates belong in an explicit **Undated** view; uncertain year-only or month-only dates must not be given invented precision.

### Special material

- Screenshots should remain first-class library items and may be grouped in a logical Screenshots view.
- Files carrying image extensions that do not decode as images must be classified as unreadable, document-like or unknown based on evidence; extensions must not dictate destructive treatment.
- Zero-byte placeholders and unavailable content remain recorded as exceptions with provenance.
- Imports and historical folder structures must remain discoverable even when richer organisation labels are added.

Any later physical-storage layout is an implementation choice. It must not become the sole carrier of dates, events, places or provenance.

## Review and lifecycle states

Decision status, canonical role and custody status are separate dimensions. Keeping them separate avoids contradictory states such as treating "quarantined" as an opinion about quality.

### Decision status

| State | Meaning | Allowed transition principle |
|---|---|---|
| Unreviewed | No recommendation has been assessed | Analysis may create a suggestion |
| Suggested | A recommendation exists with evidence and rationale | Owner or authorised later workflow may approve or reject |
| Approved | The recommendation was explicitly accepted | May be withdrawn or superseded with an audit record |
| Rejected | The recommendation was explicitly declined | May be reconsidered without erasing the rejection history |
| Needs manual review | Evidence is conflicting, incomplete or inherently subjective | Returns to Suggested only with new rationale/evidence |

### Canonical role

| State | Meaning |
|---|---|
| Unassigned | No preferred role is recorded |
| Canonical | Preferred item for a stated scope following approval |
| Alternate | Preserved non-preferred rendition or instance linked to a canonical item |

An Alternate is not inferior, disposable or hidden by default. Canonical and Alternate assignments are reversible catalogue decisions.

### Custody status

| State | Meaning |
|---|---|
| In place | Instance remains at its recorded current location |
| Quarantine proposed | A future custody change has been recommended but not performed |
| Quarantined | Instance was moved by an authorised later workflow to a controlled, recoverable location |
| Restored | A quarantined instance was returned or otherwise restored through rollback |
| Unavailable | The catalogue can no longer read the recorded instance; this is not proof of deletion |

Every transition must record the subject, prior and new states, timestamp, actor, reason, supporting evidence, policy/tool version and approval reference where applicable. History must be retained rather than overwritten.

## Quarantine and rollback policy

Quarantine is controlled, reversible custody separation; it is not deletion. M12 does not authorise quarantine actions.

A future quarantine workflow must:

- require explicit approval for the defined action scope;
- verify the source instance immediately before action using SHA-256 and relevant metadata;
- use a controlled location on trusted storage, never the retired Z: device;
- avoid overwriting an existing destination;
- record original absolute and relative paths, quarantine path, content hash, size, timestamps, source/import identity and action time;
- verify the quarantined copy before considering the move complete;
- retain enough path, naming, metadata and conflict-handling information to restore the original state;
- make rollback independently available and auditable; and
- report partial failures without concealing either surviving instance.

All future file-changing actions, including moves, renames, metadata writes and restoration, require an append-only audit record. Destructive deletion remains outside this milestone and must not be inferred from Canonical, Alternate or Quarantined status.

## Minimum provenance requirements

The catalogue must retain, where applicable:

- stable identifiers for the catalogue item, content identity and physical instance;
- original source and source account/device/collection identifier where known;
- original relative path and observed original filename;
- current or staging path, plus path history after any authorised future action;
- SHA-256 and the time/tool context in which it was calculated;
- byte size, media type and readability/validation result;
- source filesystem timestamps and embedded timestamps, labelled by kind and timezone status;
- acquisition or import batch, method and verification result;
- membership in and relationships to M10 exact-duplicate content/groups;
- membership in and relationships to M11 near-duplicate pairs/groups, including method and distance;
- retained sidecar or companion-file relationships;
- later logical organisation labels and their evidence/confidence;
- canonical, alternate, review and custody decisions with actor, timestamp, rationale and approval; and
- every file-changing action and the information needed to reverse it.

Unknown or unavailable values must remain explicit. Provenance fields must not be silently replaced by normalised values; normalised values should be stored alongside observations.

## PROPOSED future canonical-decision framework - NOT YET AUTHORISED

The following framework is a discussion aid only. It is not an executable ranking algorithm and does not authorise automatic nominations or actions.

### Proposed gating and comparison sequence

1. **Establish identity class.** Use SHA-256 to distinguish exact instances of one content identity from genuinely different contents. Never use perceptual similarity as exact identity.
2. **Apply safety gates.** Exclude unreadable, unavailable, unverified or provenance-deficient candidates from automatic preference; route conflicts to review.
3. **Compare like with like.** Compare technical properties only within a known relationship such as exact instance, original/rendition or reviewed burst. Do not reward file size or dimensions globally.
4. **Present evidence dimensions.** Show preservation integrity, apparent generation/rendition, technical quality, metadata/context and operational availability separately.
5. **Explain the recommendation.** Retain each supporting and conflicting fact rather than emitting only a score.
6. **Require the applicable approval.** Record the owner or later authorised rule that accepted the nomination.

### Proposed decision matrix

| Situation | Possible future handling | Required safeguards |
|---|---|---|
| SHA-256-identical, readable, verified instances with complete provenance | Suggest a preferred operational instance | Keep every instance; explain source/path choice; approval policy still to be chosen |
| SHA-256-identical instances where one is unreadable or unavailable | Suggest the verified readable instance | Retain exception record; do not infer permission to remove the other entry |
| Clear reviewed original plus lower-quality export/recompression | Suggest original for archival scope and allow export as Alternate | Relationship must be evidenced; preserve edit/export and provenance; owner approval |
| Edited, cropped, filtered or annotated variant | No automatic preference | Owner review; canonical scope may differ for archival and display use |
| Burst, live-photo components or similar event frames | No automatic preference | Owner review and companion/sequence awareness |
| M11 perceptual candidate, including hash-distance zero with different SHA-256 | No automatic preference | Side-by-side review; technical and provenance evidence; never delete from hash evidence |
| Large screenshot/layout cluster | Keep as low-confidence review collection | Do not infer pairwise equivalence from connected grouping |
| Conflicting dates, filenames, sidecars or source histories | No automatic preference | Preserve all observations and request manual resolution |
| Unreadable, zero-byte, document-like or unknown-extension material | No canonical automation | Exception handling and manual review; preserve item and provenance |

A later scoring model, if adopted, should use transparent evidence dimensions and hard safety gates rather than a single opaque total. It must be tested against reviewed examples, expose uncertainty and abstain when evidence conflicts. No weights, thresholds or tie-break rules are authorised by this document.

### Proposed automation boundary

Automation may eventually be safe for reproducible catalogue work such as calculating hashes, recording technical metadata, linking SHA-256-identical instances, creating logical views and generating explainable suggestions. Even these operations require validation and must not alter source media.

Owner review should remain mandatory for subjective rendition preference, edits versus originals, event/place interpretation, people classification, conflicting provenance, ambiguous dates, near duplicates, screenshot/layout clusters, unreadable content and any action that changes file custody or reduces redundancy.

## Decisions requiring owner approval

Resolved:

- **APPROVED:** Canonical status has separate **archival** and **display/export** scopes. They may reference the same file or different files.
- **APPROVED:** Every canonical nomination requires explicit owner approval at this stage, including verified SHA-256-identical copies and both canonical scopes. No automatic canonical nomination is authorised.

Active now:

- None. All owner decisions required to complete the current M12 policy foundation are resolved.

Deferred until the application foundation, catalogue or relevant evidence exists:

1. **DEFERRED:** Which date-evidence precedence and timezone rules should drive the preferred capture date and calendar views when sources conflict.
2. **DEFERRED:** Which logical organisation views should be primary: date-first, event-first, source-first, or a chosen combination.
3. **DEFERRED:** Whether a future managed physical layout should ever be created in addition to logical catalogue views, and what approval boundary should govern it.
4. **DEFERRED:** Whether screenshots and document-like images should remain in the main media catalogue, appear in separate logical collections, or be routed to a future specialist document workflow.
5. **DEFERRED:** Whether people recognition/tagging may be introduced in a future milestone and, if so, under what privacy and confirmation rules.
6. **DEFERRED:** What future quarantine approvals, retention period and restore expectations should apply before any custody-changing workflow is implemented.
7. **DEFERRED:** Detailed canonical scoring, weighting, thresholds and tie-break rules.

## M12 boundary

This policy foundation does not complete M12 and does not authorise application implementation. No source media or staging data was moved, renamed, deleted, consolidated, quarantined or altered in producing it.
