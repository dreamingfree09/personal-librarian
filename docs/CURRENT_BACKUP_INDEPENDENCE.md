# Current independent-backup readiness

Creation-time device identities remain unchanged in backup manifests. They are
historical provenance, not proof of present physical separation. Each readiness
evaluation measures current production and backup storage, verifies snapshot
integrity/schema/catalogue identity/freshness, then measures the actual selected
snapshot path again. Unknown, unavailable or changed topology cannot produce PASS.
Same-device results produce FAIL even when the snapshot itself is accepted.

The report exposes `current_device_independence`, current identities and stability,
separately from `historical_*` fields. The existing desktop DR status displays this
newly calculated summary; catalogue health remains a separate assessment.

The Windows provider queries only the requested local volume and the single disk
reported by its extent. Multiple volumes on that disk share an identity. It does
not enumerate other drives, treat drive letters as physical identities, or infer
separation from POSIX volume numbers. Supported measurement is deliberately narrow:
fixed local NTFS, no reparse ancestors, one disk extent, and an OS-reported directly
attached ATA/USB/SATA/NVMe transport. RAID, SCSI/SAS, virtual/file-backed storage,
Storage Spaces, network and unknown topologies require separate proof and return
unknown. Inability to query without sufficient privileges also returns unknown.

These disk numbers are transient, within-evaluation identities, not permanent UUIDs.
The result is a point-in-time measurement under the trusted Windows storage stack,
not a guarantee against subsequent hotplug, controller deception, hidden shared
infrastructure or common power/enclosure failure. Old backups/manifests are not
rewritten to satisfy readiness. Native development tests use synthetic snapshots
and a controlled device provider, not owner backup-device enumeration.

Windows contracts: [volume disk extents](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_volume_get_volume_disk_extents),
[storage query](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_storage_query_property),
[device descriptor](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ns-winioctl-storage_device_descriptor).
