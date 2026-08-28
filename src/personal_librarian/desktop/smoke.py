"""Explicit, bounded frozen-runtime validation used by packaging QA."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QPushButton

from personal_librarian.desktop.main_window import MainWindow
from personal_librarian.desktop.services import DesktopDataService
from personal_librarian.desktop.thumbnails import SUPPORTED_IMAGE_SUFFIXES, ThumbnailService
from personal_librarian.desktop.viewer import ImageViewerDialog
from personal_librarian.safety import PathIntent


def write_packaged_smoke_report(service: DesktopDataService, output_path: str | Path) -> None:
    """Exercise frozen desktop dependencies without entering an interactive event loop."""

    output = Path(output_path)
    dashboard = service.dashboard()
    exact = service.exact_reviews(status=None, limit=50, offset=0)
    similar = service.similar_reviews(status=None, limit=50, offset=0)
    years = service.browse_years()
    first_year = years["years"][0]["year"] if years["years"] else None
    year_content = service.year_content(year=first_year, limit=25, offset=0)
    exact_detail = service.exact_detail(int(exact["items"][0]["context_id"]))
    similar_detail = service.similar_detail(int(similar["items"][0]["context_id"]))
    window = MainWindow(service)
    button_text = {
        button.text().casefold() for button in window.findChildren(QPushButton)
    }
    preview: dict[str, Any] = {"result": "unavailable"}
    thumbnail_service = ThumbnailService(service.layout.root, max_size=(1600, 1200))
    for detail in (exact_detail, similar_detail):
        for item in detail["physical_instances"]:
            raw = item.get("current_observed_path")
            safety = service.policy.check_path(str(raw or ""), intent=PathIntent.READ)
            if (
                not raw
                or not safety.allowed
                or Path(raw).suffix.casefold() not in SUPPORTED_IMAGE_SUFFIXES
                or not Path(raw).is_file()
            ):
                continue
            source = Path(raw)
            before = (source.stat().st_size, source.stat().st_mtime_ns)
            generated = thumbnail_service.load(
                source, content_identity=item["content_identity_key"]
            )
            image = QImage(str(generated.cache_path)) if generated.cache_path else QImage()
            if not image.isNull():
                viewer = ImageViewerDialog(image, "packaged smoke")
                viewer.actual_size()
                viewer.zoom_in()
                viewer.zoom_out()
                viewer.fit_to_window()
                viewer.close()
            after = (source.stat().st_size, source.stat().st_mtime_ns)
            preview = {
                "result": "PASS" if generated.error is None and not image.isNull() else "FAIL",
                "source": str(source),
                "source_unchanged": before == after,
                "cache_path": None if generated.cache_path is None else str(generated.cache_path),
                "error": generated.error,
            }
            break
        if preview["result"] != "unavailable":
            break
    backups = service.backups()
    report = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "working_directory": os.getcwd(),
        "sys_path": list(sys.path),
        "navigation": list(window.SECTION_NAMES),
        "year_count": len(years["years"]),
        "first_year": first_year,
        "year_content_page_count": len(year_content["content"]),
        "year_content_total": year_content["total_matching"],
        "organisation_counts": {
            key: dashboard["counts"][key]
            for key in ("albums", "album_memberships", "tags", "content_tags", "organisation_events")
        },
        "production_health": dashboard["health"].get("summary"),
        "disaster_recovery": dashboard["health"].get("disaster_recovery", {}).get("summary"),
        "exact_page_count": len(exact["items"]),
        "exact_total": exact["total_matching"],
        "exact_detail_instances": len(exact_detail["physical_instances"]),
        "similar_page_count": len(similar["items"]),
        "similar_total": similar["total_matching"],
        "similar_detail_instances": len(similar_detail["physical_instances"]),
        "decision_count": len(service.decisions(limit=100)),
        "plan_count": len(service.plans(limit=50)["plans"]),
        "quarantine_count": len(service.quarantine(limit=100)["executions"]),
        "backup_count": (
            backups["operational"]["count"] + backups["independent"]["count"]
        ),
        "preview": preview,
        "forbidden_controls_present": any(
            text in {"delete", "execute", "restore", "quarantine"}
            for text in button_text
        ),
    }
    window.close()
    QThreadPool.globalInstance().waitForDone(30000)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
