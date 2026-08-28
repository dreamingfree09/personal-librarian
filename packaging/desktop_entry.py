"""PyInstaller entry point; starts the Qt desktop directly."""

from personal_librarian.desktop.app import packaged_main


if __name__ == "__main__":
    raise SystemExit(packaged_main())
