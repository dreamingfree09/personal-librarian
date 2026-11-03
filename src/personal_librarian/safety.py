"""Central, non-I/O safety policy for operation modes and filesystem paths."""

from __future__ import annotations

import ntpath
import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PathIntent(StrEnum):
    """The intended relationship with a filesystem path."""

    READ = "read"
    WRITE = "write"


class OperationMode(StrEnum):
    """Execution modes recognised by the application safety contract."""

    READ_ONLY = "read-only"
    DRY_RUN = "dry-run"
    ACTION = "action"


def physical_command_mode_error(explicit_mode: str | None) -> str | None:
    """M19 confirmation is a narrow contract, never an override of M13 modes."""
    if explicit_mode is not None:
        return (
            f"Explicit {explicit_mode} mode prohibits physical quarantine/restore. "
            "Omit --mode only when intentionally using the separately confirmed "
            "quarantine/restore contract. General action mode remains unavailable."
        )
    return None


@dataclass(frozen=True, slots=True)
class SafetyResult:
    """An explainable path-safety decision."""

    allowed: bool
    code: str
    reason: str
    raw_path: str
    assessed_path: str | None
    intent: PathIntent


@dataclass(frozen=True, slots=True)
class OperationDecision:
    """An explainable operation-mode decision."""

    allowed: bool
    code: str
    reason: str
    mode: OperationMode
    intent: PathIntent


@dataclass(frozen=True, slots=True)
class WriteBoundaryResult:
    """Explain a lexical and resolved M18 future-write boundary decision."""

    allowed: bool
    code: str
    reason: str
    destination_root: str
    destination_path: str
    resolved_root: str | None
    resolved_existing_ancestor: str | None


def assess_operation(mode: OperationMode, intent: PathIntent) -> OperationDecision:
    """Enforce the M13 rule that no mode authorises filesystem writes."""

    if mode is OperationMode.ACTION:
        return OperationDecision(
            allowed=False,
            code="ACTION_MODE_UNAVAILABLE",
            reason="Action mode is reserved for future milestones and is unavailable in M13.",
            mode=mode,
            intent=intent,
        )
    if intent is PathIntent.WRITE:
        return OperationDecision(
            allowed=False,
            code="WRITE_BLOCKED_BY_MODE",
            reason=f"The {mode.value} mode cannot authorise filesystem writes.",
            mode=mode,
            intent=intent,
        )
    return OperationDecision(
        allowed=True,
        code="READ_ALLOWED",
        reason=f"The {mode.value} mode permits read intent.",
        mode=mode,
        intent=intent,
    )


def windows_path_kind(path: str) -> str:
    """Classify syntax only; never resolve or probe a Windows namespace.

    Ordinary UNC shares remain supported. Win32/NT device aliases are not
    ordinary shares, including when their separators use forward slashes.
    """
    value = path.replace("/", "\\")
    if (value.startswith(("\\\\?\\", "\\\\.\\", "\\??\\", "\\\\??\\"))
            or value in {"\\\\?", "\\\\.", "\\??", "\\\\??"}
            or re.match(r"^\\(?:Device|GLOBALROOT|GLOBAL\?\?|DosDevices)(?:\\|$)", value, re.I)):
        return "device"
    if not value or any(ord(c) < 32 for c in value):
        return "invalid"
    if value.startswith("\\\\"):
        parts = value[2:].split("\\")
        if (len(parts) < 2 or any(p in {"", ".", ".."} for p in parts[:2])
                or any(re.search(r'[<>:"|?*]', p) or p.endswith((" ", ".")) for p in parts[:2])):
            return "malformed-unc"
        tail = "\\".join(parts[2:])
        kind = "unc"
    elif re.match(r"^[A-Za-z]:", value):
        tail = value[2:]
        kind = "drive-absolute" if tail.startswith("\\") else "drive-relative"
    else:
        tail = value
        kind = "root-relative" if value.startswith("\\") else "relative"
    for part in tail.split("\\"):
        if part in {"", ".", ".."}:
            continue
        if (re.search(r'[<>:"|?*]', part) or part.endswith((" ", "."))
                or part.split(".", 1)[0].upper() in _RESERVED_WINDOWS_NAMES):
            return "invalid"
    return kind


class PathSafetyPolicy:
    """Assess Windows paths without opening, resolving, or enumerating them."""

    _DRIVE_PATTERN = re.compile(r"^[A-Za-z]:$")
    _EXPLICIT_DRIVE_PATTERN = re.compile(r"^([A-Za-z]):")
    _DEVICE_DRIVE_PATTERN = re.compile(r"^\\\\[?.]\\([A-Za-z]):", re.IGNORECASE)

    def __init__(self, retired_drives: frozenset[str] | None = None) -> None:
        drives = retired_drives or frozenset({"Z:"})
        normalised = frozenset(drive.upper() for drive in drives)
        if not normalised or any(not self._DRIVE_PATTERN.fullmatch(drive) for drive in normalised):
            raise ValueError("Retired drives must be Windows drive letters such as 'Z:'.")
        self._retired_drives = normalised

    @property
    def retired_drives(self) -> frozenset[str]:
        return self._retired_drives

    def check_path(
        self,
        path: str | os.PathLike[str],
        *,
        intent: PathIntent,
        base_path: str | os.PathLike[str] | None = None,
    ) -> SafetyResult:
        """Assess a path lexically; this method performs no filesystem access."""

        try:
            raw_path = os.fspath(path)
        except TypeError:
            return self._blocked("INVALID_PATH_TYPE", "Path must be text or path-like.", repr(path), None, intent)

        if not isinstance(raw_path, str):
            return self._blocked("INVALID_PATH_TYPE", "Byte paths are not supported.", repr(raw_path), None, intent)
        if not raw_path or raw_path.isspace():
            return self._blocked("EMPTY_PATH", "Path must not be empty.", raw_path, None, intent)
        if "\x00" in raw_path:
            return self._blocked("NUL_BYTE", "Path contains a NUL byte.", raw_path, None, intent)

        candidate = raw_path.replace("/", "\\")
        kind = windows_path_kind(candidate)
        device_match = self._DEVICE_DRIVE_PATTERN.match(candidate)
        if device_match:
            drive = f"{device_match.group(1).upper()}:"
            if drive in self._retired_drives:
                return self._retired(raw_path, candidate, intent)
            return self._blocked(
                "UNSUPPORTED_DEVICE_PATH",
                "Windows device paths are not supported by the M13 safety policy.",
                raw_path,
                candidate,
                intent,
            )

        if kind == "device":
            return self._blocked("UNSUPPORTED_DEVICE_PATH", "Windows device namespaces are unsupported.", raw_path, candidate, intent)
        if kind in {"invalid", "malformed-unc"}:
            code = "MALFORMED_UNC_PATH" if kind == "malformed-unc" else "INVALID_WINDOWS_PATH"
            return self._blocked(code, "Path is not supported Windows filesystem syntax.", raw_path, candidate, intent)

        explicit_match = self._EXPLICIT_DRIVE_PATTERN.match(candidate)
        if explicit_match:
            drive = f"{explicit_match.group(1).upper()}:"
            if drive in self._retired_drives:
                return self._retired(raw_path, candidate, intent)
            tail = candidate[2:]
            if not tail.startswith("\\"):
                return self._blocked(
                    "AMBIGUOUS_DRIVE_RELATIVE_PATH",
                    "Drive-relative paths such as 'C:folder' are ambiguous and rejected.",
                    raw_path,
                    candidate,
                    intent,
                )
            assessed = ntpath.normpath(candidate)
            return self._allowed(raw_path, assessed, intent)

        if candidate.startswith("\\\\"):
            if not self._valid_unc(candidate):
                return self._blocked(
                    "MALFORMED_UNC_PATH",
                    "UNC paths must contain both a server and a share name.",
                    raw_path,
                    candidate,
                    intent,
                )
            return self._allowed(raw_path, ntpath.normpath(candidate), intent)

        base = os.fspath(base_path) if base_path is not None else str(Path.cwd())
        if not isinstance(base, str) or not base:
            return self._blocked("INVALID_BASE_PATH", "Relative paths require a valid base path.", raw_path, None, intent)

        base_candidate = base.replace("/", "\\")
        base_result = self._check_absolute_base(base_candidate, intent)
        if not base_result.allowed:
            return SafetyResult(
                allowed=False,
                code=base_result.code,
                reason=f"Relative path base is unsafe: {base_result.reason}",
                raw_path=raw_path,
                assessed_path=base_result.assessed_path,
                intent=intent,
            )

        assert base_result.assessed_path is not None
        if candidate.startswith("\\"):
            base_drive, _ = ntpath.splitdrive(base_result.assessed_path)
            assessed = ntpath.normpath(f"{base_drive}{candidate}")
        else:
            assessed = ntpath.normpath(ntpath.join(base_result.assessed_path, candidate))

        assessed_drive, _ = ntpath.splitdrive(assessed)
        if assessed_drive.upper() in self._retired_drives:
            return self._retired(raw_path, assessed, intent)
        return self._allowed(raw_path, assessed, intent)

    def _check_absolute_base(self, base: str, intent: PathIntent) -> SafetyResult:
        device_match = self._DEVICE_DRIVE_PATTERN.match(base)
        if device_match:
            drive = f"{device_match.group(1).upper()}:"
            if drive in self._retired_drives:
                return self._retired(base, base, intent)
            return self._blocked(
                "UNSUPPORTED_DEVICE_PATH",
                "Windows device paths cannot be used as relative-path bases.",
                base,
                base,
                intent,
            )

        kind = windows_path_kind(base)
        if kind == "device":
            return self._blocked("UNSUPPORTED_DEVICE_PATH", "Device namespaces cannot be relative-path bases.", base, base, intent)
        if kind not in {"drive-absolute", "unc"}:
            return self._blocked("INVALID_BASE_PATH", "Relative-path base must be a supported absolute path.", base, base, intent)
        explicit_match = self._EXPLICIT_DRIVE_PATTERN.match(base)
        if explicit_match:
            drive = f"{explicit_match.group(1).upper()}:"
            if drive in self._retired_drives:
                return self._retired(base, base, intent)
            if base[2:].startswith("\\"):
                return self._allowed(base, ntpath.normpath(base), intent)
            return self._blocked(
                "INVALID_BASE_PATH",
                "Relative-path base must be absolute.",
                base,
                base,
                intent,
            )

        if base.startswith("\\\\") and self._valid_unc(base):
            return self._allowed(base, ntpath.normpath(base), intent)
        return self._blocked(
            "INVALID_BASE_PATH",
            "Relative-path base must be an absolute drive or UNC path.",
            base,
            base,
            intent,
        )

    @staticmethod
    def _valid_unc(path: str) -> bool:
        parts = path[2:].split("\\")
        return len(parts) >= 2 and bool(parts[0]) and bool(parts[1])

    def _retired(self, raw_path: str, assessed_path: str, intent: PathIntent) -> SafetyResult:
        return self._blocked(
            "RETIRED_DRIVE",
            "The retired Z: device is blocked for every path intent.",
            raw_path,
            assessed_path,
            intent,
        )

    @staticmethod
    def _allowed(raw_path: str, assessed_path: str, intent: PathIntent) -> SafetyResult:
        return SafetyResult(
            allowed=True,
            code="PATH_ALLOWED",
            reason=f"Path passed the M13 lexical safety policy for {intent.value} intent.",
            raw_path=raw_path,
            assessed_path=assessed_path,
            intent=intent,
        )

    @staticmethod
    def _blocked(
        code: str,
        reason: str,
        raw_path: str,
        assessed_path: str | None,
        intent: PathIntent,
    ) -> SafetyResult:
        return SafetyResult(False, code, reason, raw_path, assessed_path, intent)


_INVALID_WINDOWS_COMPONENT = re.compile(r'[<>:"/\\|?*]')
_RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


def assess_write_destination(
    destination_root: str | os.PathLike[str],
    destination_path: str | os.PathLike[str],
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> WriteBoundaryResult:
    """Fail-closed lexical and existing-ancestor preflight for a future write."""

    policy = safety_policy or PathSafetyPolicy()
    root_raw = os.fspath(destination_root)
    destination_raw = os.fspath(destination_path)
    root_result = policy.check_path(root_raw, intent=PathIntent.WRITE)
    destination_result = policy.check_path(destination_raw, intent=PathIntent.WRITE)
    if not root_result.allowed:
        return _write_blocked(root_result.code, root_result.reason, root_raw, destination_raw)
    if not destination_result.allowed:
        return _write_blocked(
            destination_result.code, destination_result.reason, root_raw, destination_raw
        )
    assert root_result.assessed_path is not None
    assert destination_result.assessed_path is not None
    root_normal = ntpath.normpath(root_result.assessed_path)
    destination_normal = ntpath.normpath(destination_result.assessed_path)
    if not _windows_absolute(root_normal) or not _windows_absolute(destination_normal):
        return _write_blocked(
            "ABSOLUTE_PATH_REQUIRED", "Destination root and path must be absolute.",
            root_raw, destination_raw,
        )
    raw_root_tail = ntpath.splitdrive(root_raw.replace("/", "\\"))[1]
    raw_tail = ntpath.splitdrive(destination_raw.replace("/", "\\"))[1]
    if ".." in raw_root_tail.split("\\") or ".." in raw_tail.split("\\"):
        return _write_blocked(
            "LEXICAL_TRAVERSAL", "Destination contains an explicit parent traversal component.",
            root_raw, destination_raw,
        )
    try:
        common = ntpath.commonpath(
            [ntpath.normcase(root_normal), ntpath.normcase(destination_normal)]
        )
    except ValueError:
        common = ""
    if common != ntpath.normcase(root_normal):
        return _write_blocked(
            "OUTSIDE_DESTINATION_ROOT", "Destination is outside the approved destination root.",
            root_raw, destination_raw,
        )
    relative = ntpath.relpath(destination_normal, root_normal)
    for component in relative.split("\\"):
        if component in {"", "."}:
            continue
        stem = component.split(".", 1)[0].upper()
        if (
            _INVALID_WINDOWS_COMPONENT.search(component)
            or component.endswith((" ", "."))
            or stem in _RESERVED_WINDOWS_NAMES
        ):
            return _write_blocked(
                "INVALID_WINDOWS_COMPONENT",
                f"Destination component is not safe on Windows: {component!r}.",
                root_raw,
                destination_raw,
            )

    root_path = Path(root_normal)
    if not root_path.exists() or not root_path.is_dir():
        return _write_blocked(
            "DESTINATION_ROOT_UNAVAILABLE",
            "Approved destination root must already exist as a directory for preflight.",
            root_raw,
            destination_raw,
        )
    try:
        if _is_reparse(root_path):
            return _write_blocked(
                "DESTINATION_ROOT_REPARSE_UNCERTAIN",
                "Approved destination root is itself a symlink/junction/reparse point.",
                root_raw,
                destination_raw,
            )
        resolved_root = root_path.resolve(strict=True)
        resolved_result = policy.check_path(str(resolved_root), intent=PathIntent.WRITE)
        if not resolved_result.allowed:
            return _write_blocked(
                resolved_result.code, "Resolved destination root is unsafe.",
                root_raw, destination_raw, str(resolved_root), None,
            )
        current = root_path
        resolved_ancestor = resolved_root
        parent_relative = ntpath.dirname(relative)
        for component in parent_relative.split("\\"):
            if component in {"", "."}:
                continue
            current = current / component
            if not current.exists():
                break
            resolved_ancestor = current.resolve(strict=True)
            if not _resolved_within(resolved_ancestor, resolved_root):
                return _write_blocked(
                    "REPARSE_ESCAPE",
                    "Existing destination ancestor resolves outside the approved root.",
                    root_raw, destination_raw, str(resolved_root), str(resolved_ancestor),
                )
            resolved_check = policy.check_path(str(resolved_ancestor), intent=PathIntent.WRITE)
            if not resolved_check.allowed:
                return _write_blocked(
                    resolved_check.code, "Resolved destination ancestor is unsafe.",
                    root_raw, destination_raw, str(resolved_root), str(resolved_ancestor),
                )
        return WriteBoundaryResult(
            True,
            "DESTINATION_SAFE",
            "Lexical and existing resolved destination boundaries passed.",
            root_raw,
            destination_raw,
            str(resolved_root),
            str(resolved_ancestor),
        )
    except OSError as exc:
        return _write_blocked(
            "RESOLUTION_UNCERTAIN", f"Resolved destination safety is uncertain: {exc}",
            root_raw, destination_raw,
        )


def windows_collision_key(path: str) -> str:
    """Non-authoritative Windows case/Unicode collision key for planned paths."""

    return unicodedata.normalize("NFC", ntpath.normpath(path)).casefold()


def _windows_absolute(path: str) -> bool:
    drive, tail = ntpath.splitdrive(path)
    return (len(drive) == 2 and drive[1] == ":" and tail.startswith("\\")) or (
        path.startswith("\\\\") and bool(drive)
    )


def _is_reparse(path: Path) -> bool:
    information = path.lstat()
    attributes = getattr(information, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _resolved_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return path == root


def _write_blocked(
    code: str,
    reason: str,
    root: str,
    destination: str,
    resolved_root: str | None = None,
    resolved_ancestor: str | None = None,
) -> WriteBoundaryResult:
    return WriteBoundaryResult(
        False, code, reason, root, destination, resolved_root, resolved_ancestor
    )
