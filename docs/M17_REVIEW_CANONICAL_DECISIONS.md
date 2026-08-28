# M17 - Review and Canonical-Decision Workflow

Date: 22 August 2026

Status: implementation and bounded temporary-catalogue validation complete; M17 remains open pending owner close-out decision

## Purpose and safety boundary

M17 supplies the first catalogue-driven owner review workflow over exact-duplicate and near-duplicate evidence. It reaches Recommend/Approve only. It does not copy, move, rename, delete, quarantine, consolidate, alter timestamps, or modify media metadata.

Canonical status is reversible catalogue metadata. A non-canonical instance remains preserved. Review and decision commands do not rescan, rehash, decode, or otherwise open media. SQLite remains authoritative; JSON output is a report, not canonical state.

## Review queue architecture

`review.py` builds deterministic read-only views from catalogue rows. Queue order uses stable identity/group keys with integer IDs as tie-breakers. Filtering happens on event-derived review state before `--offset` and `--limit` pagination, so repeated calls with unchanged catalogue state return the same page.

Both queue types support:

- `pending`, `reviewed`, `partially_reviewed`, `decided`, `abstained`, and `reopened` filters;
- bounded pagination;
- human-readable indented output or compact JSON; and
- detail views containing paths, sources, sizes, timestamps, extensions, SHA-256 identity, exact-copy counts, current nominations, and current approvals where available.

No quality score or preferred winner is calculated. Source, timestamp, size, path length, extension, and similarity distance remain evidence only.

## Exact-duplicate decision context

An exact review context is the SHA-256 content identity, identified by `content_identity_id`, when at least two physical instances currently reference it. This is more stable than an analysis-run-specific exact-group row. The detail view also lists every `exact_duplicate_groups` provenance row associated with the content identity.

Only a physical instance carrying that exact content identity can be nominated in the context. The queue reports all current physical copies rather than selecting one.

## Near-duplicate decision context

A near-duplicate review context is a specific `similarity_group_id`. It preserves the M11/M16 group provenance, member content identities, physical representations, individual pHash/dHash distances, relationship type, algorithm/run context, review tier, and large-group flags.

A physical instance is eligible only when its content identity is a member of that group. This eligibility does not merge identities. Similarity relationships themselves cannot be nomination targets.

## Canonical scopes

The M12 scopes are implemented independently:

- `archival` means archival-canonical, the preferred preservation representation;
- `display_export` means display/export-canonical, the preferred viewing, sharing, export, album, or downstream representation.

The scopes may approve the same physical instance or different instances. Neither scope authorizes file action or deletion.

## Nomination and approval lifecycle

Every write requires an explicit event ID, owner identity, canonical scope, and target evidence. Event IDs are stable unique catalogue keys.

1. `nominate` records an owner-created proposal for one eligible physical instance. It remains pending and is not canonical.
2. `approve` records a separate owner approval referring to a pending nomination. It becomes the current approved instance only if the scope has no existing approval.
3. `reject` closes a pending nomination without selecting a canonical instance.
4. `supersede` explicitly approves a different pending nomination and identifies the current approval it replaces.
5. `abstain` records an explicit no-selection state for a context/scope. For provenance it targets a content identity in the context. When a current approval exists, the command must explicitly name that approval with `--prior-approval-id`; the event withdraws it without rejection and preserves the complete history.

There is no automatic nomination or implicit nomination-plus-approval operation.

## Append-only event model

Migration 5, `review_and_canonical_decision_workflow`, minimally extends the existing `decision_events` foundation with:

- `workflow_action` (`nominate`, `approve`, `reject`, `supersede`, `abstain`);
- `exact_content_identity_id` or `similarity_group_id` context provenance; and
- a second related-event reference used by supersession.

The established proposal/approval/rejection/withdrawal/supersession vocabulary is preserved underneath. M17 abstention uses the historical withdrawal storage type plus the explicit `abstain` workflow action, avoiding a destructive table rewrite. Existing append-only UPDATE and DELETE triggers continue to protect every row.

Approval and rejection point to their nomination. Supersession additionally points to the prior current approval. Abstention points to the withdrawn approval when one exists. Actor, owner status, reason, occurrence time, record time, target type, and target ID remain auditable.

## Current-state and review-status derivation

Current state is rebuilt directly from events ordered by immutable `decision_event_id`. There is no mutable projection or cached canonical truth.

Per scope, derivation exposes:

- pending nominations;
- the current approved physical instance and its nomination/approval events;
- rejected and superseded nomination history;
- abstained/no-selection state; and
- superseded and withdrawn nomination states retained in history. A `reopened` review state is reserved for a future explicit reopening lifecycle and is not produced by ordinary M17 commands.

Aggregate review state is:

- `pending` when no owner workflow event exists;
- `partially_reviewed` when some work exists but both scopes are not finally approved/abstained;
- `decided` when both scopes are resolved by approval or explicit abstention;
- `abstained` when both scopes explicitly abstain; or
- `reopened` when applicable from the event history.

The `reviewed` filter is an alias for every state other than untouched `pending`.

## Conflict and invariant rules

Decision writes use `BEGIN IMMEDIATE` transactions and validate all references before append:

- a nomination target must belong to its exact or similar context;
- only pending nominations can be approved, rejected, or used as a replacement;
- approval is refused when the context/scope already has a current winner;
- replacement requires explicit supersession and the exact current approval ID;
- the replacement must be a different physical instance;
- archival and display/export uniqueness are enforced independently;
- a rejected or superseded nomination cannot later be silently approved;
- abstention cannot implicitly displace an approval; withdrawal requires its exact current approval ID;
- unrelated identities and groups cannot be cross-wired; and
- no relationship or decision changes a content identity.

These are catalogue workflow invariants, not physical custody operations.

## CLI

Queue inspection:

```powershell
personal-librarian review exact list --database 'C:\explicit\catalogue.sqlite3' --status pending --limit 50
personal-librarian review exact show 123 --database 'C:\explicit\catalogue.sqlite3'
personal-librarian review similar list --database 'C:\explicit\catalogue.sqlite3' --status reviewed
personal-librarian review similar show 456 --database 'C:\explicit\catalogue.sqlite3'
```

Owner workflow:

```powershell
personal-librarian decision nominate `
  --database 'C:\explicit\catalogue.sqlite3' --event-id owner-nomination-001 `
  --context-type exact --context-id 123 --physical-instance-id 789 `
  --scope archival --owner owner

personal-librarian decision approve `
  --database 'C:\explicit\catalogue.sqlite3' --event-id owner-approval-001 `
  --nomination-id owner-nomination-001 --physical-instance-id 789 `
  --scope archival --owner owner

personal-librarian decision reject --help
personal-librarian decision supersede --help
personal-librarian decision abstain --help
personal-librarian decision current --database 'C:\explicit\catalogue.sqlite3'
personal-librarian decision history --database 'C:\explicit\catalogue.sqlite3'
```

All commands support `--format json`; queue/current/history JSON can be redirected to a file when an external report is needed. The output is read-only evidence and never replaces SQLite.

## Validation

Synthetic tests cover deterministic exact and similarity queues, pending/reviewed filtering, pagination, evidence detail, large-group flags, nomination remaining pending, explicit approval, independent scopes, same and separate winners, rejection, supersession, abstention, append-only triggers, deterministic history, repeatable state rebuilding, one-winner enforcement, cross-context rejection, invalid targets, identity separation, unchanged media bytes/timestamps, JSON CLI output, and lexical Z: database rejection.

A bounded workflow was also exercised in a temporary schema-v5 catalogue populated with verified M9/M10/M11 evidence. It used one real exact context and one real near-duplicate group, tested list/show, pending nomination, approval, explicit replacement supersession, independent display/export handling, complete history, and derived current state. Decisions existed only in the temporary validation database. Integrity and foreign-key checks remained clean.

## Limitations and close-out boundary

- M17 is CLI/catalogue workflow only; there is no graphical review interface or image preview.
- No quality scoring, ranking, automatic nomination, or automatic approval exists.
- An exact context uses the current catalogue mapping of physical instances to one SHA-256 identity; historical group rows remain evidence rather than separate decision contexts.
- A near-duplicate context is tied to a particular similarity-group row/analysis provenance. Cross-run group correlation is deferred.
- Abstention is scope-specific. Both scopes must abstain for the aggregate context state to be `abstained`.
- JSON reporting is written to standard output; M17 does not manage export files or treat them as authoritative.
- No permanent production catalogue, owner-identity registry, authentication mechanism, or multi-user authorization layer is selected here.
