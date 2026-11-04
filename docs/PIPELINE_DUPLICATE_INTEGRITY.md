# Historical exact-duplicate derivation (F12/F13)

## Evidence contract

Derivation requires the named completed SHA-256 job on every call, including a
completed retry. Its configuration fingerprint and retained source label are
validated. Successful `pipeline_job_items` supply physical occurrence identity,
SHA-256, size and nanosecond mtime. These must agree with that job's analysis-run
`pipeline_hash_observations` and `hash_observations`. The canonical SHA-256 identity
key/hash mapping supplies the content identity. Successful observation membership
must exactly reconcile with successful checkpoints. Missing or inconsistent
historical evidence fails closed; current catalogue state is never substituted.

The existing schema already retains this relationship. No schema extension,
backfill or historical evidence rewrite is required. Normal pipeline APIs do not
change a completed job's checkpoints. This is not protection against coordinated
malicious direct SQL rewriting of all historical evidence.

Current `physical_instances` content identity, size, source, locator and mtime and
current source display names are not used to derive historical groups. Original
path/extension/stat provenance remains in the named job's checkpoint rows; the
exact-job configuration links that job to its source hash job. Group membership
identifies occurrences as observed by that job, not a claim that today's file is
still identical or safe to act on. Current physical actions still require their
own current evidence and authority. Each hash job is single-source under the
existing hash source/root contract; a comma in its source label is not a second
source. No new cross-source selection mechanism is introduced.

## Publication and recovery invariant

New groups, memberships, pipeline completion and analysis-run completion commit
in one transaction through the existing `finish_job`. No separate group commit
precedes completion. Process death before commit leaves no partial new publication;
death just after commit leaves complete, replayable output.

Before any success report, existing groups and exact memberships/metrics are
compared with the expected historical result under the write lock. Legacy output
committed before its completion marker can be completed only when every required
record matches. Group IDs, original creation times and unrelated runs are retained.
Partial, conflicting or inconsistent committed evidence is preserved and rejected
for offline review, never deleted or silently repaired. A completed marker with
missing output does not cause a successful report. Repeated completed calls are
read-only and cannot duplicate groups/memberships. Source-job mismatch rejection
and the original completed-source requirement remain intact.

## Reproductions and validation

Baseline F12: a subprocess exits after group publication and before `finish_job`;
retry fails on the group uniqueness constraint. Baseline F13: after a completed
hash job of two equal files, a later legitimate inventory/hash changes one file;
rederiving the original job incorrectly changes one historical group to zero.

Disposable Windows regressions include actual process exits before completion,
immediately after the actual commit, after `finish_job`, between completion-marker
writes, and after legacy-style group publication. They also exercise incomplete
legacy output, incomplete completed output, historical replay after newer hashes,
changed current metadata/locators/source labels, unchanged stored records on
rejection, missing/mismatched evidence, source-job identity/completion, reuse,
zero-byte groups, unique nonmembers, integrity and foreign-key checks.

The original detailed historical audit was unavailable. These contracts derive
from the supplied F12/F13 descriptions and reproduced source behavior. This work
does not close issue #9, the Qt 6.12 shutdown investigation, F14/F16 or G3/G4, and
does not access production catalogues or owner media.
