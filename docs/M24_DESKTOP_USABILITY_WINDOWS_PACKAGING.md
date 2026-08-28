# M24 - Desktop Usability and Windows Packaging

Date: 23 August 2026

Status: usability implementation, standalone build, and packaged production smoke complete; pending owner close-out

## Scope and preserved architecture

M24 retains the M23 PySide6 architecture: one local Python/Qt process over existing
backend services. Widgets do not own catalogue business rules. No browser frontend,
API process, automatic canonical selection, delete, generic filesystem execution,
desktop quarantine/restore, or production-recovery control was added.

## Exact-review usability

Exact review retains bounded paging and lazy detail while adding:

- adjustable 25/50/100 group pages and 128/160/192/256-pixel thumbnails;
- clearer instance rows with source, raw/current path, extension, human-readable size,
  created/modified evidence, full SHA-256, and archival/display badges;
- richer preview captions with filename, source, and content identity;
- selected-instance focus between comparison table and preview list;
- explicit Copy path and Copy SHA-256 controls;
- Alt+Up/Alt+Down group navigation and Ctrl+PageUp/Ctrl+PageDown paging; and
- Enter/double-click preview opening.

No row is ranked, scored, recommended, or automatically selected as canonical.

## Similar-review usability and filters

Similar review remains explicitly distinct from exact identity. It retains pHash/dHash
ranges, review tiers, relationship evidence, separate content IDs, and large-cluster
warnings. Its filter menu offers All, Pending, Decided, and Large groups. Large filtering
is performed by the bounded backend queue before pagination rather than hiding rows only
after a page is loaded.

Exact filters are All, Pending, Decided, and Abstained. No search engine or inferred
quality/date policy was introduced.

## Read-only preview viewer

Double-click or Enter opens the selected supported image in a larger read-only viewer.
The larger derivative is decoded in a Qt worker using the established safe thumbnail
service with a 1600x1200 cap. The dialog supports:

- Ctrl++ / Ctrl+- zoom;
- Fit (`F`);
- 100% (`1`);
- mouse-drag panning; and
- Escape close.

Metadata remains selectable below the image. Unicode paths work. Missing, invalid,
zero-byte, unsupported, or safety-rejected sources show a concise error. Videos remain
placeholder-only; ffmpeg was not added.

## Decision UX

Nomination and approval remain separate actions. Confirmation now shows action, scope,
actor, exact context, target instance, and current/raw path. Optional reason remains
available. Successful writes show the resulting scope state; backend stale/conflict
errors remain authoritative and visible. Catalogue health continues to fail closed for
decision writes.

## Preferences

Harmless preferences are stored as versioned JSON at:

`<app-data-root>\state\ui_preferences.json`

They include window geometry, navigation/review splitter sizes, last section, page size,
and thumbnail size. Invalid versions, malformed JSON, or out-of-range values recover to
safe defaults. Preferences contain no roots, decisions, plans, canonical state, or media
truth; SQLite remains authoritative.

## Status and accessibility

The header calmly distinguishes production and DR `PASS` / `WARN` / `FAIL` state and
schema. F5 refreshes the current page and health. Major controls have accessible names
or tooltips, tables retain copyable detail, and preview zoom has keyboard equivalents.
M24 does not claim full accessibility certification.

## Packaging choice

M24 uses PyInstaller 6.22.2 as a build-only optional dependency. The one-folder format
was selected because Qt plugins and runtime DLLs remain visible and diagnosable, startup
does not require self-extraction, and correctness is easier to validate than a one-file
bundle.

Source-controlled packaging files are:

- `packaging/personal_librarian.spec`;
- `packaging/build_windows.ps1`;
- `packaging/desktop_entry.py`; and
- `packaging/version_info.txt`.

The build includes Python 3.13, PySide6/Qt plugins, Pillow, NumPy, SQLite support, and
Personal Librarian code. It excludes tests and bundles no catalogue, application-data
root, media, cache, credentials, or root configuration.

Build command:

```powershell
python -m pip install -e '.[build]'
.\packaging\build_windows.ps1
```

Generated `build\` and `dist\` directories are ignored by Git.

## Distribution and identity

The generated one-folder distribution is:

`H:\PersonalLibrarian\dist\PersonalLibrarian\`

Executable:

`H:\PersonalLibrarian\dist\PersonalLibrarian\PersonalLibrarian.exe`

The final distribution contains 221 files totalling 164,785,584 bytes (approximately
157.1 MiB). The executable is `PersonalLibrarian.exe`; Windows metadata records product
`Personal Librarian`, version `0.1.0`, and the desktop review description. No custom icon
was added because no suitable existing asset exists.

## Runtime root configuration

Normal packaged launch accepts external roots:

```powershell
PersonalLibrarian.exe `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

With no arguments, a small startup dialog selects an existing application-data root and
optional independent root. It validates the production catalogue and never bootstraps
one. No H: or X: runtime default is embedded, and roots are not persisted automatically.

## Repository-independence validation

The frozen executable was started from a fresh directory under `%LOCALAPPDATA%\Temp`,
not the repository. The report confirmed `sys.frozen = true`; `sys.path` contained only
the distribution's `_internal` archive, dynamic-library directory, and runtime root.
Neither `H:\PersonalLibrarian` source nor the temporary working directory was an import
path. Python, the editable installation, repository working directory, and repository
presence are therefore not runtime requirements for this distribution.

## Normal and packaged production smoke

The normal Qt shell and the frozen executable were both exercised against the explicit
production and independent roots. Results:

- production health `PASS`, DR readiness `PASS`, UUID/schema unchanged;
- exact review returned 50 of 7,707 groups and loaded a three-instance detail;
- similar review returned 50 of 5,067 groups and loaded a two-instance detail;
- Decisions, Plans, Quarantine, and Backups / Recovery opened;
- decision/plan/quarantine production counts remained zero;
- backup view found two operational and one independent backup;
- a real H: JPEG produced a 1600x1200-cap derivative and successfully exercised fit,
  100%, zoom-in, zoom-out, and pan-capable viewer construction;
- source size and mtime were unchanged; and
- no forbidden desktop controls were present.

The executable exited successfully from the bounded packaged smoke. A separate normal
launch enters the Qt event loop directly.

## Production safety invariants

Before and after both smokes:

- decision events: 0;
- action plans: 0;
- action executions: 0;
- action execution events: 0;
- recovery-required executions: 0; and
- quarantine records: 0.

The production database byte hash remained unchanged where checked. Thumbnail and UI
preference state grew only under the approved application-data `state` directory. No
media was scanned, re-hashed, moved, renamed, quarantined, restored, overwritten, or
deleted. Z: and the unavailable NAS/server were not accessed.

## Limitations

- The distribution is unsigned and has no installer or automatic update mechanism.
- One-folder deployment must remain intact; moving only the EXE is unsupported.
- First launch validates roots synchronously and may take several seconds for a large
  catalogue.
- No custom Windows icon exists yet.
- Videos remain placeholders.
- Rich date/capture metadata depends on future catalogue evidence; no precedence was
  invented.
- PyInstaller reported conventional optional/cross-platform missing-module warnings;
  packaged runtime smoke passed with all required Windows modules.

## Recommended next milestone

M25 should establish owner-facing release engineering: code signing decision, versioned
release archive/checksums, supported update/rollback procedure, and optional installer
evaluation. It should also gather real owner feedback on review ergonomics before any
new physical-action UI is considered.
