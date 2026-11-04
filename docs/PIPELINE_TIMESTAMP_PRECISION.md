# Pipeline timestamp precision (F11)

Inventory and both fresh/reused SHA-256 observation paths encode `st_mtime_ns`
using integer seconds and nine fractional UTC digits. No floating-point `st_mtime`
or microsecond `datetime` round trip is used. ISO timestamp meaning, UTC offset
and existing timestamp columns are retained; no schema change is required.
The filesystem's observable precision is retained, not enhanced (Windows NTFS
fixtures exercise 100 ns steps). The checkpoint integer remains authoritative.

Action planning decodes explicit nine-digit aware timestamps with integer epoch
arithmetic, including negative epochs and non-UTC offsets. Existing lower-precision,
naive or absent timestamp evidence cannot establish an exact filesystem mtime.
It produces no invented nanosecond value. Preflight returns
`source_mtime_precision_unavailable` for such evidence, including old plans with
padded integers. Historical rows/plans are not rewritten. A fresh authorised
inventory/hash observation and a new plan are needed to regain exact preflight;
this correction does not perform them against owner data. Ordinary timestamp
consumers may continue to parse/display ISO timestamps as before.

Baseline reproduction on a disposable Windows file: observed
`1700000000123456700` became `1700000000123457000` through the former float/ISO
conversion. This both rejected an unchanged file and could falsely match a later
300 ns change. Regression tests cover exact observation rows, hashing and reuse,
unchanged preflight, later submicrosecond changes, preserved earlier checkpoints,
legacy plans, timezone offsets and exact negative-epoch round trips.

This contract follows the supplied F11 description and reproduced source defect.
The original detailed historical audit was unavailable; no additional historical
acceptance criteria are inferred. No physical execution, schema migration or
production operation is part of this change.
