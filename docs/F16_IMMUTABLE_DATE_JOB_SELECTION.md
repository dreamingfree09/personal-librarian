# F16: immutable date-job selection and completed replay

Each new catalogue-only date job captures its exact eligible physical-instance
membership in ascending ID order, within the requested cursor and limit. It
retains each physical ID, content ID, source ID, relative path, observed creation
timestamp and observed modification timestamp. The original count, first/last
IDs, next cursor and end-of-catalogue result are retained, including empty jobs.
An upper-ID watermark alone is not the selection boundary.

The versioned selection and SHA-256 fingerprint are stored in the existing
`analysis_runs.parameters_json`, alongside the original request configuration.
The existing job configuration and its fingerprint keep their request meaning;
the report additionally exposes `selection_fingerprint`. Job, analysis run and
selection are created in one `BEGIN IMMEDIATE` transaction. Schema 10 already
has the required storage; no migration or new table is needed.

Resume verifies the selection binding and checkpoint identities before changing
job state. Every original source-field binding must still match; otherwise the
job stops for offline review without substituting today's inputs. Each item is
rechecked under a write reservation, then evidence, preferred projection and
checkpoint commit together. New eligible records, newly linked records and new
IDs in old gaps cannot enter the original job. A separately authorised job ID
can select a new window. Media files are never opened or statted.

A completed retry verifies retained metadata and complete checkpoint membership,
then returns the original checkpoint-derived report without changing records,
events, preferred projections, analysis completion, job timestamps or selection
metadata. It does not reinterpret subsequent source metadata. Another worker's
completed job is not re-completed after the per-item loop.

## Historical jobs

The previous implementation retained request limits/cursors and processed-item
checkpoints, but not the accepted selection or unprocessed source inputs.
Completion flags cannot prove initial membership: jobs could previously reopen
and absorb changed eligibility. Even a checkpoint count equal to the requested
limit cannot prove the original selection; it may be the union of earlier live
selections. An empty checkpoint set cannot prove an originally empty selection.

Consequently, an unsnapshotted historical job fails closed with a clear diagnostic
and remains unchanged. No historical snapshot is manufactured from the current
catalogue or checkpoint subset. Request compatibility alone is insufficient.
Preserve the old evidence and explicitly authorise a new job ID if processing a
new selection is appropriate. There is no demonstrated safe automatic conversion
for the historical records supplied by this schema. This supersedes the old test
that expected an empty historical completed job to process today's first page.

## Validation and limits

Disposable schema-10 tests reproduce completed-job reopening, empty-selection
growth, sparse-ID replacement and source-field reinterpretation on accepted main.
Corrected tests cover cursor windows, changed eligibility, interrupted resumes,
all captured source bindings, snapshot corruption, checkpoint corruption, atomic
job insertion failure, process termination during evidence/checkpoint work and
interruption after completion commit. Whole logical-database comparisons prove
completed replay has no writes. Existing cursor/CLI, per-item failure and
schema-9 rejection-without-migration tests remain in force.

The fingerprint detects inconsistent retained metadata; it is not protection
against an operator deliberately replacing both metadata and its digest. Older
unfixed application versions must not resume jobs using their live-selection
behaviour. The original detailed source audit was unavailable in authorised
references; implementation follows the explicit F16 instruction. No production,
media, backup, package, dependency or authority-policy operation is included.
