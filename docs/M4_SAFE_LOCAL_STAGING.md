# M4 Safe Local Staging

> Recovery reconstruction created 17 August 2026 after failure of the former Z: working drive.
> This document reconstructs the known M4 design and decisions from previously verified project records.

## Purpose

M4 created a safe local staging structure for Personal Librarian acquisitions.

Staging exists so source material can be copied and verified without mixing sources, renaming originals, deleting duplicates, or prematurely declaring files canonical.

## Core rule

Staged does not mean canonical.

The acquisition sequence remains:

Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act

## Original staging root

During M4 the staging root was:

`Z:\PersonalLibrary\Staging`

Following the Z: storage failure on 17 August 2026, the temporary replacement root is:

`H:\PersonalLibrary\Staging`

The logical structure remains unchanged.

## Source-separated staging areas

The M4 structure established separate acquisition areas for:

`OneDrive`

`GooglePhotos`

`CurrentPhone`

`HistoricalSources\Dropbox`

`HistoricalSources\HDD_Disk2`

`HistoricalSources\OldPhones`

`HistoricalSources\Network`

Source populations must remain distinguishable during acquisition.

## OneDrive staging groups

M5 uses three principal OneDrive media groups:

- DesktopPhotos
- Screenshots
- CameraRoll

These map back to:

- OneDrive\Desktop\photos
- OneDrive\Pictures\Screenshots
- OneDrive\Pictures\Camera Roll

## Staging safety rules

- Copy only during acquisition.
- Never move source files as part of ingestion.
- Do not delete from the source.
- Do not rename source files.
- Do not merge source populations yet.
- Do not deduplicate destructively during staging.
- Do not reorganise into year/event folders during acquisition.
- Keep source-relative paths where useful.
- Preserve unusual files until later analysis.
- Preserve zero-byte entries.
- Verify before considering an acquisition complete.

## Cloud placeholders

A OneDrive filename visible through Files On-Demand is not proof of a local copy.

M5 therefore records storage state and distinguishes cloud-only files from files whose contents are locally available.

Cloud-backed data remains protected by the cloud source until a verified acquisition exists.

## Verification

Verification evidence may include:

- file counts
- byte counts
- source/destination size comparison
- SHA-256 where appropriate
- provider-supported checksums
- explicit successful acquisition records

A failed or interrupted verification does not justify deleting either copy.

## Quarantine and destructive operations

M4 does not provide an automatic delete path.

Later duplicate handling should favour:

- recommendation
- human approval
- quarantine
- rollback

over immediate permanent deletion.

## Programme versus library

The programme serves the library.

The library does not belong to the programme.

Application files, Git history and scripts are therefore logically separate from the preserved Personal Library data.

## Temporary H: recovery layout

Following retirement of Z:, the temporary working arrangement is:

- `H:\PersonalLibrarian` - programme, scripts, documentation and repository
- `H:\PersonalLibrary` - staging and preserved acquisitions

This H: arrangement is temporary until the planned server/NAS becomes available.

## M4 completion state

M4 successfully established the safe staging model and source-separated directory structure.

The project then advanced to M5 OneDrive Acquisition.

## Recovery note

The original M4_SAFE_LOCAL_STAGING.md Git blob was lost when the former Z: device became unreadable.
This reconstruction preserves the known M4 structure and safety decisions but does not claim byte-for-byte identity with the lost original.
