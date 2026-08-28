# M28 - Catalogue Organisation Schema and Manual Albums Foundation

Date: 24 August 2026

Status: implementation, validation, and production migration complete; pending owner review

## Scope and policy boundary

M28 implements the smallest owner-managed logical-organisation foundation described by
M27. It adds schema and application operations for manual albums, content-identity album
membership, immutable organisation history, and minimal manual tags.

It does not create physical album folders or change media paths. It does not scan,
re-hash, classify, geocode, cluster faces, call AI, create embeddings, infer events or
places, select canonical copies, or perform physical actions. M12 canonical decisions,
M17 review history, M18 plans, and M19 quarantine remain independent.

## Schema 9 migration

Migration 9, `manual_logical_organisation`, is appended to the existing ordered migration
history. Historical migrations 1–8 are unchanged. The existing migration runner applies
it in one `BEGIN IMMEDIATE` transaction and records it only after all tables, indexes,
constraints, and triggers succeed. Reopening an already migrated catalogue is
idempotent.

Schema 9 adds:

- `albums`;
- `album_memberships`;
- `tags`;
- `content_tags`; and
- `organisation_events`.

No existing table is rebuilt or altered. No seed rows are inserted.

## Albums

An album has a local integer primary key and stable UUID. It records name, optional
description, extensible album kind, active/archived state, creation/update/archive times,
actor, and typed provenance. M28 creates only `manual` albums.

Album names are 1–200 trimmed characters. Duplicate active names are allowed because
future presentation hierarchy and owner intent may legitimately produce equal names.
UUID and state are always surfaced; names never merge albums. Rename preserves UUID.

Albums are never hard-deleted. Archive is reversible and retains membership. Archived
albums are read-only for membership changes until restored.

## Membership and exact-duplicate semantics

`album_memberships` relates one album to one `content_identity_id`. It never targets a
physical instance. Its unique album/content pair is a current-state projection with
`active` or `removed` state.

Adding an active pair again is an idempotent no-op. Removing an absent or already removed
pair is an idempotent no-op. Re-adding a removed pair restores it and records a new
history event. Rows cannot be deleted and their album/content identity and creation
provenance cannot be changed.

Three SHA-256-identical physical copies share one content identity and therefore produce
one logical album member. Near-duplicate contents retain separate identities and must be
added individually. Membership neither depends on nor changes archival/display canonical
status.

## Organisation history and provenance

`organisation_events` is append-only. It records stable event UUID, operation, affected
album/membership/tag/content, owner actor, timestamp, provenance, optional reason, and
structured details.

Recorded album events are create, rename, archive, restore, member add, member remove,
and member restore. Tag create/add/remove/restore event types are reserved and used by
the manual tag service where applicable. UPDATE and DELETE triggers protect all history.

The current-state projection keeps normal owner operations simple while immutable events
retain auditability. Album, membership, tag, and content-tag DELETE triggers prevent hard
deletion; snapshot triggers preserve stable identity and creation provenance.

All M28 mutations require a non-empty explicit actor. Reason is optional. Provenance
defaults to `owner-manual`, while schema fields distinguish owner, system, and future AI
provenance. M28 services create owner records only.

## Manual tags and deferred classifications

Schema 9 includes minimal `tags` and `content_tags` tables with stable UUIDs,
namespace/name, state, content-identity membership, provenance, reversible membership
state, and organisation history. The service supports manual create, list, add, remove,
and content lookup. Automatic tagging is unavailable.

The broader classification model—media type, topic, disposition/Dumpster, and role—is
deferred. M28 does not create classification values or a Dumpster workflow. Events,
places, people, smart albums, AI suggestions, and presentation collections are also
future schema extensions.

## Organisation service

`personal_librarian.organisation` provides transactional, path-policy-aware operations:

- `create_album`, `rename_album`, `archive_album`, `restore_album`;
- `list_albums`, `get_album`;
- `add_content_to_album`, `remove_content_from_album`;
- `list_album_members`, `list_albums_for_content`;
- `organisation_history`; and
- minimal manual tag creation, membership, and lookup functions.

Writes use `BEGIN IMMEDIATE`, validate schema 9, actor, names, lengths, album/content
existence, state, and positive IDs, and commit the projection plus audit event together.
Lists are bounded to at most 500 rows per request.

## CLI

The bounded CLI is:

```powershell
personal-librarian albums list --database 'C:\explicit\catalogue.sqlite3'
personal-librarian albums create --database 'C:\explicit\catalogue.sqlite3' --name 'Family' --actor owner
personal-librarian albums show <album-uuid> --database 'C:\explicit\catalogue.sqlite3'
personal-librarian albums rename <album-uuid> --database 'C:\explicit\catalogue.sqlite3' --name 'Family archive' --actor owner
personal-librarian albums archive <album-uuid> --database 'C:\explicit\catalogue.sqlite3' --actor owner
personal-librarian albums restore <album-uuid> --database 'C:\explicit\catalogue.sqlite3' --actor owner
personal-librarian albums add-content <album-uuid> <content-id> --database 'C:\explicit\catalogue.sqlite3' --actor owner
personal-librarian albums remove-content <album-uuid> <content-id> --database 'C:\explicit\catalogue.sqlite3' --actor owner
personal-librarian albums members <album-uuid> --database 'C:\explicit\catalogue.sqlite3'
personal-librarian albums for-content <content-id> --database 'C:\explicit\catalogue.sqlite3'
personal-librarian albums history --album-uuid <album-uuid> --database 'C:\explicit\catalogue.sqlite3'
```

All commands support JSON output. Mutating commands require `--actor`, accept optional
`--reason`, and support explicit owner provenance. There are no wildcard or bulk
membership operations.

## Desktop support

No desktop code changed. A safe and useful Organisation view needs content discovery,
member previews, editing controls, and audit presentation; adding a partial UI would
have widened M28 and forced a package rebuild. Service/CLI correctness therefore takes
priority. Existing desktop Exact/Similar preview safeguards are untouched.

## Disposable migration validation

A full SQLite-backup clone of the production schema-8 catalogue was migrated to schema
9 outside the repository and production root.

- Catalogue UUID before/after: `613affe5-a00b-49bc-9ad9-99b95adeec33`
- Physical instances: `69,444`
- Content identities: `56,127`
- Exact groups: `7,707`
- Similarity groups: `5,067`
- Decision events, plans, executions, and quarantine records: `0`
- New albums, memberships, tags, content tags, and organisation events: `0`
- M9/M10 historical reconciliation: `MATCH`
- M11 reconciliation: `MATCH`
- SQLite integrity: `ok`
- Foreign-key violations: `0`

## Production backup and migration evidence

- Operational pre-migration backup ID:
  `cbb7f04a-a235-4524-9e31-1ba17cff89a8`
- Independent pre-migration backup ID:
  `91747653-6f9a-4238-84b2-4531f48a9941`
- Both backups contain schema 8, passed integrity and foreign-key checks, matched the
  production UUID, and were independently reverified as `ACCEPTED`.
- The independent backup recorded different physical device identities for H: and X:.
- Production migration result: `PASS`; schema `8 -> 9`.
- Production UUID remained `613affe5-a00b-49bc-9ad9-99b95adeec33`.
- Before/after physical instances: `69,444`; content identities: `56,127`; exact groups:
  `7,707`; similarity groups: `5,067`.
- Decision events, plans, plan items/results/events, executions/execution events,
  quarantine records, and location events remained `0`.
- Albums, album memberships, tags, content tags, and organisation events are `0`.
- The ordered catalogue path-evidence SHA-256 remained
  `E9BAE20EF4E17E594D2D9D5B1838CA38D56C81CE8D23BEA50A3ADEB0711816E2`.
- Production integrity is `ok`, foreign-key violations are `0`, health is `PASS`, and
  independent disaster-recovery readiness is `PASS`.
- Post-migration M9/M10 and M11 reconciliation both remained `MATCH`.

## Validation

- Focused catalogue/organisation tests: `26 passed`.
- Broader schema/history/production/release regression tests: `75 passed`.
- Schema-8 pre-migration backup creation and verification is covered by a focused test.
- Single full automated run: `141 passed`, `1` expected Windows long-path skip.
- Changed Python modules compiled successfully.
- Full disposable production-clone migration and reconciliation passed before production
  backup or migration.
- No desktop code changed, so no source desktop smoke or package rebuild was required.

## Limitations and future M29 recommendation

- CLI content selection uses content identity ID; there is no general media browser.
- Duplicate album names are distinguishable by UUID but there is no hierarchy/context UI.
- Album description editing after creation is not exposed in M28.
- Tags have service support but no dedicated CLI or desktop surface.
- Tags cannot yet be renamed/archived through the service.
- Classifications, Dumpster state, events, places, people, smart albums, collections,
  AI suggestions, and AI authority remain unimplemented.
- There is no bulk membership operation, hard delete, physical album folder, or media
  action.

Recommended M29 scope is a modest desktop Organisation view and content-selection
workflow over the validated M28 service, plus the smallest explicit classification
foundation needed for owner-managed media type/topic/disposition. AI remains deferred
until sufficient owner-labelled examples and a separate suggestion schema exist.
