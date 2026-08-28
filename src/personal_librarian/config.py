"""Typed, explicit-only TOML configuration loading."""

from __future__ import annotations

import ntpath
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from personal_librarian.safety import PathIntent, PathSafetyPolicy


class ConfigError(ValueError):
    """Raised when application configuration is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """M13 configuration. Raw path text is retained without filesystem resolution."""

    project_root: str | None = None
    data_root: str | None = None
    source_file: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "project_root": self.project_root,
            "data_root": self.data_root,
            "source_file": self.source_file,
        }


def load_config(
    config_path: str | os.PathLike[str] | None,
    *,
    safety_policy: PathSafetyPolicy | None = None,
) -> AppConfig:
    """Load explicit TOML configuration, or return safe unset defaults."""

    if config_path is None:
        return AppConfig()

    policy = safety_policy or PathSafetyPolicy()
    path_result = policy.check_path(config_path, intent=PathIntent.READ)
    if not path_result.allowed:
        raise ConfigError(f"Unsafe configuration path ({path_result.code}): {path_result.reason}")

    path = Path(config_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration file '{path}': {exc}") from exc

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in '{path}': {exc}") from exc

    unknown_sections = set(document) - {"paths"}
    if unknown_sections:
        names = ", ".join(sorted(unknown_sections))
        raise ConfigError(f"Unknown configuration section(s): {names}")

    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        raise ConfigError("The [paths] section must be a TOML table.")
    unknown_keys = set(paths) - {"project_root", "data_root"}
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ConfigError(f"Unknown [paths] key(s): {names}")

    project_root = _validate_root("project_root", paths.get("project_root"), policy)
    data_root = _validate_root("data_root", paths.get("data_root"), policy)
    return AppConfig(project_root=project_root, data_root=data_root, source_file=str(path))


def _validate_root(name: str, value: object, policy: PathSafetyPolicy) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.isspace():
        raise ConfigError(f"[paths].{name} must be a non-empty string.")

    candidate = value.replace("/", "\\")
    drive, tail = ntpath.splitdrive(candidate)
    is_drive_absolute = len(drive) == 2 and drive[1] == ":" and tail.startswith("\\")
    is_unc_absolute = candidate.startswith("\\\\") and bool(drive)
    if not (is_drive_absolute or is_unc_absolute):
        raise ConfigError(f"[paths].{name} must be an absolute Windows drive or UNC path.")

    result = policy.check_path(value, intent=PathIntent.READ)
    if not result.allowed:
        raise ConfigError(f"Unsafe [paths].{name} ({result.code}): {result.reason}")
    return value
