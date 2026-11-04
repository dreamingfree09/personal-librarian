# F14: complete preferred-date Year shelves

The schema-10 desktop Year view follows the M30 contract: a resolved preferred
year belongs to that Year; needs-review, unknown and missing projections belong
to Unknown Date. Observed filesystem timestamps never supply a fallback year.
The separate Needs review and Unknown only filters remain narrower status views,
not additional primary shelves. Albums use the same shelf membership rule.

Valid preferred-date years span 1–9999. Year page and Album validation now accept
that entire range, including year-only precision. Unknown counts retain the
bounded, index-based count/page/enrichment strategy, subtracting only resolved
projections from the total identity count. No schema change or automatic
migration is introduced; schema-9 continues using the legacy read-only path.

Disposable Windows regressions cover years 0001, 1899, 2101 and 9999, full dates,
year-only dates, all projection statuses, missing projections, empty shelves,
paging, Album membership and status transitions. The actual PySide6 Library
widget exercises shelf selection, filters, next/previous pages and identity
preservation. Existing schema-9 and stale-navigation tests remain in force.

The accepted-main baseline fails the new shelf regressions: extreme shelves
raise the 1900–2100 validation error and needs-review identities disappear from
the primary partition. The corrected tests reconcile every content identity to
exactly one primary shelf. Earlier tests encoding the inconsistent exclusion of
needs-review were updated to the documented contract without removing their
bounded-query or representative-instance checks.

This correction does not alter preferred-date authority, media, production data,
Qt dependencies, packaging or the historical PowerShell guard. The original
detailed source audit was not available in the authorised local references;
scope is limited to Aether's explicit F14 finding and canonical M30 policy.
