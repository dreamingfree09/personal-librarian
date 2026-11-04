# Preferred-date integrity: F09 and F10

This correction uses the existing schema-10 preferred-date architecture. It does
not migrate a catalogue, change date authority, inspect media, or add physical actions.
The supplied F09/F10 acceptance contract and source behaviour are the authority for
this change; the original detailed audit was not available in retained local references.

## F09: value and basis are separate projections

The preferred signature and active `(evidence ID, role)` pairs are checked separately.
A matching preferred signature no longer skips basis reconciliation. Missing links
are inserted, obsolete current links are superseded, and existing roles are corrected.
Unchanged links are not written. Basis-only changes return `basis_changed=true` while
`changed=false` continues to mean no preferred-selection change. Existing pipeline
selection-change metrics therefore do not count a basis refresh as a new selection.

Basis reconciliation does not alter preferred timestamps, actor, policy or selection
provenance and does not manufacture selection events. A changed policy version still
uses the existing preferred-policy transition event. Evidence stays immutable.
The existing schema has one basis row per preferred/evidence pair: those rows and their
IDs/initial link timestamps are retained, obsolete links have a superseded timestamp,
and roles/current state are a mutable projection rather than an append-only role ledger.
No historical organisation event is rewritten and no basis row is deleted. This change
does not claim a new history of every intermediate basis role; adding such a ledger
would require a separately reviewed schema/event contract.

An active owner selection remains authoritative, including under a newer policy version.
Its evidence is the selected basis. Compatible non-owner evidence corroborates it;
incompatible non-filesystem evidence is conflicting and weak incompatible filesystem
evidence is ignored. Prior owner choices remain historical/superseded, not revived as
current policy basis. Repeating the same evaluation writes no basis or selection rows
and appends no event.

## F10: durable content-scoped owner action identity

M30 requires a deterministic action ID and a new ID for a new correction. Its date
evidence key already scopes an action to the content identity. That existing scope is
preserved: `(content_identity_id, action_id)` identifies one owner date request, across
set/replace entry points. It is not a catalogue-wide or cross-service identifier.
Collections have their own broader domain-scoped history lookup; their contract is
unchanged. Reusing the same text for another content identity is a separate action.

An effective request binds the parsed/rendered partial date, actor, reason (including
absence) and provenance. Existing text validation/normalisation applies. Equivalent
space/T separators and Z/+00:00 spelling may retry the same request; changed precision,
offset representation, actor, reason or provenance is a conflict even if two datetimes
describe the same instant. Original raw evidence is never rewritten.

New owner events additionally retain the action ID and validated request in their
immutable JSON details. No table, index, trigger or migration changes are required.
The lookup, conflict check, evidence insertion, projection, basis and event append all
run under the existing SQLite `BEGIN IMMEDIATE` transaction. Concurrent calls use the
same durable history rather than process-local memory. An exception rolls back the
whole action.

An identical completed retry performs no writes, even after a newer owner correction.
It returns `changed=false`, `replayed=true`, the original action's `value` and evidence
ID, plus `is_current` and `current_selected_evidence_id` so the response does not imply
the historical choice became current. A conflicting request raises `DateEvidenceError`
without evidence, projection, basis or event changes. A new action ID can legitimately
correct the date. Existing CLI confirmation and desktop actor/confirmation seams remain.

### Compatibility with older immutable history

Older date events did not retain the action ID in plaintext. For a supplied ID, the
service recomputes the original evidence-key algorithm against that content's retained
owner rows using each row's original raw value. Matching evidence is checked against
its completed owner events, including actor, reason and provenance. This is verification
of a supplied ID, not reversal or invention of an unknown ID. No historical backfill
or payload rewrite occurs. Matching legacy retries are no-ops; altered payloads fail.
Ambiguous legacy reuse, missing completed history, malformed owner-event details or
inconsistent evidence/history fail closed and require separate investigation.

Scope is supported owner service writes and the existing immutable evidence-key contract.
This does not repair pre-existing contradictory owner history, bypass service checks for
arbitrary direct SQL, or introduce production migration. Tests use disposable synthetic
schema-10 catalogues and inspect stored evidence, projection, basis, immutable events,
integrity and foreign keys, including concurrent requests and injected rollback failure.
