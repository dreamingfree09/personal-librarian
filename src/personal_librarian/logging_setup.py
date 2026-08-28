"""Simple structured, human-readable application logging."""

from __future__ import annotations

import logging
from datetime import datetime, timezone


class Iso8601Formatter(logging.Formatter):
    """Render log timestamps as UTC ISO-8601 values."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        moment = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RunIdFilter(logging.Filter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = self._run_id
        return True


def configure_logging(run_id: str, *, verbose: bool = False) -> logging.Logger:
    """Configure the application logger without creating log files."""

    logger = logging.getLogger("personal_librarian")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setLevel(logger.level)
    handler.addFilter(RunIdFilter(run_id))
    handler.setFormatter(
        Iso8601Formatter(
            "%(asctime)s level=%(levelname)s run_id=%(run_id)s component=%(name)s message=%(message)s"
        )
    )
    logger.addHandler(handler)
    return logger
