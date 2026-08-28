# M18 - Safe Action Planning and Dry-Run

Date: 22 August 2026

Status: implementation complete; execution remains unavailable

## Purpose and boundary

M18 converts a current, explicit M17 owner approval into a deterministic catalogue snapshot of a possible future physical action. It answers what would happen, to which file, why, from which decision, and whether a bounded preflight currently passes. It does not grant permission to act.

The planner and preflight never copy, move, rename, quarantine, delete, overwrite, create destination directories, alter metadata, or change timestamps. There is no execution command or reachable `executed` state. SQLite is authoritative; human and JSON output are reports.

## Architecture and catalogue model

Migration 6, `safe_action_planning_and_preflight`, adds:

- `action_plans`: the immutable semantic snapshot plus a convenience lifecycle status;
- `action_plan_items`: immutable source, destination, identity, decision, precondition, postcondition, and restore evidence;
- `action_plan_preflight_results`: append-only item results, grouped by a UUID attempt ID; and
- `action_plan_events`: append-only creation, preflight, stale, and invalidation history.

Items, results, and events reject update and delete. Plans reject delete, and a trigger prevents updates to snapshot fields; only lifecycle status and invalidation fields are mutable conveniences. Historical attempts remain retained.

Lifecycle states are `draft`, `preflight_passed`, `preflight_failed`, `stale`, and `invalidated`. An invalidated plan cannot be preflighted. No execution state exists.

## Deterministic identity and decision provenance

`m18-v1` plan keys are stable hashes of the planner version, named policy, exact context and scope, current approval event, decision fingerprint, explicit destination root, ordered source IDs, safety margin, and reason. Item keys additionally bind the source physical instance, action type, destination, and policy. Repeating identical semantics returns the existing plan rather than rewriting it.

Creation accepts only the current effective M17 `approve` or `supersede` event with `owner_approved = 1` for the exact context and canonical scope. Pending, rejected, abstained, or superseded approvals cannot create a plan. Each item retains the decision-event foreign key and exported stable approval event ID. Archival and display/export scopes remain independent.

The plan stores a fingerprint of the derived decision snapshot. If the current approval changes, preflight records `STALE`; it does not revise the old snapshot. A materially changed policy or safety contract requires a new planner/policy version and therefore a new key.

## Explicit action policies

M18 exposes four versioned policies:

- `canonical-copy-to-destination-v1`;
- `canonical-move-to-destination-v1`;
- `canonical-rename-to-destination-v1`; and
- `exact-duplicate-quarantine-v1`.

Canonical copy, move, and rename policies use exactly the currently approved physical instance. The quarantine policy requires an exact-content context and explicit non-canonical physical-instance IDs; canonical approval alone never chooses what happens to other copies. Near-duplicate similarity alone is never actionable. A similar context can only use its exact currently approved physical instance through an explicit canonical policy.

Delete is deliberately omitted. Every policy records `overwrite: false` and `execution_available: false`.

## Destination derivation and source preconditions

The caller must supply an explicit absolute Windows drive or UNC destination root. No production root, library layout, NAS, drive, or quarantine location is inferred. The planned destination is deterministically:

`<explicit destination root>\<source basename>`

The explicit root therefore defines the intended plan namespace. It must already exist for preflight; M18 creates no directory. Z: is rejected lexically before access.

Creation snapshots the physical instance ID, raw and current paths, content identity, exact SHA-256, size, catalogue modified timestamp, filesystem nanosecond mtime when available, context, scope, decision, and operation. Preflight verifies that:

- the catalogue instance and its path, identity, size, and SHA-256 snapshot still match;
- the source remains a member of the expected exact/similar context;
- the path remains safe and not on retired Z:;
- the file exists and is a file;
- current size and captured filesystem mtime match; and
- the source and destination are not the same Windows case/Unicode-normalized path.

Preflight does not rehash the source automatically. It hashes only an already-existing bounded destination to classify same/different content. A future cryptographic source re-verification mode remains explicit work rather than an implicit library scan.

## Resolved destination safety

M18 extends the central M13 safety layer with a fail-closed future-write boundary assessment. It requires absolute paths, rejects explicit `..`, verifies the lexical destination remains within the explicit root, and rejects invalid or reserved Windows components.

The root must exist as a directory and cannot itself be a symlink, junction, or reparse point. Each existing destination ancestor is resolved without modification. An ancestor that resolves outside the root, reaches a blocked drive, or cannot be resolved safely fails preflight. Uncertainty is reported as unsafe. Links and reparse points are never altered.

Windows path collision keys use NFC normalization plus case folding. They classify case-insensitive and Unicode-normalization conflicts and detect two planned items targeting the same effective path.

## Conflict and free-space model

Preflight classifies source missing/changed/context failures; destination available, same-content, different-content, file/directory, case/Unicode, unknown, source/destination, planned-item, boundary, and reparse conflicts. An existing destination always fails readiness, including when its SHA-256 matches. Overwrite is always `NO`.

Copy, move, and quarantine conservatively require the total planned bytes plus the plan safety margin. Rename requires only the margin. Available bytes are queried at the explicit root and reported as `PASS`, `FAIL`, or `UNKNOWN`; space is never reserved. M18 does not assume that a move is same-volume or space-free.

## Quarantine and reversibility

A quarantine item captures original physical instance and raw/current paths, content identity and SHA-256, planned quarantine path, plan key, and approval event. This is restore provenance only. No quarantine occurs, and future execution would require a separate milestone and authority.

## CLI and reports

```powershell
personal-librarian plan create --help
personal-librarian plan list --help
personal-librarian plan show --help
personal-librarian plan preflight --help
personal-librarian plan report --help
personal-librarian plan invalidate --help
```

Every command requires an explicit database. Creation additionally requires policy, context, scope, approval event, destination root, and owner. Preflight requires an actor; invalidation requires a stable event ID, owner, and reason. `--format json` exposes the complete plan, items, latest result and append-only preflight history. Human output uses the same structured data.

Reports include plan identity and policy, scope, item/byte totals, source and destination, operation, SHA-256, reason, approval provenance, source/destination/conflict/free-space/safety results, readiness, and PASS/FAIL/STALE counts. They state:

`NO FILESYSTEM CHANGES WERE PERFORMED`

## Validation and limitations

Synthetic tests cover approval eligibility and scope separation, all four action representations, deterministic identity, exact-policy gating, near-similarity non-actionability, source changes and context identity, stale decisions, destination conflicts and boundaries, Windows case/Unicode collision semantics, Z: rejection, reparse escape where supported, free-space outcomes, restore provenance, append-only history, invalidation, and absence of execution.

The bounded real-evidence workflow uses a temporary schema-current catalogue and temporary owner decisions only. It imports the verified M9/M10/M11 evidence, plans one non-canonical exact copy, preflights it, exercises a destination conflict, supersedes the approval, confirms staleness, and removes the temporary validation state. It never scans, rehashes, or changes media.

Limitations remain deliberate: no permanent destination policy or physical library layout has been approved; no source rehash is implicit; no directory creation or space reservation occurs; and no physical action can be executed. M18 ends at planning and dry-run preflight.
