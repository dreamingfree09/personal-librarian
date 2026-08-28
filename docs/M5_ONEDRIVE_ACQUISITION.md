# M5 - OneDrive Acquisition

**Status:** COMPLETE
**Completed:** 17 August 2026
**Verified destination:** H:\PersonalLibrary\Staging\OneDrive

## Objective

Acquire the relevant OneDrive photo/video source populations into locally controlled storage without deleting or modifying the OneDrive originals.

## Source groups

- `onedrive-personal:Desktop/photos`
- `onedrive-personal:Pictures/Screenshots`
- `onedrive-personal:Pictures/Camera Roll`

## Final destination groups

- `H:\PersonalLibrary\Staging\OneDrive\DesktopPhotos`
- `H:\PersonalLibrary\Staging\OneDrive\Screenshots`
- `H:\PersonalLibrary\Staging\OneDrive\CameraRoll`

## Acquisition method

The final accepted acquisition was performed directly from Microsoft OneDrive cloud to H: using rclone v1.75.0.

This bypassed Windows OneDrive Files On-Demand hydration on C: and completely bypassed the retired Z: device.

The operation used copy semantics. OneDrive originals were not deleted, moved or renamed.

## Final catch-up

A final catch-up copy was run immediately before verification.

- DesktopPhotos: 0 new files
- Screenshots: 46 new files, approximately 13.177 MiB
- CameraRoll: 0 new files

All three catch-up operations completed with exit code 0.

## Final verification

Final verification used read-only `rclone check --one-way` from OneDrive cloud against H:.

Results:

- DesktopPhotos: 18,678 matching files; 0 differences; exit code 0
- Screenshots: 4,335 matching files; 0 differences; exit code 0
- CameraRoll: 583 matching files; 0 differences; exit code 0

**Total verified source-folder files: 23,596**

No differences were found in any of the three source groups.

## Storage incident context

An earlier acquisition to Z: completed but could not be accepted because the Z: device subsequently produced repeated physical I/O and NTFS failures.

The accepted M5 dataset was therefore reacquired independently from OneDrive directly to the validated H: HDD.

Z: is not part of the accepted M5 chain of custody.

## Exit criteria

- Relevant OneDrive source folders acquired locally: PASS
- OneDrive originals left untouched: PASS
- Destination independent of failed Z: device: PASS
- Final remote-to-local verification completed: PASS
- Zero differences across all source groups: PASS

## Decision

**M5 - OneDrive Acquisition is COMPLETE.**

The project may proceed to M6 - Google Photos Acquisition.
