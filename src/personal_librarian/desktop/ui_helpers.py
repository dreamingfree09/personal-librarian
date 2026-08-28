"""Pure formatting and review-navigation helpers for the desktop UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


SIMILARITY_HELP_TEXT = (
    "Lower pHash and dHash distances mean the images are more visually similar. "
    "These perceptual comparisons do not prove byte-for-byte identity; the current "
    "review set requires both distances to be within its threshold."
)

_STATE_LABELS = {
    "pending": "Pending",
    "nominated": "Nominated",
    "approved": "Approved",
    "rejected": "Rejected",
    "abstained": "Abstained",
    "decided": "Decided",
    "review_only": "Review only",
    "large_low_confidence_review_only": "Large · review only",
    "very_large_low_confidence_review_only": "Very large · review only",
    "operational-local": "Operational",
    "independent-local": "Independent",
    "display_export": "Display / export",
}


def format_bytes(value: object) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("bytes", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{int(size):,} bytes" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def display_timestamp(value: object) -> str:
    if value is None or not str(value).strip():
        return "—"
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return raw


def owner_state_label(value: object, *, empty: str = "Not chosen") -> str:
    if value is None or not str(value).strip():
        return empty
    raw = str(value).strip().casefold()
    return _STATE_LABELS.get(raw, raw.replace("_", " ").capitalize())


def canonical_scope_label(canonical: dict[str, dict[str, bool]], scope: str) -> str:
    state = canonical.get(scope, {})
    if state.get("approved"):
        return "Approved"
    if state.get("nominated"):
        return "Nominated"
    return "Not chosen"


def canonical_badge(canonical: dict[str, dict[str, bool]]) -> str:
    return (
        f"Archival: {canonical_scope_label(canonical, 'archival')} · "
        f"Display: {canonical_scope_label(canonical, 'display_export')}"
    )


def item_filename(item: dict[str, Any]) -> str:
    current = str(item.get("current_observed_path") or item.get("raw_relative_path") or "")
    return Path(current.replace("\\", "/")).name if current else "Unavailable"


def preview_caption(item: dict[str, Any]) -> str:
    return (
        f"{item_filename(item)}\n{item.get('source') or 'Unknown source'} · "
        f"{format_bytes(item.get('size_bytes'))} · "
        f"{display_timestamp(item.get('observed_modified_at'))}"
    )


def metadata_blocks(item: dict[str, Any]) -> tuple[str, str]:
    primary = (
        f"{item_filename(item)}\n"
        f"Source: {item.get('source') or '—'}\n"
        f"Size: {format_bytes(item.get('size_bytes'))}\n"
        f"Modified: {display_timestamp(item.get('observed_modified_at'))}\n"
        f"Represented copies: {item.get('exact_duplicate_count', 1)}\n"
        f"Archival: {canonical_scope_label(item.get('canonical', {}), 'archival')}\n"
        f"Display: {canonical_scope_label(item.get('canonical', {}), 'display_export')}"
    )
    technical = (
        f"SHA-256: {item.get('sha256') or '—'}\n"
        f"Instance ID: {item.get('physical_instance_id') or '—'}\n"
        f"Content ID: {item.get('content_identity_id') or '—'}\n"
        f"Full path: {item.get('current_observed_path') or item.get('raw_relative_path') or '—'}"
    )
    return primary, technical


def metadata_summary(item: dict[str, Any]) -> str:
    primary, technical = metadata_blocks(item)
    return f"{primary}\n\nTechnical details\n{technical}"


def decision_confirmation_text(
    *,
    action: str,
    scope: str,
    actor: str,
    reason: str | None,
    context_id: int,
    selected: dict[str, Any] | None,
) -> tuple[str, str, str]:
    scope_label = "archival" if scope == "archival" else "display/export"
    questions = {
        "nominate": f"Nominate this copy as the preferred {scope_label} candidate?",
        "approve": f"Approve this nominated copy for {scope_label} use?",
        "reject": f"Reject this {scope_label} nomination?",
        "supersede": f"Replace the current {scope_label} approval with this nomination?",
        "abstain": f"Record no {scope_label} choice for this exact group?",
    }
    primary = questions[action]
    if selected is None:
        informative = f"Owner: {actor}\nScope: {scope_label.title()}"
        technical = f"Exact context: {context_id}\nTarget: whole review group"
    else:
        informative = (
            f"{item_filename(selected)}\n"
            f"Source: {selected.get('source') or '—'}\n"
            f"Scope: {scope_label.title()}\nOwner: {actor}"
        )
        technical = (
            f"Exact context: {context_id}\n"
            f"Instance ID: {selected.get('physical_instance_id') or '—'}\n"
            f"Path: {selected.get('current_observed_path') or selected.get('raw_relative_path') or '—'}"
        )
    if reason:
        informative += f"\nReason: {reason}"
    informative += "\n\nNomination and approval are separate catalogue events."
    return primary, informative, technical


def bounded_row(current: int, count: int, delta: int) -> int:
    if count <= 0:
        return -1
    if current < 0:
        return 0
    return max(0, min(count - 1, current + delta))
