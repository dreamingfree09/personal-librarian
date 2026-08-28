# M2 Source Ledger

> Recovery reconstruction created 17 August 2026 after failure of the former Z: working drive.
> This document reconstructs the known M2 inventory from previously verified project records.

## Purpose

M2 established where Personal Librarian source material currently exists before any destructive organisation or deduplication.

Core rule: Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act.

No source is deleted merely because it has been discovered or copied.

## Current computer

- Host: `<local-workstation>`
- User: `<user>`
- Windows 11 Pro, 64-bit
- CPU: AMD Ryzen 7 5800X
- RAM: approximately 64 GB
- GPU: AMD Radeon RX 5700 XT

## Physical storage inventory

### Disk 0
- Former working device: 4 TB SATA SSD
- Windows model: SSD 4TB
- Serial: `<redacted-machine-serial>`
- Former volume: Z:
- Status after 17 August 2026 incident: retired from Personal Librarian use due repeated I/O and NTFS delayed-write failures.

### Disk 1
- Kingston A400 240 GB SATA SSD
- Volume: X:
- Approximate usable size: 223.57 GB
- General software/archive use.

### Disk 2
- WDC WD1002FBYS-18W8B1
- 1 TB SATA HDD
- Serial: `<redacted-machine-serial>`
- Volumes: G: and H:
- G: approximately 91.62 GB
- H: approximately 839.84 GB
- H: current temporary Personal Library working location after Z: retirement.

### Disk 3
- Samsung SSD 860 EVO M.2 500 GB
- Volume: C:
- Windows / OS volume
- Approximate usable size: 464.81 GB

### Disk 4
- Crucial T500 1 TB NVMe SSD
- Volume: E:
- Approximate usable size: 931.51 GB
- Existing Steam / coding use.

## Cloud and synchronised sources

### Microsoft OneDrive
- Local root: `C:\Users\<user>\OneDrive`
- OneDrive and OneDriveConsumer both point to this root.
- OneDriveCommercial was empty during audit.
- OneDrive Files On-Demand is in use.
- Phone Camera Upload is enabled.
- Phone upload includes videos.
- Selected phone folders observed: Camera, Tapo, Screen recordings, Screenshots.

Primary M5 acquisition source groups identified:

- `C:\Users\<user>\OneDrive\Desktop\photos`
- `C:\Users\<user>\OneDrive\Pictures\Screenshots`
- `C:\Users\<user>\OneDrive\Pictures\Camera Roll`

Additional candidate OneDrive source:

- `C:\Users\<user>\OneDrive\Scans`

OneDrive must remain intact until an independently verified replacement exists.

### Google Photos / Google account
- Google Photos Backup is enabled on the current phone.
- Google remains an acquisition/safety source, not the intended canonical master.
- M6 is reserved for Google Photos acquisition.

### Dropbox
- Local Dropbox root: `C:\Users\<user>\Dropbox`
- Dropbox is treated as a separate historical/source population.

## Current phone

- Current phone contains active photo/video acquisition sources.
- Google Photos Backup is enabled.
- OneDrive Camera Upload is enabled.
- Current-phone ingestion is M7.
- Existing cloud backup behaviour must not be disabled until replacement workflows are proven.

## Historical sources

### WD HDD / Disk 2
- G: and H: contain existing historical material.
- These files are source material and must remain separate from newly acquired library data.
- M8 is reserved for systematic historical-source acquisition.

### Old phones
- Old-phone media is a known future source category.
- Preserve as HistoricalSources/OldPhones during acquisition.

### Network storage
- L: previously mapped to:
- `<private-network-host>\<share>\<historical-project-path>`
- This was a network project path, not a Personal Library canonical root.

## Active synchronisation observed during M2

- OneDrive.exe
- OneDrive.Sync.Service.exe

## Personal Librarian storage model

The programme and the library are separate concepts.

Original design:
- Z:\PersonalLibrarian - application, scripts, repository and documentation
- Z:\PersonalLibrary - preserved data and staging

Recovery design from 17 August 2026:
- H:\PersonalLibrarian - temporary application/repository location
- H:\PersonalLibrary - temporary preserved library location

Long-term intended destination: server/NAS storage once available.

Principle: The programme serves the library. The library does not belong to the programme.

## Source categories

1. OneDrive
2. Google Photos
3. Current phone
4. Dropbox
5. Historical HDD material
6. Old phones
7. Network / NAS sources
8. Other local drives discovered during later inventory

## Safety rules established during M2

- Inventory before deletion.
- Copy rather than move during acquisition.
- Never treat a cloud placeholder as a verified local copy.
- Keep sources separated during staging.
- Preserve zero-byte and unusual files until later analysis.
- No automatic AI deletion.
- Prefer quarantine and rollback to destructive cleanup.
- Source remains authoritative until copied and verified.

## M2 completion state

M2 established the initial source inventory and source classifications.

The project then advanced through M3 Backup Behaviour Audit and M4 Safe Local Staging before beginning M5 OneDrive Acquisition.

## Recovery note

The original M2_SOURCE_LEDGER.md Git blob was lost when the former Z: device became unreadable.
This reconstruction preserves the known source inventory and operational decisions but does not claim byte-for-byte identity with the lost original.
