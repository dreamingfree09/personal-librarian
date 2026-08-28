"""In-memory run context for application commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from personal_librarian.safety import OperationMode


@dataclass(frozen=True, slots=True)
class RunContext:
    """Identity and mode for one CLI execution; M13 has no job database."""

    run_id: str
    started_at: datetime
    mode: OperationMode

    @classmethod
    def create(cls, mode: OperationMode = OperationMode.READ_ONLY) -> "RunContext":
        return cls(run_id=str(uuid4()), started_at=datetime.now(timezone.utc), mode=mode)
