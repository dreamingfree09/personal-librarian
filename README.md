# Personal Librarian

A local-first, privacy-focused desktop application for cataloguing, analysing, organising, and protecting personal photo and video libraries without surrendering control of the underlying files.

[![CI](https://github.com/dreamingfree09/personal-librarian/actions/workflows/ci.yml/badge.svg)](https://github.com/dreamingfree09/personal-librarian/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Platform: Windows](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)
![UI: PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)
![Database: SQLite](https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white)
![Status: pre-1.0 RC7](https://img.shields.io/badge/Status-pre--1.0%20RC7-orange)

Personal Librarian builds an explicit catalogue over media that remains outside the repository. It separates analysis, review, owner decisions, and safe action planning so that discovering a duplicate or proposing an organisation change never silently changes a file.

## Why Personal Librarian?

Personal media rarely lives in one clean location. A library may be fragmented across local disks, cloud-sync folders, phone transfers, exports, duplicate copies, and backup drives. File browsers show where files are; they do not reliably explain which copies are identical, what evidence supports a date, or which organisation choices an owner has approved.

Personal Librarian responds with a few strict design choices:

- **Local-first:** core catalogue and desktop workflows run locally.
- **Catalogue-first:** physical files are represented as evidence-bearing catalogue records before organisation decisions are made.
- **Non-destructive:** analysis is not authority to move, rename, overwrite, or delete media.
- **Evidence-driven:** exact hashes, similarity evidence, dates, provenance, and decisions remain inspectable.
- **Owner-controlled:** nomination and approval are explicit, separate steps.
- **Auditable:** decisions and logical organisation history are append-only where the data model requires it.
- **Externally rooted:** media, catalogue databases, thumbnails, inventories, and backups live outside the source tree.

## Implemented features

The current public source includes:

- a schema-10 SQLite catalogue of physical instances and content identities;
- reproducible inventory, SHA-256 exact-duplicate, and perceptual-similarity analysis pipelines;
- bounded exact-duplicate and similar-content review;
- explicit owner nomination, approval, rejection, supersession, and abstention records;
- preferred-date evidence, Year shelves, and explicit Unknown Date handling;
- manual Albums and cross-year Collections;
- immutable, auditable logical-organisation History;
- action-plan preflight and read-only plan visibility in the desktop;
- constrained exact-duplicate quarantine and restoration foundations;
- catalogue backup, verification, recovery staging, and independent local disaster-recovery checks;
- a PySide6 desktop interface and a comprehensive command-line interface; and
- Windows one-folder and release packaging tooling.

Physical media organisation is not presented as an automatic feature. The current workflow is deliberately catalogue-led and non-destructive.

### Planned or future work

Future work is separate from the implemented feature set and requires its own design and safety review. Candidate areas include richer EXIF capture-date evidence, video metadata, trusted sidecar or source metadata, improved semantic search or locally assisted AI, and carefully controlled physical-organisation workflows.

## Safety model

The preservation-first operating principle is:

> Discover → Copy → Verify → Analyse → Recommend → Approve → Plan → Preflight → Act → Verify

Analysis never grants permission to mutate media. Review, owner decisions, planning, preflight, and execution are distinct stages. Media paths are not silently reorganised, production data is kept outside the repository, and destructive functionality is deliberately constrained. Existing quarantine and recovery operations require explicit context and confirmation; there is no generic delete or overwrite path.

## Architecture

```text
Sources / media
       ↓
Physical instances
       ↓
Content identities
       ↓
Evidence and analysis
       ↓
Preferred state / review
       ↓
Owner decisions
       ↓
Plans / safe actions
```

- **Source media** is the owner's external file content and remains the preservation authority.
- **The catalogue** records physical instances, logical identities, evidence, state, and provenance.
- **Logical organisation** uses dates, Albums, and Collections without changing source paths.
- **Physical organisation** concerns file placement and is intentionally a separate, more constrained workflow.

See [PROJECT_TRUTH.md](PROJECT_TRUTH.md) for the canonical architecture and safety boundaries.

## Current status

| Item | Status |
| --- | --- |
| Source/package version | `0.1.0rc7` |
| Catalogue schema | 10 |
| Current milestone | M30 complete |
| Initial catalogue-only preferred-date population | Complete |
| Maturity | Pre-1.0 release candidate |

RC7 source and packaging tools are present, but this repository does not currently offer an approved binary download or GitHub Release. Pre-1.0 interfaces and support policy may evolve.

## Screenshots

Screenshots will be added once a sanitized demonstration catalogue is available. No private production screenshots are used. See the [screenshot policy](docs/screenshots/README.md).

## Quick start

Personal Librarian currently targets Windows and requires Python 3.13.

```powershell
git clone https://github.com/dreamingfree09/personal-librarian.git
cd personal-librarian

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Confirm the installed CLI, launch against an existing Personal Librarian application-data root, and run the synthetic test suite:

```powershell
personal-librarian version
personal-librarian desktop --app-data-root '<data-root>'
python -m unittest discover -s tests -v
```

Do not substitute an arbitrary media folder for `<data-root>`; desktop startup expects an existing validated catalogue layout, as explained below.

## Desktop usage

The source-installed desktop command requires an existing application-data root:

```powershell
personal-librarian desktop `
  --app-data-root '<data-root>' `
  --independent-backup-root '<backup-root>'
```

The independent-backup root is optional. The application-data root is not: it must already contain a valid Personal Librarian catalogue. The program does not create, bootstrap, or silently choose a production catalogue during desktop startup. Read the [canonical project definition](PROJECT_TRUTH.md) before pointing operational commands at important data.

The packaged desktop launcher can present a folder picker, but it applies the same rule: only an existing validated application-data root is accepted.

Explore the CLI without touching a catalogue:

```powershell
personal-librarian --help
personal-librarian desktop --help
personal-librarian doctor
```

## Build and package

Install the build-only dependency set:

```powershell
python -m pip install -e '.[build]'
```

Build the Windows one-folder application:

```powershell
.\packaging\build_windows.ps1
```

Build the local release package, including the portable ZIP, checksums, and manifest:

```powershell
.\packaging\build_release.ps1
```

The release wrapper is RC7-specific and records the frozen RC7 build provenance in its generated manifest. Generated output under `build/`, `dist/`, and `release/` is ignored and must not be committed. Packaging is a local operation; no binary is published by these instructions.

## Repository structure

```text
src/        application source
tests/      deterministic synthetic-data tests
docs/       architecture and milestone engineering records
scripts/    guarded operational and project scripts
packaging/  Windows build and release tooling
config/     deterministic configuration area
```

## Data and privacy

This repository contains source code, tests, configuration scaffolding, and documentation only. The following remain external and must never be committed:

- personal photos, videos, documents, or other media;
- catalogue databases, SQLite journals, and recovery candidates;
- thumbnails, inventories, logs, caches, and staging data;
- operational and disaster-recovery backups;
- credentials, private filesystem details, and local editor state;
- AI models; and
- generated executables, archives, and release output.

Core catalogue and desktop workflows are local-first. Some historical acquisition records discuss cloud-sync sources, but the current release does not silently upload personal media or add a hosted service.

## Development

Use Python 3.13 and install the project in editable mode as shown in [Quick start](#quick-start). Changes should remain focused, preserve the non-destructive boundaries, and include deterministic tests where behaviour changes.

Before submitting a change:

```powershell
python -m unittest discover -s tests -v
git -c core.whitespace=cr-at-eol diff --check
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) for contributor guidance and [SECURITY.md](SECURITY.md) for private vulnerability reporting.

## Documentation

- [Architecture and canonical project definition](PROJECT_TRUTH.md)
- [Engineering-history index](docs/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## License

Personal Librarian is available under the [MIT License](LICENSE). Copyright © 2026 Konstantinos Aidinidis.
