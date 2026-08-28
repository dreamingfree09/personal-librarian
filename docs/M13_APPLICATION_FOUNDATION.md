# M13 - Application Foundation and Safety Boundaries

Date: 21 August 2026

Status: In progress; foundation implemented for review

## Purpose

M13 introduces the first reusable Personal Librarian application foundation. It contains no media scanning, catalogue, canonical-selection or file-changing workflow.

The governing sequence remains:

`Discover -> Copy -> Verify -> Analyse -> Recommend -> Approve -> Act`

## Architecture added

The Python 3.13-compatible package uses a `src` layout:

- `personal_librarian.cli` - central command-line interface
- `personal_librarian.config` - typed, explicit-only TOML configuration
- `personal_librarian.safety` - central path and operation-mode policy
- `personal_librarian.logging_setup` - structured console logging
- `personal_librarian.jobs` - in-memory UUID run context

Runtime code uses only the Python standard library. Setuptools is constrained as the packaging build backend; it is not an application runtime dependency.

## Safety model

M13 recognises read-only, dry-run and future action modes. Only read-only and dry-run are exposed by the CLI. Neither can authorise a write. Action mode is represented for future design compatibility but is explicitly unavailable.

The central path policy:

- rejects `Z:` case-insensitively for read and write intent;
- rejects explicit, drive-relative and relative-via-base references to Z:;
- assesses relative paths against an explicit base or the current working directory;
- distinguishes Windows drive, UNC, device and malformed paths;
- returns a structured decision code, reason, raw path and lexically assessed path; and
- performs no filesystem access during assessment.

Raw path text remains available and is not replaced by the assessed comparison form.

## Configuration

Configuration is optional and must be supplied explicitly with `--config`. With no file, both future roots remain unset.

Supported TOML fields are:

```toml
[paths]
project_root = "C:\\absolute\\project"
data_root = "H:\\absolute\\data"
```

Roots must be absolute Windows drive or UNC paths and must pass the central safety policy. Configuration loading rejects unknown fields and malformed TOML. It does not check root existence or enumerate configured directories.

## CLI commands

After an editable installation:

```powershell
personal-librarian version
personal-librarian doctor
personal-librarian config show
personal-librarian safety check-path <path>
```

Global options include `--config`, `--mode read-only|dry-run` and `--verbose`. `safety check-path` also accepts `--intent read|write` and an optional `--base`. A write-intent check is only a policy assessment; M13 refuses to authorise the operation.

The doctor command reports Python/package versions, the current working directory, configuration state, retired-Z rejection and action-mode rejection. It does not scan media, invoke rclone or contact services.

## Logging and runs

Each CLI execution receives a UUID run ID and UTC start time. Console logs include UTC timestamp, level, run ID, component and a human-readable message. M13 creates no log files or job database.

## Historical M5 script

`scripts/Invoke-M5OneDriveAcquisition.ps1` retains its historical body and records the original recovered blob hash, but now has an immediate fail-fast guard before any path construction or filesystem access. It cannot proceed to its retired destination workflow.

## Tests and validation

The standard targeted validation command is:

```powershell
python -m unittest discover -s tests -v
```

Tests cover retired-drive rejection, case handling, safe and relative paths, UNC validation, operation modes, UUID run IDs, configuration validation, CLI smoke behavior and the historical M5 fail-fast guard. They use temporary configuration files only and do not depend on personal media or Z:.

Lightweight CLI smoke checks are:

```powershell
personal-librarian version
personal-librarian doctor
personal-librarian safety check-path 'C:\example'
```

## Development workflow note

Use deterministic shell, PowerShell or Python commands for simple mechanical work. A local Ollama model may support suitable low-risk work. Codex remains appropriate for repository-wide implementation, complex debugging and architectural changes. M13 adds no Ollama or AI integration to the application.

## Explicit non-goals

M13 does not:

- scan or access the Personal Library;
- import M9, M10 or M11 evidence;
- create SQLite or another catalogue;
- rank or nominate canonical copies;
- implement deduplication, file moves, renames, quarantine or deletion;
- run rclone or contact cloud services;
- provide a UI; or
- mark M13 complete.

## Known limitations

- Path assessment is deliberately lexical because M13 performs no filesystem operations. Future file-changing code must re-check real filesystem targets, links and junctions without weakening the retired-drive rule.
- Configuration supports only project and data roots; source registries arrive in a later milestone.
- Run state and logs are in memory/console only.
- The CLI has diagnostics but no media or catalogue commands.
