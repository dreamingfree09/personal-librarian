# M25 - Release Candidate 0.1.0rc2

Status: local unsigned release candidate prepared for owner usability review

RC2 remains the accepted M25 baseline. It is superseded for M26 owner UX review by the
local `0.1.0rc3` candidate documented in `M26_DESKTOP_UX_REFINEMENT.md`.

## Identity and provenance

- Canonical version: `0.1.0rc2`
- Archive: `PersonalLibrarian-0.1.0rc2-win64.zip`
- Base source commit: `f28b34d`
- Source state: uncommitted M25 release-validation working tree; not a clean tagged release
- Expected catalogue schema: 8; M25 introduces no schema migration
- Validated target: Windows 11 Pro 64-bit only

The generated JSON manifest records the exact build timestamp, current Git commit,
working-tree status, platform, tooling versions, file count, sizes, and hashes. Generated
release files are local and ignored by Git; nothing is uploaded or published.

RC2 supersedes RC1 for owner testing. RC1 allowed a stale asynchronous thumbnail result
from a previously selected group to populate a reused preview-list row. RC2 binds every
result to its immutable context, generation, physical-instance ID, and source path;
stale results are discarded and per-instance cache evidence is isolated.

## What works

The portable one-folder application provides Overview health and disaster-recovery
status, bounded exact-duplicate and similar-image review, real read-only image previews
with zoom, explicit owner canonical decisions, and read-only Decisions, Plans,
Quarantine, and Backups / Recovery sections. Python and the repository are not runtime
requirements.

## Safety boundaries

Production application data and independent backups remain outside the application
distribution. The package contains no catalogue, media, credentials, root defaults, or
smoke artefacts. M25 adds no delete, overwrite, generic copy/move/rename execution,
quarantine/restore controls, catalogue-recovery controls, automatic canonical choice,
media scan, re-hash, or similarity regeneration. One-folder contents must remain intact.

## Prerequisites and launch

The owner needs an existing schema-8 application-data root and may provide an existing
independent-backup root. Extract the complete ZIP to a new versioned folder. Either
double-click `PersonalLibrarian.exe` and select the roots, or run:

```powershell
.\PersonalLibrarian.exe `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

The root-selection dialog validates but never creates or migrates a catalogue.

## Verify checksums

From the folder containing the ZIP, calculate its SHA-256:

```powershell
Get-FileHash -Algorithm SHA256 .\PersonalLibrarian-0.1.0rc2-win64.zip
```

After extraction, calculate the executable SHA-256:

```powershell
Get-FileHash -Algorithm SHA256 .\PersonalLibrarian\PersonalLibrarian.exe
```

Compare the results with `PersonalLibrarian-0.1.0rc2-win64.sha256` and the JSON manifest.
Final locally generated values:

- Archive size: `66,808,856 bytes` (approximately 63.7 MiB)
- Archive SHA-256: `ABE815015CA195417E0302FD18AAE214CE7CCB080413C7967C55050E6B340679`
- Executable SHA-256: `D362FF3DCB0259CC79818F00C57AE05897C2E908B63B99BCEC3E97B803C62F7C`
- Packaged files: `221`

## Clean-extraction validation

The exact ZIP above was extracted beneath `%LOCALAPPDATA%\Temp`, outside the repository.
The extracted executable hash matched the manifest and it exited successfully after a
bounded frozen-runtime smoke. `sys.path` contained only the extracted distribution's
`_internal` paths; neither the repository nor a system Python installation was used.

Against the explicitly supplied external roots, production health and DR readiness were
both `PASS`; Overview, exact review, similar review, Decisions, Plans, Quarantine, and
Backups / Recovery loaded. A real image produced a valid large preview and its source
size and modification time remained unchanged. No forbidden controls were present and
no production decision/action records were created.

## Manual update

1. Close Personal Librarian.
2. Leave `<data-root>` and `<backup-root>` unchanged.
3. Retain the previous application folder as the known-good build.
4. Verify and extract the new ZIP into a separate versioned folder.
5. Launch the new executable against the same external roots.
6. Confirm Overview health and DR status, then perform the owner checklist.
7. Remove the old application folder only after the owner confirms the new build works.

Changing application binaries alone must not trigger production-data migration.

## Rollback

Close the current application and relaunch the previous known-good one-folder build
against the same external production and backup roots. This candidate remains compatible
with schema 8 and introduces no migration. If a future release changes schema
compatibility, use that release's documented catalogue backup/recovery procedure rather
than assuming an older executable can open the newer catalogue.

## Signing and installer decisions

The candidate is unsigned. Windows may display Microsoft Defender SmartScreen or
unknown-publisher warnings, particularly after download or transfer. Signing is not a
blocker for this owner's local/internal v0.1 evaluation. A later signed release would
need an appropriate code-signing certificate or managed signing service, secured key
handling, timestamping, signing of the executable and distribution, and release-time
signature verification.

M25 uses a portable one-folder ZIP. This keeps Qt dependencies visible, makes rollback a
folder switch, and avoids introducing installer state. Inno Setup is a reasonable later
option for a conventional shortcut/uninstall experience; WiX adds more Windows Installer
complexity than this personal candidate needs. No installer is justified for M25.

## Owner usability pass

After checksum verification and launch, follow
[`M25_OWNER_USABILITY_CHECKLIST.md`](M25_OWNER_USABILITY_CHECKLIST.md). Record observations
without performing destructive actions in
[`M25_OWNER_USABILITY_FEEDBACK.md`](M25_OWNER_USABILITY_FEEDBACK.md).

## Known limitations

- Unsigned; SmartScreen or unknown-publisher warnings are possible.
- Portable one-folder only; no installer or automatic updater.
- Validated on Windows 11 Pro 64-bit, not other Windows versions.
- No custom application icon.
- First root validation may take several seconds on a large catalogue.
- Video previews remain placeholders.
- Rich capture-date metadata remains limited by existing catalogue evidence.
- This is an uncommitted local candidate, not a clean tagged public release.
