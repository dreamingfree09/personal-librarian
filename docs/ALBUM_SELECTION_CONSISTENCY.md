# Album selection and asynchronous member loading

Album members are displayed only for the current request generation and selected
Album UUID. Visible names and table row positions are not identities. Selecting a
new Album immediately clears the previous members and displays a loading message.
Clearing selection, changing Year/date filters, refreshing catalogue data, replacing
Album rows or changing the Album lifecycle filter invalidates pending member reads.
A replaced Album table requires an explicit selection; the former numeric row is
not silently reused. Duplicate or obsolete completions cannot restore old members,
detail text, thumbnail bindings or removal state.

Removal requires the loaded Album UUID, selected Album UUID and selected member
bindings to agree. Selected IDs must belong to the loaded member rows. Add/remove
confirmation captures its target and rechecks the selection generation after the
modal dialog, since Qt can process queued events during confirmation. A confirmed
operation invalidates pending reads before dispatch and refreshes after completion.
The service still enforces actor evidence, active-Album rules, append-only history
and logical membership only. The existing 50-item limit is retained. No schema or
physical-file action is introduced.

Regression tests use actual Qt widgets and retained Library workers with controlled
completion delivery, plus disposable SQLite membership/history validation. They
cover out-of-order responses, A/B/A selection, identical names with distinct UUIDs,
clearing, filters, Year navigation, refresh, payload mismatch, duplicate callbacks,
empty/archived Albums, wrong-context removal, confirmation-time selection changes,
legitimate addition/removal, bounded owner authority and thumbnail generations.
The existing worker lifetime and preview identity checks are retained.

This is a UI request-context guarantee for one Library page. Backend transaction
and concurrent-writer rules remain those of the existing catalogue services; this
change does not introduce cross-process locking or a new asynchronous framework.
