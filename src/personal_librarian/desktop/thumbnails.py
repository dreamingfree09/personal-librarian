"""Read-only, bounded thumbnail generation and asynchronous Qt loading."""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QObject, QRunnable, QSize, Signal
from PySide6.QtGui import QImage

from personal_librarian.safety import PathIntent, PathSafetyPolicy

THUMBNAIL_VERSION = "preview-format-boundary-v3"
IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".gif": "GIF", ".webp": "WEBP"}
SUPPORTED_IMAGE_SUFFIXES = frozenset(IMAGE_FORMATS)
MAX_SOURCE_PIXELS = 50_000_000


@dataclass(frozen=True, slots=True)
class ThumbnailResult:
    cache_key: str
    cache_path: Path | None
    error: str | None


class ThumbnailService:
    """Generate non-authoritative PNG previews without modifying source media."""

    def __init__(
        self,
        app_data_root: str | Path,
        *,
        max_size: tuple[int, int] = (192, 192),
        safety_policy: PathSafetyPolicy | None = None,
    ) -> None:
        self.policy = safety_policy or PathSafetyPolicy()
        root_check = self.policy.check_path(app_data_root, intent=PathIntent.READ)
        if not root_check.allowed:
            raise OSError(f"Unsafe application-data root: {root_check.code}")
        self.app_data_root = Path(app_data_root)
        self.cache_root = self.app_data_root / "state" / "thumbnails"
        self.max_size = max_size

    def cache_key(
        self,
        content_identity: str | int,
        *,
        physical_instance_id: int | None = None,
        source_path: str | Path | None = None,
        source_size: int | None = None,
        source_mtime_ns: int | None = None,
    ) -> str:
        instance_evidence = ""
        if physical_instance_id is not None:
            instance_evidence = (
                f":instance={physical_instance_id}:path={source_path}"
                f":size={source_size}:mtime={source_mtime_ns}"
            )
        material = (
            f"{THUMBNAIL_VERSION}:{content_identity}{instance_evidence}"
            f":{self.max_size[0]}x{self.max_size[1]}"
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def load(
        self,
        source_path: str | Path,
        *,
        content_identity: str | int,
        physical_instance_id: int | None = None,
    ) -> ThumbnailResult:
        source = Path(source_path)
        key = self.cache_key(
            content_identity,
            physical_instance_id=physical_instance_id,
            source_path=source if physical_instance_id is not None else None,
        )
        safety = self.policy.check_path(str(source), intent=PathIntent.READ)
        if not safety.allowed:
            return ThumbnailResult(key, None, f"Unsafe source path: {safety.code}")
        if source.suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES:
            return ThumbnailResult(key, None, "Preview is unavailable for this file type.")
        if not source.is_file():
            return ThumbnailResult(key, None, "Source media is unavailable.")
        try:
            source_stat = source.stat()
        except OSError as exc:
            return ThumbnailResult(key, None, f"Preview unavailable: {exc}")
        key = self.cache_key(
            content_identity,
            physical_instance_id=physical_instance_id,
            source_path=source if physical_instance_id is not None else None,
            source_size=source_stat.st_size if physical_instance_id is not None else None,
            source_mtime_ns=source_stat.st_mtime_ns if physical_instance_id is not None else None,
        )
        cache_path = self.cache_root / key[:2] / f"{key}.png"
        if cache_path.is_file():
            return ThumbnailResult(key, cache_path, None)
        temporary_cache = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        try:
            # Restrict plugin selection itself, before parsing metadata or pixels.
            # Passing every installed Pillow decoder here would make a trusted
            # extension sufficient to enter an excluded native decoder.
            with source.open("rb") as stream, warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                expected_format = IMAGE_FORMATS[source.suffix.casefold()]
                with Image.open(stream, formats=[expected_format]) as opened:
                    if opened.format != expected_format:
                        raise ValueError("Image content does not match its preview file type.")
                    if opened.width * opened.height > MAX_SOURCE_PIXELS:
                        raise ValueError("Image dimensions exceed the preview safety limit.")
                    opened.seek(0)
                    image = ImageOps.exif_transpose(opened).convert("RGBA")
                    image.thumbnail(self.max_size, Image.Resampling.LANCZOS)
                    self._prepare_cache_parent(cache_path.parent)
                    image.save(temporary_cache, format="PNG", optimize=True)
                    temporary_cache.replace(cache_path)
            return ThumbnailResult(key, cache_path, None)
        except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError,
                Image.DecompressionBombWarning, UnidentifiedImageError) as exc:
            return ThumbnailResult(key, None, f"Preview unavailable: {exc}")
        finally:
            temporary_cache.unlink(missing_ok=True)

    def _prepare_cache_parent(self, parent: Path) -> None:
        root_safety = self.policy.check_path(str(self.cache_root), intent=PathIntent.WRITE)
        parent_safety = self.policy.check_path(str(parent), intent=PathIntent.WRITE)
        if not root_safety.allowed or not parent_safety.allowed:
            raise OSError("Thumbnail cache path failed the application safety policy.")
        try:
            parent.resolve(strict=False).relative_to(self.cache_root.resolve(strict=False))
        except ValueError as exc:
            raise OSError("Thumbnail cache path escaped application state.") from exc
        parent.mkdir(parents=True, exist_ok=True)


class ThumbnailSignals(QObject):
    loaded = Signal(object, object, str)


class ThumbnailTask(QRunnable):
    """Small QThreadPool task; image decoding never runs on the UI thread."""

    def __init__(
        self,
        service: ThumbnailService,
        source_path: str,
        content_identity: str | int,
        token: object,
        physical_instance_id: int | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.source_path = source_path
        self.content_identity = content_identity
        self.token = token
        self.physical_instance_id = physical_instance_id
        self.signals = ThumbnailSignals()

    def run(self) -> None:
        result = self.service.load(
            self.source_path,
            content_identity=self.content_identity,
            physical_instance_id=self.physical_instance_id,
        )
        image = QImage()
        if result.cache_path is not None:
            image.load(str(result.cache_path))
        try:
            self.signals.loaded.emit(self.token, image, result.error or "")
        except RuntimeError:
            pass  # The owning review page may have closed while decoding finished.


def thumbnail_icon_size(size: int = 160) -> QSize:
    return QSize(size, size)
