"""Catalogue-specific error types."""


class CatalogueError(RuntimeError):
    """Base class for safe, user-facing catalogue failures."""


class CataloguePathError(CatalogueError):
    """Raised before an unsafe or ambiguous database path is accessed."""


class CatalogueNotInitialisedError(CatalogueError):
    """Raised when a database is not a recognised Personal Librarian catalogue."""


class SchemaVersionError(CatalogueError):
    """Raised when migration history is unsupported or inconsistent."""


class MigrationError(CatalogueError):
    """Raised when a schema migration fails."""


class EvidenceImportError(CatalogueError):
    """Base class for evidence-import failures."""


class EvidenceValidationError(EvidenceImportError):
    """Raised when evidence input is malformed or internally inconsistent."""


class InputFingerprintMismatchError(EvidenceImportError):
    """Raised when a completed stage is rerun with different input evidence."""


class ReconciliationError(EvidenceImportError):
    """Raised when imported metrics differ from required baselines."""

    def __init__(self, message: str, report: object) -> None:
        super().__init__(message)
        self.report = report


class PipelineError(CatalogueError):
    """Raised for safe, user-facing M15 pipeline failures."""


class DecisionError(CatalogueError):
    """Raised when an M17 review or decision invariant would be violated."""


class PlanningError(CatalogueError):
    """Raised when an M18 plan or preflight would violate a safety invariant."""


class QuarantineError(CatalogueError):
    """Raised when an M19 quarantine or restore safety invariant fails."""


class ProductionError(CatalogueError):
    """Raised when an M20 production, backup, or recovery invariant fails."""


class OrganisationError(CatalogueError):
    """Raised when an M28 logical-organisation invariant would be violated."""


class DateEvidenceError(CatalogueError):
    """Raised when an M30 preferred-date invariant would be violated."""


class CollectionError(CatalogueError):
    """Raised when an M30 Collection invariant would be violated."""
