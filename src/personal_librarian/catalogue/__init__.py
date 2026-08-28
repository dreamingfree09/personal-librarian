"""Persistent SQLite catalogue foundation."""

from personal_librarian.catalogue.database import (
    connect_existing_catalogue,
    get_catalogue_status,
    initialise_catalogue,
)
from personal_librarian.catalogue.migrations import CURRENT_SCHEMA_VERSION

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "connect_existing_catalogue",
    "get_catalogue_status",
    "initialise_catalogue",
]
