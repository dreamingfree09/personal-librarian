# Catalogue maintenance and physical command modes

This describes the public correction candidate. It does not approve a release,
production adoption, a general ACTION mode, or changes to existing owner data.

## Bootstrap and recovery

Bootstrap and recovery are exclusive Windows maintenance operations supported
only on fixed local NTFS volumes with Python 3.13. UNC/network paths, mapped
network drives, non-NTFS, removable/unknown drives and reparse-path traversal are
explicitly rejected for maintenance. Recovery's selected backup files must also
be local NTFS inputs. This restriction does not redefine other backup workflows.
Close the
desktop application and other catalogue connections first. A create-only
maintenance lease coordinates Librarian processes. Windows file handles exclude
other SQLite readers/writers during replacement; a competing connection causes
the operation to fail before replacement. Publication uses Windows atomic
no-replace rename, never overwrite-on-collision.

Bootstrap retains failed staging databases and their sidecars. A destination
created by another actor is preserved. Existing destination WAL/SHM state is
not adopted or removed.

Recovery validates the selected immutable backup, stages identical snapshot
bytes, verifies its integrity, foreign keys, identity, schema and logical dump,
and preserves the original database, WAL and SHM under a unique recovery name.
It does not delete a genuine WAL. Before reporting success it checks the final
file identity and exact snapshot bytes under the exclusion handle, and requires
that no old WAL/SHM remain at the live name. The final logical-state assertion is
grounded in byte equality to the already logically verified selected snapshot;
it is not a second ordinary SQLite open while the exclusion handle is held.

An ordinary failed promotion or verification restores the original file set
without overwriting intervening files. A failed replacement is retained. The
durable recovery journal records intended transitions, original file hashes,
preserved locations, selected snapshot identity, outcome and rollback status.

Before the first preservation or publication rename, lease retention is armed.
It stays armed even if Windows completes a rename and an interruption prevents
the caller from receiving its return value. Rollback reconciles actual original
and preserved locations against the held handles and recorded device/file-index
identities, then verifies every recorded hash and the absence of unexpected
sidecars. It does not trust a list of completed calls. A same-content file with
a different physical identity is not adopted. Only a durably journaled verified
publication or fully verified restoration permits lease removal.

Windows identity is the pair `(st_dev, st_ino)` obtained from Python's path stat
and held-descriptor fstat interfaces; a zero file index or a non-regular/reparse
file is rejected. Native NTFS tests check that this pair stays equal across a
rename and differs for two separate files containing identical bytes. These
results are not extrapolated to UNC, SMB, ReFS, FAT or other filesystems.

## Interrupted maintenance

An abrupt process termination leaves the maintenance lease in place. Normal
Librarian catalogue access refuses an active or abandoned lease. A failed
rollback also retains the lease and reports `offline-recovery-required`.
There is deliberately no timeout-based lease stealing or automatic cleanup.
Bootstrap also retains a publication journal with the staged snapshot identity,
hash and both names. An interruption immediately after bootstrap publication
keeps the lease until offline review; it is not treated as an accepted bootstrap.

Do not remove an unexplained lease, delete sidecars, or open preserved evidence
in place. Keep the application offline. Review the matching attempt ID and
recovery journal, identify each original file at its original or preserved
location, and verify its recorded hash. Establish rollback in a separate
disposable directory using the complete original DB/WAL/SHM set; check integrity
and the expected pre-recovery logical state there. This candidate does not offer
an automatic crash-resume command. Any live repair or lease removal requires an
explicit operator recovery decision after that proof. An intervening catalogue
must not be overwritten to force rollback.

The guarantees concern supported Windows local-file operations and process
interruption. They are not a guarantee against failing hardware, filesystem
corruption, or a privileged actor independently renaming/deleting evidence.

## Physical quarantine and restore

An explicitly supplied `--mode read-only` or `--mode dry-run` rejects physical
quarantine execute/restore before dispatch, even when confirmation is supplied.
Read-only status and history remain available.

To intentionally use the separately approved M19 narrow physical contract, omit
`--mode` and supply the existing operation-specific confirmation. Omitting mode
does not bypass approval, canonical, path, hash, same-volume or confirmation
checks. Logs label this route `narrow-quarantine-contract`; other media commands
default to read-only. General `--mode action` remains unavailable.

## Validation scope

Regression fixtures are synthetic and disposable. Coverage includes concurrent
bootstrap processes, intervening publication, retained staging, crash-left WAL,
selected-state restoration, existing/new competing SQLite connections, failed
promotion, failed verification, sidecar interruption, abrupt process exit,
offline rollback proof and rollback collision. CLI dispatch tests mock the
physical executors.
