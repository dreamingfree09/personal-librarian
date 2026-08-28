"""Desktop application bootstrap."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from personal_librarian import __version__
from personal_librarian.desktop.main_window import MainWindow
from personal_librarian.desktop.services import DesktopDataService
from personal_librarian.desktop.startup import StartupDialog, validate_runtime_roots


def run_desktop(
    *, app_data_root: str | Path, independent_backup_root: str | Path | None = None
) -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Personal Librarian")
    application.setOrganizationName("Personal Librarian")
    service = DesktopDataService(app_data_root, independent_backup_root)
    window = MainWindow(service)
    window.show()
    return application.exec()


def packaged_main(argv: list[str] | None = None) -> int:
    """Direct GUI entry point used by the standalone Windows distribution."""

    parser = argparse.ArgumentParser(prog="PersonalLibrarian")
    parser.add_argument("--app-data-root")
    parser.add_argument("--independent-backup-root")
    parser.add_argument(
        "--smoke-report",
        help="Explicit QA-only JSON output path; runs bounded frozen-runtime validation and exits.",
    )
    args = parser.parse_args(argv)
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Personal Librarian")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("Personal Librarian")
    if args.app_data_root:
        try:
            app_root, independent_root = validate_runtime_roots(
                args.app_data_root, args.independent_backup_root
            )
        except ValueError as exc:
            QMessageBox.critical(None, "Cannot open catalogue", str(exc))
            return 2
    else:
        dialog = StartupDialog()
        if dialog.exec() != StartupDialog.Accepted:
            return 0
        app_root, independent_root = validate_runtime_roots(
            dialog.app_root.text(), dialog.independent_root.text()
        )
    service = DesktopDataService(app_root, independent_root)
    if args.smoke_report:
        from personal_librarian.desktop.smoke import write_packaged_smoke_report

        write_packaged_smoke_report(service, args.smoke_report)
        return 0
    window = MainWindow(service)
    window.show()
    return application.exec()
