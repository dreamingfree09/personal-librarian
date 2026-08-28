# Changelog

Notable public-facing changes to Personal Librarian are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) where practical, and the project uses pre-1.0 release-candidate versions.

## [Unreleased]

### Added

- Public contribution guidance, issue forms, pull-request guidance, and Windows CI.
- A navigable engineering-documentation index and sanitized screenshot policy.

### Changed

- Reworked the public landing page to present current capabilities, safety boundaries, architecture, setup, and privacy expectations clearly.

## [0.1.0rc7] - 2026-08-27

### Added

- PySide6 desktop interface and command-line workflows over a schema-10 SQLite catalogue.
- Physical-instance and content-identity cataloguing with exact-duplicate and similar-content review.
- Preferred-date evidence, Year shelves, explicit Unknown Date handling, Albums, and cross-year Collections.
- Auditable owner decisions and immutable logical-organisation History.
- Catalogue backup, verification, recovery staging, and independent local disaster-recovery checks.

### Changed

- Improved preferred-date counting and desktop performance for the RC7 source/package baseline.
- Kept plans, quarantine, backup, and recovery visibility bounded by the existing safety model.

### Fixed

- Corrected the desktop History timestamp contract while preserving stored event timestamps and ordering.

### Safety

- Maintained the separation between analysis, review, owner approval, planning, preflight, and action.
- Kept production catalogues, media, backups, and generated release artifacts outside the source repository.
