# Desktop state containment

Thumbnails and preferences retain the original approved application-data root.
Their state I/O uses fixed local Windows NTFS only, with no reparse ancestors,
UNC roots, mounted-folder redirection or hard-linked state files. This stricter
state contract does not globally prohibit ordinary UNC catalogue/source paths.

Existing ancestors are opened without following reparse points, inspected by
handle and held without write/delete sharing during traversal and reads. Missing
directories are created only under the approved root, then opened and inspected
before descending. Final reads use a checked non-reparse, single-link handle;
they never trust a later pathname reopen. The Qt worker receives validated PNG
bytes, not an unchecked path to load after containment handles have closed.

Writes use exclusive unique temporary objects, flush completed bytes, then rename
the open object relative to its held parent handle. For publication only, that
parent retains a no-delete pin while its write-sharing restriction is relaxed:
NTFS refuses directory redirection while our non-deletable temporary object keeps
it nonempty. Higher ancestors retain strong handles. In-process state I/O is
serialized; decoding remains concurrent. Incompatible external handles fail closed.
Cache publication never replaces a competing winner; the actual
winner is read and validated. Preferences intentionally use last-completed-save
wins via directory-entry replacement. They never write through an existing link.
Malformed preferences recover to defaults; partial cache entries are rejected.

If an interruption makes the rename outcome uncertain, complete published bytes
or private temporary evidence are preserved. Temporary names are never read as
accepted cache entries. Failed pre-publication writes discard only the open
temporary object by handle. This does not claim power-loss durability of a
multi-file transaction or hostile-administrator/kernel/volume-remount protection.
Incompatible handles, unsupported filesystems and uncertain checks fail closed.

Native synthetic tests exercise junctions, file links, hard links, ancestors above
the root, denied ancestor replacement/write handles, concurrent generators and
interruptions before and immediately after successful publication. Accepted Pillow
decoder restrictions remain in force. Detailed baseline reproductions remain private.

Windows API contracts: [CreateFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[reparse operations](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points-and-file-operations),
[nonempty-directory restriction](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points),
[native rename](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/content/ntifs/nf-ntifs-ntsetinformationfile).
