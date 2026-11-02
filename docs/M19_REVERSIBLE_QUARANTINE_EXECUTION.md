# M19 - Reversible Quarantine Execution

Date: 23 August 2026

Status: implementation and bounded real quarantine/restore validation complete; pending owner close-out

## Scope and safety boundary

M19 introduces the smallest physical `Act`: moving one explicitly planned, preflight-passed, non-canonical exact duplicate into an explicit quarantine root, and restoring that same item. It does not introduce a generic action mode.

General copy, move, rename, delete, overwrite, bulk cleanup, near-duplicate execution, and automatic canonical selection remain unavailable. M18 plan inspection and dry-run preflight remain unchanged.

Exact duplicates are the only eligible evidence because M19 requires the source bytes to match the plan's exact SHA-256 identity before and after the move. Perceptual similarity is never sufficient.

## Confirmation and eligibility gates

Current CLI clarification: explicitly selecting `--mode read-only` or
`--mode dry-run` prohibits physical execute/restore, including confirmed requests.
The separately confirmed M19 route requires omission of `--mode`; it does not
enable general ACTION mode. See [the current maintenance and mode contract](CATALOGUE_MAINTENANCE.md).

`quarantine execute` requires `--confirm-quarantine`; the API requires `confirm_quarantine=True`. Restore independently requires `--confirm-restore`. Missing confirmation fails before an execution row or filesystem action is created.

Execution additionally requires:

- an existing M18 `exact-duplicate-quarantine-v1` plan and item;
- exact context and quarantine action types;
- current plan status `preflight_passed` and latest item result `PASS`;
- the same explicit quarantine root recorded by the M18 plan;
- the same current owner-approved canonical decision and scope;
- a source physical instance that is not the approved canonical instance;
- matching catalogue path, content identity, SHA-256, and size evidence; and
- no earlier execution attempt for that item.

Repeated calls for an already journaled item are idempotent reports. They never move a file again.

## Fresh pre-execution and cryptographic verification

M19 does not trust the older preflight by itself. After recording the request it checks the source path policy, existence, file type, size, captured mtime, exact context membership, current canonical decision, destination boundary, destination absence, same-volume identity, and conservative free space again.

The source is streamed through SHA-256 and must equal the planned digest. Catalogue decision and source evidence, size, mtime, and destination absence are checked again immediately before `os.rename`.

After the move, source absence and destination presence/size are verified. The destination is streamed through SHA-256 and must match the same digest. Only then is the execution marked `succeeded`. A post-move verification failure becomes `recovery_required`, never success.

## Same-volume policy and destination

M19 supports same-filesystem quarantine and restore only. It compares filesystem device identity before action and uses `os.rename`, whose Windows behavior does not overwrite an existing destination. Cross-volume operation fails closed; there is no copy-delete fallback.

The caller supplies an existing absolute Windows/UNC quarantine root. It must exactly match the M18 plan root. M19 deterministically derives:

`<root>\plan-<plan-token>\item-<item-token>\<original basename>`

The identity directories avoid collisions while retaining the basename. M19 may create only these directories inside the validated root for the single confirmed action. It reassesses resolved ancestors after creation and never overwrites.

## Journal and lifecycle

Migration 7, `reversible_quarantine_execution`, adds:

- `action_executions`: immutable request provenance with mutable lifecycle outcome;
- `action_execution_events`: append-only requested/validation/move/verification/failure/recovery/restore events;
- `quarantine_records`: original/quarantine paths, identity, size, digest, and restore state; and
- `physical_instance_location_events`: append-only verified quarantine/restore location history.

Execution states are `requested`, `validating`, `moving`, `verifying`, `succeeded`, `failed`, `recovery_required`, and `restored`. A filesystem move without post-verification cannot become `succeeded`. Execution records cannot be deleted, snapshot fields cannot be changed, and event/location history is append-only.

## Interruption and reconciliation

The request and `moving` event are committed before the filesystem move. Therefore a restart can compare the durable journal with both paths. `quarantine reconcile` performs no move, copy, or deletion and classifies:

- source only with correct hash: `not_moved` or `restored_verified`;
- quarantine destination only with correct hash: `quarantined_verified`;
- both paths: `both_source_and_destination_exist`;
- neither path: `neither_source_nor_destination_exists`;
- wrong source/destination hash: explicit hash mismatch; and
- unsafe destination: `destination_unsafe`.

Unambiguous correct quarantine/restore state can complete the catalogue journal. Ambiguous or wrong-hash states become `recovery_required`; M19 never guesses which copy to remove.

## Restore workflow

Restore accepts only a `succeeded`/`quarantined` record. It verifies the quarantine path, size, and SHA-256; requires the exact original parent to exist and pass resolved-boundary checks; rejects Z:; requires same-volume operation; and stops if the original path is occupied.

After the move back, it verifies quarantine-path absence, restored-file presence/size, and SHA-256 before recording `restored`. No alternative restore path, overwrite, or force option exists.

## Catalogue provenance and location

The immutable M18 item retains the original path snapshot. `quarantine_records` retains both original and quarantine locations. Each verified transition adds a location event. `physical_instances.current_observed_path` is updated only after verified quarantine/restore as a convenience projection; `content_identity_id` is never changed and historical evidence remains linked.

## CLI

```powershell
personal-librarian quarantine execute --help
personal-librarian quarantine status --help
personal-librarian quarantine history --help
personal-librarian quarantine reconcile --help
personal-librarian quarantine restore --help
```

There is no `plan execute`, delete command, overwrite switch, or `--force` bypass.

## Validation and limitations

Synthetic tests use temporary catalogues and files and exercise success, confirmation, eligibility, canonical/stale/preflight gates, all source-change classes, exact hashing, destination conflicts, Z: rejection, reparse escape, cross-volume rejection, post-move failure, idempotency, recovery classifications, restore success/failure, no overwrite, and durable provenance.

The bounded real validation used exact context 1 and two repaired/current H: copies of `20260610_180442.jpg`. The OneDrive instance remained the canonical reference; the Google Photos instance was the sole action target. Both were ordinary, locally accessible 4,342,370-byte JPEG files, passed Pillow verification, and matched SHA-256 `3afd2949d666603944a87929f341f909320a4d4de3134b6b396a151a95f5bc09` before action.

The M18 preflight passed. M19 moved the Google Photos copy into the explicit ignored root `H:\PersonalLibrarian\tmp\m19-quarantine-validation`, verified source absence and destination size/SHA-256, and recorded success. Reconciliation independently classified it `quarantined_verified`. Restore moved it back to the exact original path and verified the same size/SHA-256. Both source copies and their original timestamps were present afterward; the canonical copy was untouched. The temporary catalogue retained ten execution events and two location events, passed `integrity_check`, and had no foreign-key violations before all temporary validation state was removed.

Limitations are deliberate: same-volume only; no copy-delete fallback; no automatic retries after a failed attempt; no alternate restore destination; no permanent quarantine root; no bulk actions; and no deletion or general execution.
