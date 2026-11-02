# Contributing to Personal Librarian

Thank you for helping improve Personal Librarian. The project values preservation, explicit evidence, owner control, and small changes that are easy to review.

## Before starting

Open or join an issue before undertaking a large feature, architectural change, schema change, or new file-mutating workflow. This helps confirm scope and safety expectations before substantial work begins. Small documentation fixes and narrowly scoped bug fixes do not need heavy process.

Architecture-affecting proposals should align with [PROJECT_TRUTH.md](PROJECT_TRUTH.md), the canonical project definition.

## Local setup

Personal Librarian currently targets Windows and Python 3.13.

```powershell
git clone https://github.com/dreamingfree09/personal-librarian.git
cd personal-librarian
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Run the test suite:

```powershell
python -m unittest discover -s tests -v
git -c core.whitespace=cr-at-eol diff --check
```

The tests use temporary directories and synthetic fixtures. New tests must do the same: never depend on a production catalogue, private media, real backup roots, or a contributor's machine layout.

For the controlled Windows CI environment, install `requirements-ci.txt`
before installing the project with `--no-deps --no-build-isolation`.
PySide6 is currently qualified at 6.11.2 because 6.12.0 reproduces native
shutdown crashes after successful test assertions. See
[the process-finalisation diagnostic](docs/CI_FINALISATION_DIAGNOSTIC.md)
for evidence, limitations and the command that records actual process exits.

## Pull requests

- Keep each pull request focused and explain the problem it solves.
- Add or update tests when behaviour changes.
- Preserve the separation between analysis, approval, planning, and action.
- Treat non-destructive behaviour and explicit owner authority as compatibility requirements.
- Update public documentation when commands, architecture, or user-visible behaviour changes.
- Keep generated binaries, databases, media, inventories, backups, logs, and caches out of Git.
- Remove usernames, private paths, device identifiers, credentials, and real personal-library data from examples, tests, logs, and screenshots.

Before submitting, verify that the full deterministic test suite and whitespace check pass. If a check cannot run, explain why in the pull request.

## Security and privacy reports

Do not use a public issue for a suspected security or privacy vulnerability. Follow [SECURITY.md](SECURITY.md), and provide only a minimal synthetic reproduction.
