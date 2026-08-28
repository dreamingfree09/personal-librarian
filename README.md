# Personal Librarian

Personal Librarian is a local-first, privacy-oriented, catalogue-driven desktop application
for preserving, organising, searching and protecting personal digital material. It is
non-destructive by design: catalogue organisation and review do not alter source media.

Photographs and videos are the first operational priority. Future expansion may include documents, scans, saved web content, notes and locally assisted AI search.

## Canonical Project Definition

Before making substantial architectural or implementation changes, read:

- `PROJECT_TRUTH.md`

`PROJECT_TRUTH.md` is the canonical architectural source of truth for this project.

The frozen initial architecture baseline is retained as:

- `PROJECT_TRUTH.v0.2.BASELINE.RECONSTRUCTED.md`

## Safety Principle

`Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Plan -> Preflight -> Act -> Verify`

Personal Librarian is preservation-first. Destructive operations must not be introduced casually.

## Repository Boundary

This repository contains application code, documentation, tests, scripts and configuration.

It must not contain the user's Personal Library, private media, personal documents, secrets, AI models, generated caches or production data.

Catalogue databases, backups, thumbnails, generated inventories, release builds and the
personal-data root are external to this repository. The application does not bootstrap or
silently select a production catalogue.

## Current Phase

M30 - Preferred Date Evidence and Cross-Year Collections Design/Foundation - COMPLETE

The project is pre-1.0. M30 completed the explicit, auditable preferred-date evidence foundation, schema-10
cross-year Collections services and desktop integration, canonical RC7 packaging, and the
initial catalogue-only production population. All 69,444 eligible physical instances have
one checkpoint; 8,843 identities are resolved, 47,284 remain safely Unknown, and none need
review. Richer date evidence from EXIF, video capture timestamps and trusted sidecar metadata,
along with semantic/AI analysis and physical media reorganisation, is future separately
approved work. Organisation does not alter media.

The current source/package version is `0.1.0rc7` and the current catalogue schema is 10.
RC7 build artefacts are local generated output; they are not tracked in this source repository
and are not publication assets unless separately approved for a future GitHub Release.

## Development setup

Python 3.13 is required. The desktop uses PySide6, and perceptual image analysis uses Pillow
and NumPy; no GPU or separate scientific-computing stack is required. Windows PowerShell is
required for the supplied Windows packaging scripts.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

For Windows packaging, install the build-only extra:

```powershell
python -m pip install -e '.[build]'
```

## Desktop review interface

M23 adds a local PySide6 desktop interface over the existing production catalogue and
backend services. Launch it with explicit roots:

```powershell
personal-librarian desktop `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

The interface provides a bounded year-centred Library, preferred-date evidence detail,
cross-year Collections, confirmed manual album/tag organisation, read-only organisation
history, bounded exact/similar review, append-only owner canonical decisions, and read-only
plans, quarantine, backup, and recovery visibility. Nomination and approval are separate
confirmed actions. Delete, generic execution, GUI quarantine/restore, catalogue restore,
and physical organisation are unavailable.

The standalone one-folder build launches directly from:

```powershell
dist\PersonalLibrarian\PersonalLibrarian.exe `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

If launched without arguments, it asks the owner to select an existing application-data
root and optional independent-backup root. It never bootstraps a catalogue. Production
data remains external and must not be copied into the distribution.

Build on Windows with:

```powershell
.\packaging\build_windows.ps1
```

Build the complete local release candidate, including the one-folder build, portable ZIP,
SHA-256 files, and JSON manifest, with:

```powershell
.\packaging\build_release.ps1
```

Generated output under `build\`, `dist\`, and `release\` is ignored by Git and must not be
committed to the source repository. Extract the
versioned ZIP to a new folder and keep its `PersonalLibrarian` contents together. Launch
`PersonalLibrarian.exe` with no arguments to select existing external roots, or provide
the explicit `--app-data-root` and optional `--independent-backup-root` arguments shown
above. Neither Python nor this repository is required on the target machine.

Run the CLI:

```powershell
personal-librarian version
personal-librarian doctor
personal-librarian config show
personal-librarian safety check-path '<path>'
personal-librarian catalogue init --database '<data-root>\catalogue.sqlite3'
personal-librarian catalogue status --database '<data-root>\catalogue.sqlite3'
personal-librarian catalogue import-evidence --help
personal-librarian inventory scan --help
personal-librarian hash sha256 --help
personal-librarian exact-duplicates report --help
personal-librarian pipeline reconcile --help
personal-librarian similarity hash --help
personal-librarian similarity analyse --help
personal-librarian similarity report --help
personal-librarian similarity reconcile --help
personal-librarian review exact list --help
personal-librarian review exact show --help
personal-librarian review similar list --help
personal-librarian review similar show --help
personal-librarian decision nominate --help
personal-librarian decision approve --help
personal-librarian decision reject --help
personal-librarian decision supersede --help
personal-librarian decision abstain --help
personal-librarian decision current --help
personal-librarian decision history --help
personal-librarian albums list --help
personal-librarian albums create --help
personal-librarian albums show --help
personal-librarian albums rename --help
personal-librarian albums archive --help
personal-librarian albums restore --help
personal-librarian albums add-content --help
personal-librarian albums remove-content --help
personal-librarian albums members --help
personal-librarian albums for-content --help
personal-librarian albums history --help
personal-librarian plan create --help
personal-librarian plan list --help
personal-librarian plan show --help
personal-librarian plan preflight --help
personal-librarian plan report --help
personal-librarian plan invalidate --help
personal-librarian quarantine execute --help
personal-librarian quarantine status --help
personal-librarian quarantine history --help
personal-librarian quarantine reconcile --help
personal-librarian quarantine restore --help
personal-librarian production bootstrap --help
personal-librarian production health --help
personal-librarian production recover --help
personal-librarian catalogue backup create --help
personal-librarian catalogue backup list --help
personal-librarian catalogue backup verify --help
personal-librarian catalogue backup report --help
```

Run the standard targeted validation:

```powershell
python -m unittest discover -s tests -v
```

Catalogue health and backup commands require explicit external data and backup roots. Both
operational and independent freshness thresholds are seven days. Live backups use the SQLite
backup API and versioned manifests; no scheduler, generic action mode, or delete/overwrite
path exists. Core catalogue and desktop workflows are local-first and do not upload personal
media. Cloud acquisition, richer capture-metadata ingestion, and semantic/AI analysis are not
part of the current release.
