"""Module launch path for ``python -m personal_librarian.desktop``."""

from __future__ import annotations

from personal_librarian.desktop.app import packaged_main


def main() -> int:
    return packaged_main()


if __name__ == "__main__":
    raise SystemExit(main())
