"""Command-line entry point for the M13 application foundation."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Sequence

from personal_librarian import __version__
from personal_librarian.action_planning import (
    DEFAULT_SAFETY_MARGIN_BYTES,
    POLICIES,
    create_plan,
    invalidate_plan,
    list_plans,
    plan_report,
    preflight_plan,
    show_plan,
)
from personal_librarian.catalogue.database import get_catalogue_status, initialise_catalogue
from personal_librarian.catalogue.errors import CatalogueError
from personal_librarian.catalogue.importers import import_verified_evidence
from personal_librarian.catalogue.models import CatalogueStatus
from personal_librarian.config import AppConfig, ConfigError, load_config
from personal_librarian.collections import (
    add_content_to_collection,
    archive_collection,
    collection_history,
    create_collection,
    get_collection,
    list_collection_members,
    list_collections,
    list_collections_for_content,
    remove_content_from_collection,
    rename_collection,
    restore_collection,
    restore_content_to_collection,
)
from personal_librarian.decisions import (
    abstain as decision_abstain,
    approve as decision_approve,
    current_decisions,
    decision_history,
    nominate as decision_nominate,
    reject as decision_reject,
    supersede as decision_supersede,
)
from personal_librarian.date_evidence import (
    PreferredStatus,
    get_preferred_date,
    list_date_evidence,
    list_owner_overrides,
    list_preferred_basis,
    list_preferred_identities,
    preferred_date_counts,
    set_owner_preferred_date,
)
from personal_librarian.jobs import RunContext
from personal_librarian.logging_setup import configure_logging
from personal_librarian.organisation import (
    add_content_to_album,
    archive_album,
    create_album,
    get_album,
    list_album_members,
    list_albums,
    list_albums_for_content,
    organisation_history,
    remove_content_from_album,
    rename_album,
    restore_album,
)
from personal_librarian.pipeline import (
    derive_exact_duplicates,
    reconcile_m11_baseline,
    reconcile_historical_baseline,
    run_inventory,
    run_date_evidence_pipeline,
    run_perceptual_hashing,
    run_sha256,
    run_similarity_analysis,
    run_similarity_groups,
)
from personal_librarian.pipeline.perceptual_hashing import DEFAULT_HASH_SUITE_VERSION
from personal_librarian.pipeline.similarity import DUAL_HASH_RULE_VERSION
from personal_librarian.review import (
    list_exact_reviews,
    list_similar_reviews,
    show_exact_review,
    show_similar_review,
)
from personal_librarian.quarantine import (
    execute_quarantine,
    quarantine_history,
    quarantine_status,
    reconcile_quarantine,
    restore_quarantine,
)
from personal_librarian.production import (
    BACKUP_CLASSES,
    bootstrap_production,
    create_backup,
    list_backups,
    production_health,
    recover_production,
    retention_report,
    verify_backup,
)
from personal_librarian.safety import (
    OperationMode,
    PathIntent,
    PathSafetyPolicy,
    assess_operation,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-librarian")
    parser.add_argument(
        "--mode",
        choices=(OperationMode.READ_ONLY.value, OperationMode.DRY_RUN.value),
        default=OperationMode.READ_ONLY.value,
        help="Read-only and dry-run media-operation modes; action mode is unavailable.",
    )
    parser.add_argument("--config", help="Explicit path to a TOML configuration file.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("version", help="Show the package version.")
    commands.add_parser("doctor", help="Check runtime and safety-policy state without scanning media.")
    desktop_parser = commands.add_parser("desktop", help="Launch the local desktop review interface.")
    desktop_parser.add_argument("--app-data-root", required=True)
    desktop_parser.add_argument("--independent-backup-root")

    config_parser = commands.add_parser("config", help="Inspect application configuration.")
    config_commands = config_parser.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show", help="Show validated configuration values.")

    safety_parser = commands.add_parser("safety", help="Inspect central safety-policy decisions.")
    safety_commands = safety_parser.add_subparsers(dest="safety_command", required=True)
    check_path = safety_commands.add_parser("check-path", help="Assess a path without accessing it.")
    check_path.add_argument("path")
    check_path.add_argument("--base", help="Explicit absolute base used for a relative path.")
    check_path.add_argument(
        "--intent",
        choices=(PathIntent.READ.value, PathIntent.WRITE.value),
        default=PathIntent.READ.value,
    )

    catalogue_parser = commands.add_parser("catalogue", help="Manage an explicit SQLite catalogue.")
    catalogue_commands = catalogue_parser.add_subparsers(dest="catalogue_command", required=True)
    catalogue_init = catalogue_commands.add_parser(
        "init", help="Create or migrate the explicitly supplied catalogue database."
    )
    catalogue_init.add_argument("--database", required=True)
    catalogue_status = catalogue_commands.add_parser(
        "status", help="Inspect an existing catalogue without changing it."
    )
    catalogue_status.add_argument("--database", required=True)
    catalogue_import = catalogue_commands.add_parser(
        "import-evidence",
        help="Import explicitly supplied verified M9/M10/M11 CSV evidence.",
    )
    catalogue_import.add_argument("--database", required=True)
    catalogue_import.add_argument("--m9", required=True)
    catalogue_import.add_argument("--m10-manifest", required=True)
    catalogue_import.add_argument("--m10-groups", required=True)
    catalogue_import.add_argument("--m10-rows", required=True)
    catalogue_import.add_argument("--m11-dualhash", required=True)
    catalogue_import.add_argument("--m11-pairs", required=True)
    catalogue_import.add_argument("--m11-groups", required=True)
    catalogue_import.add_argument("--m11-summary", required=True)
    catalogue_backup = catalogue_commands.add_parser(
        "backup", help="Create, list, verify, or report production catalogue backups."
    )
    backup_commands = catalogue_backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser("create")
    backup_create.add_argument("--app-data-root", required=True)
    backup_create.add_argument("--backup-root")
    backup_create.add_argument(
        "--backup-class", choices=tuple(sorted(BACKUP_CLASSES)), default="operational-local"
    )
    backup_create.add_argument("--reason", default="manual")
    backup_create.add_argument("--format", choices=("human", "json"), default="human")
    backup_list = backup_commands.add_parser("list")
    backup_list.add_argument("--app-data-root", required=True)
    backup_list.add_argument("--backup-root")
    backup_list.add_argument("--backup-class", choices=tuple(sorted(BACKUP_CLASSES)))
    backup_list.add_argument("--format", choices=("human", "json"), default="human")
    backup_verify = backup_commands.add_parser("verify")
    backup_verify.add_argument("--app-data-root")
    backup_verify.add_argument("--expected-catalogue-uuid")
    backup_verify.add_argument("--manifest", required=True)
    backup_verify.add_argument("--format", choices=("human", "json"), default="human")
    backup_report = backup_commands.add_parser("report")
    backup_report.add_argument("--app-data-root", required=True)
    backup_report.add_argument("--backup-root")
    backup_report.add_argument("--backup-class", choices=tuple(sorted(BACKUP_CLASSES)))
    backup_report.add_argument("--keep-latest", type=int, default=10)
    backup_report.add_argument("--format", choices=("human", "json"), default="human")

    production_parser = commands.add_parser(
        "production", help="Bootstrap, inspect, or recover an explicit production catalogue."
    )
    production_commands = production_parser.add_subparsers(dest="production_command", required=True)
    production_bootstrap = production_commands.add_parser("bootstrap")
    production_bootstrap.add_argument("--app-data-root", required=True)
    production_bootstrap.add_argument("--m9", required=True)
    production_bootstrap.add_argument("--m10-manifest", required=True)
    production_bootstrap.add_argument("--m10-groups", required=True)
    production_bootstrap.add_argument("--m10-rows", required=True)
    production_bootstrap.add_argument("--m11-dualhash", required=True)
    production_bootstrap.add_argument("--m11-pairs", required=True)
    production_bootstrap.add_argument("--m11-groups", required=True)
    production_bootstrap.add_argument("--m11-summary", required=True)
    production_bootstrap.add_argument("--format", choices=("human", "json"), default="human")
    production_health_parser = production_commands.add_parser("health")
    production_health_parser.add_argument("--app-data-root", required=True)
    production_health_parser.add_argument("--independent-backup-root")
    production_health_parser.add_argument("--format", choices=("human", "json"), default="human")
    production_recover = production_commands.add_parser("recover")
    production_recover.add_argument("--app-data-root", required=True)
    production_recover.add_argument("--manifest", required=True)
    production_recover.add_argument("--actor", required=True)
    production_recover.add_argument("--confirm-restore-catalogue", action="store_true")
    production_recover.add_argument("--format", choices=("human", "json"), default="human")

    inventory_parser = commands.add_parser("inventory", help="Run reproducible media inventory.")
    inventory_commands = inventory_parser.add_subparsers(dest="inventory_command", required=True)
    inventory_scan = inventory_commands.add_parser("scan", help="Inventory an explicit media root.")
    _add_pipeline_identity_arguments(inventory_scan, include_root=True)
    inventory_scan.add_argument("--limit", type=int, help="Bound the number of media items.")

    hash_parser = commands.add_parser("hash", help="Run reproducible content hashing.")
    hash_commands = hash_parser.add_subparsers(dest="hash_command", required=True)
    hash_sha256 = hash_commands.add_parser("sha256", help="Hash a completed inventory job.")
    _add_pipeline_identity_arguments(hash_sha256, include_root=True)
    hash_sha256.add_argument("--inventory-job", required=True)
    hash_sha256.add_argument("--limit", type=int, help="Bound the number of items hashed.")

    duplicate_parser = commands.add_parser(
        "exact-duplicates", help="Derive informational exact-duplicate groups."
    )
    duplicate_commands = duplicate_parser.add_subparsers(
        dest="exact_duplicates_command", required=True
    )
    duplicate_report = duplicate_commands.add_parser("report")
    duplicate_report.add_argument("--database", required=True)
    duplicate_report.add_argument("--job-id", required=True)
    duplicate_report.add_argument("--hash-job", required=True)

    pipeline_parser = commands.add_parser("pipeline", help="Inspect pipeline reconciliation.")
    pipeline_commands = pipeline_parser.add_subparsers(dest="pipeline_command", required=True)
    reconcile = pipeline_commands.add_parser(
        "reconcile", help="Compare catalogue state with verified M9/M10 baselines."
    )
    reconcile.add_argument("--database", required=True)

    similarity_parser = commands.add_parser(
        "similarity", help="Run reproducible perceptual near-duplicate analysis."
    )
    similarity_commands = similarity_parser.add_subparsers(
        dest="similarity_command", required=True
    )
    similarity_hash = similarity_commands.add_parser(
        "hash", help="Calculate pHash and dHash per exact content identity."
    )
    similarity_hash.add_argument("--database", required=True)
    similarity_hash.add_argument("--job-id", required=True)
    similarity_hash.add_argument("--limit", type=int)
    similarity_hash.add_argument(
        "--hash-suite-version", default=DEFAULT_HASH_SUITE_VERSION
    )
    similarity_analyse = similarity_commands.add_parser(
        "analyse", help="Generate review-only dual-hash relationships."
    )
    similarity_analyse.add_argument("--database", required=True)
    similarity_analyse.add_argument("--job-id", required=True)
    similarity_analyse.add_argument("--hash-job", required=True)
    similarity_analyse.add_argument("--limit", type=int)
    similarity_analyse.add_argument("--rule-version", default=DUAL_HASH_RULE_VERSION)
    similarity_report = similarity_commands.add_parser(
        "report", help="Build connected-component review groups."
    )
    similarity_report.add_argument("--database", required=True)
    similarity_report.add_argument("--job-id", required=True)
    similarity_report.add_argument("--analysis-job", required=True)
    similarity_reconcile = similarity_commands.add_parser(
        "reconcile", help="Compare imported M11 evidence with the verified baseline."
    )
    similarity_reconcile.add_argument("--database", required=True)

    review_parser = commands.add_parser(
        "review", help="Inspect deterministic exact and near-duplicate review queues."
    )
    review_types = review_parser.add_subparsers(dest="review_type", required=True)
    for review_type in ("exact", "similar"):
        type_parser = review_types.add_parser(review_type)
        type_commands = type_parser.add_subparsers(dest="review_command", required=True)
        list_parser = type_commands.add_parser("list")
        list_parser.add_argument("--database", required=True)
        list_parser.add_argument(
            "--status",
            choices=(
                "pending", "reviewed", "partially_reviewed", "decided",
                "abstained", "reopened",
            ),
        )
        list_parser.add_argument("--limit", type=int, default=50)
        list_parser.add_argument("--offset", type=int, default=0)
        list_parser.add_argument("--format", choices=("human", "json"), default="human")
        show_parser = type_commands.add_parser("show")
        show_parser.add_argument("context_id", type=int)
        show_parser.add_argument("--database", required=True)
        show_parser.add_argument("--format", choices=("human", "json"), default="human")

    decision_parser = commands.add_parser(
        "decision", help="Record or inspect append-only owner decision events."
    )
    decision_commands = decision_parser.add_subparsers(
        dest="decision_command", required=True
    )
    nominate_parser = decision_commands.add_parser("nominate")
    _add_decision_write_arguments(nominate_parser, include_context=True)
    nominate_parser.add_argument("--physical-instance-id", type=int, required=True)

    for action in ("approve", "reject"):
        action_parser = decision_commands.add_parser(action)
        _add_decision_write_arguments(action_parser, include_context=False)
        action_parser.add_argument("--nomination-id", required=True)
        action_parser.add_argument("--physical-instance-id", type=int, required=True)

    supersede_parser = decision_commands.add_parser("supersede")
    _add_decision_write_arguments(supersede_parser, include_context=False)
    supersede_parser.add_argument("--nomination-id", required=True)
    supersede_parser.add_argument("--prior-approval-id", required=True)
    supersede_parser.add_argument("--physical-instance-id", type=int, required=True)

    abstain_parser = decision_commands.add_parser("abstain")
    _add_decision_write_arguments(abstain_parser, include_context=True)
    abstain_parser.add_argument("--content-identity-id", type=int, required=True)
    abstain_parser.add_argument("--prior-approval-id")

    current_parser = decision_commands.add_parser("current")
    _add_decision_read_arguments(current_parser)
    history_parser = decision_commands.add_parser("history")
    _add_decision_read_arguments(history_parser)
    history_parser.add_argument("--limit", type=int, default=100)
    history_parser.add_argument("--offset", type=int, default=0)

    albums_parser = commands.add_parser(
        "albums", help="Manage owner-created logical albums without changing media files."
    )
    album_commands = albums_parser.add_subparsers(dest="albums_command", required=True)
    albums_list = album_commands.add_parser("list")
    _add_album_read_arguments(albums_list)
    albums_list.add_argument("--include-archived", action="store_true")
    albums_list.add_argument("--limit", type=int, default=100)
    albums_list.add_argument("--offset", type=int, default=0)
    albums_create = album_commands.add_parser("create")
    _add_album_mutation_arguments(albums_create)
    albums_create.add_argument("--name", required=True)
    albums_create.add_argument("--description")
    for command_name in ("show", "members"):
        command_parser = album_commands.add_parser(command_name)
        command_parser.add_argument("album_uuid")
        _add_album_read_arguments(command_parser)
        if command_name == "members":
            command_parser.add_argument("--include-removed", action="store_true")
            command_parser.add_argument("--limit", type=int, default=100)
            command_parser.add_argument("--offset", type=int, default=0)
    albums_rename = album_commands.add_parser("rename")
    albums_rename.add_argument("album_uuid")
    _add_album_mutation_arguments(albums_rename)
    albums_rename.add_argument("--name", required=True)
    for command_name in ("archive", "restore"):
        command_parser = album_commands.add_parser(command_name)
        command_parser.add_argument("album_uuid")
        _add_album_mutation_arguments(command_parser)
    for command_name in ("add-content", "remove-content"):
        command_parser = album_commands.add_parser(command_name)
        command_parser.add_argument("album_uuid")
        command_parser.add_argument("content_identity_id", type=int)
        _add_album_mutation_arguments(command_parser)
    albums_for_content = album_commands.add_parser("for-content")
    albums_for_content.add_argument("content_identity_id", type=int)
    _add_album_read_arguments(albums_for_content)
    albums_for_content.add_argument("--include-removed", action="store_true")
    albums_history = album_commands.add_parser("history")
    _add_album_read_arguments(albums_history)
    albums_history.add_argument("--album-uuid")
    albums_history.add_argument("--content-identity-id", type=int)
    albums_history.add_argument("--limit", type=int, default=100)
    albums_history.add_argument("--offset", type=int, default=0)

    dates_parser = commands.add_parser(
        "dates", help="Inspect or populate deterministic preferred-date evidence."
    )
    date_commands = dates_parser.add_subparsers(dest="dates_command", required=True)
    for command_name in ("show", "evidence", "basis"):
        command_parser = date_commands.add_parser(command_name)
        command_parser.add_argument("content_identity_id", type=int)
        command_parser.add_argument("--database", required=True)
        if command_name == "evidence":
            command_parser.add_argument("--limit", type=int, default=100)
            command_parser.add_argument("--offset", type=int, default=0)
        command_parser.add_argument("--format", choices=("human", "json"), default="human")
    for command_name in ("review-list", "unknown-list", "owner-list"):
        command_parser = date_commands.add_parser(command_name)
        command_parser.add_argument("--database", required=True)
        command_parser.add_argument("--limit", type=int, default=50)
        command_parser.add_argument("--offset", type=int, default=0)
        command_parser.add_argument("--format", choices=("human", "json"), default="human")
    dates_counts = date_commands.add_parser("counts")
    dates_counts.add_argument("--database", required=True)
    dates_counts.add_argument("--format", choices=("human", "json"), default="human")
    dates_run = date_commands.add_parser("run")
    dates_run.add_argument("--database", required=True)
    dates_run.add_argument("--job-id", required=True)
    dates_run.add_argument(
        "--after-physical-instance-id", type=int, default=0,
        help="Select only physical-instance IDs greater than this deterministic cursor.",
    )
    dates_run.add_argument("--limit", type=int, default=1000)
    dates_run.add_argument("--format", choices=("human", "json"), default="human")
    dates_owner = date_commands.add_parser("owner-set")
    dates_owner.add_argument("content_identity_id", type=int)
    dates_owner.add_argument("--database", required=True)
    dates_owner.add_argument("--value", required=True)
    dates_owner.add_argument("--actor", required=True)
    dates_owner.add_argument("--action-id", required=True)
    dates_owner.add_argument("--reason")
    dates_owner.add_argument("--provenance", default="owner-manual")
    dates_owner.add_argument("--confirm-owner-date", action="store_true")
    dates_owner.add_argument("--format", choices=("human", "json"), default="human")

    collections_parser = commands.add_parser(
        "collections", help="Manage owner-created cross-year logical Collections."
    )
    collection_commands = collections_parser.add_subparsers(
        dest="collections_command", required=True
    )
    collections_list = collection_commands.add_parser("list")
    _add_collection_read_arguments(collections_list)
    collections_list.add_argument(
        "--state", choices=("active", "archived", "all"), default="active"
    )
    collections_list.add_argument("--limit", type=int, default=100)
    collections_list.add_argument("--offset", type=int, default=0)
    collections_create = collection_commands.add_parser("create")
    _add_collection_mutation_arguments(collections_create)
    collections_create.add_argument("--name", required=True)
    collections_create.add_argument("--description")
    for command_name in ("show", "members", "history"):
        command_parser = collection_commands.add_parser(command_name)
        command_parser.add_argument("collection_uuid")
        _add_collection_read_arguments(command_parser)
        if command_name in {"members", "history"}:
            command_parser.add_argument("--limit", type=int, default=100)
            command_parser.add_argument("--offset", type=int, default=0)
        if command_name == "members":
            command_parser.add_argument("--include-removed", action="store_true")
    collections_rename = collection_commands.add_parser("rename")
    collections_rename.add_argument("collection_uuid")
    _add_collection_mutation_arguments(collections_rename)
    collections_rename.add_argument("--name", required=True)
    for command_name in ("archive", "restore"):
        command_parser = collection_commands.add_parser(command_name)
        command_parser.add_argument("collection_uuid")
        _add_collection_mutation_arguments(command_parser)
    for command_name in ("add", "remove", "restore-member"):
        command_parser = collection_commands.add_parser(command_name)
        command_parser.add_argument("collection_uuid")
        command_parser.add_argument("content_identity_id", type=int)
        _add_collection_mutation_arguments(command_parser)
    collections_for_content = collection_commands.add_parser("for-content")
    collections_for_content.add_argument("content_identity_id", type=int)
    _add_collection_read_arguments(collections_for_content)
    collections_for_content.add_argument("--include-removed", action="store_true")
    collections_for_content.add_argument("--limit", type=int, default=100)
    collections_for_content.add_argument("--offset", type=int, default=0)

    plan_parser = commands.add_parser(
        "plan", help="Create and inspect non-executable M18 physical-action plans."
    )
    plan_commands = plan_parser.add_subparsers(dest="plan_command", required=True)
    plan_create = plan_commands.add_parser("create")
    plan_create.add_argument("--database", required=True)
    plan_create.add_argument("--policy", choices=tuple(POLICIES), required=True)
    plan_create.add_argument("--context-type", choices=("exact", "similar"), required=True)
    plan_create.add_argument("--context-id", type=int, required=True)
    plan_create.add_argument(
        "--scope", choices=("archival", "display_export"), required=True
    )
    plan_create.add_argument("--approval-event-id", required=True)
    plan_create.add_argument("--destination-root", required=True)
    plan_create.add_argument("--owner", required=True)
    plan_create.add_argument("--source-instance-id", type=int, action="append")
    plan_create.add_argument(
        "--safety-margin-bytes", type=int, default=DEFAULT_SAFETY_MARGIN_BYTES
    )
    plan_create.add_argument("--reason")
    plan_create.add_argument("--format", choices=("human", "json"), default="human")
    plan_list = plan_commands.add_parser("list")
    plan_list.add_argument("--database", required=True)
    plan_list.add_argument(
        "--status",
        choices=("draft", "preflight_passed", "preflight_failed", "stale", "invalidated"),
    )
    plan_list.add_argument("--limit", type=int, default=50)
    plan_list.add_argument("--offset", type=int, default=0)
    plan_list.add_argument("--format", choices=("human", "json"), default="human")
    for command_name in ("show", "report"):
        command_parser = plan_commands.add_parser(command_name)
        command_parser.add_argument("plan_id")
        command_parser.add_argument("--database", required=True)
        command_parser.add_argument("--format", choices=("human", "json"), default="human")
    plan_preflight = plan_commands.add_parser("preflight")
    plan_preflight.add_argument("plan_id")
    plan_preflight.add_argument("--database", required=True)
    plan_preflight.add_argument("--actor", required=True)
    plan_preflight.add_argument("--format", choices=("human", "json"), default="human")
    plan_invalidate = plan_commands.add_parser("invalidate")
    plan_invalidate.add_argument("plan_id")
    plan_invalidate.add_argument("--database", required=True)
    plan_invalidate.add_argument("--event-id", required=True)
    plan_invalidate.add_argument("--owner", required=True)
    plan_invalidate.add_argument("--reason", required=True)
    plan_invalidate.add_argument("--format", choices=("human", "json"), default="human")

    quarantine_parser = commands.add_parser(
        "quarantine", help="Execute or restore one explicitly approved exact quarantine."
    )
    quarantine_commands = quarantine_parser.add_subparsers(
        dest="quarantine_command", required=True
    )
    quarantine_execute = quarantine_commands.add_parser("execute")
    quarantine_execute.add_argument("--database", required=True)
    quarantine_execute.add_argument("--plan-id", required=True)
    quarantine_execute.add_argument("--item-id", required=True)
    quarantine_execute.add_argument("--quarantine-root", required=True)
    quarantine_execute.add_argument("--actor", required=True)
    quarantine_execute.add_argument("--confirm-quarantine", action="store_true")
    quarantine_execute.add_argument("--format", choices=("human", "json"), default="human")
    quarantine_status_parser = quarantine_commands.add_parser("status")
    quarantine_status_parser.add_argument("execution_id")
    quarantine_status_parser.add_argument("--database", required=True)
    quarantine_status_parser.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    quarantine_history_parser = quarantine_commands.add_parser("history")
    quarantine_history_parser.add_argument("--database", required=True)
    quarantine_history_parser.add_argument("--plan-id")
    quarantine_history_parser.add_argument("--item-id")
    quarantine_history_parser.add_argument("--limit", type=int, default=100)
    quarantine_history_parser.add_argument("--offset", type=int, default=0)
    quarantine_history_parser.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    quarantine_reconcile = quarantine_commands.add_parser("reconcile")
    quarantine_reconcile.add_argument("execution_id")
    quarantine_reconcile.add_argument("--database", required=True)
    quarantine_reconcile.add_argument("--actor", required=True)
    quarantine_reconcile.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    quarantine_restore = quarantine_commands.add_parser("restore")
    quarantine_restore.add_argument("execution_id")
    quarantine_restore.add_argument("--database", required=True)
    quarantine_restore.add_argument("--actor", required=True)
    quarantine_restore.add_argument("--confirm-restore", action="store_true")
    quarantine_restore.add_argument(
        "--format", choices=("human", "json"), default="human"
    )
    return parser


def _add_pipeline_identity_arguments(parser: argparse.ArgumentParser, *, include_root: bool) -> None:
    parser.add_argument("--database", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source", required=True)
    if include_root:
        parser.add_argument("--root", required=True)


def _add_decision_write_arguments(
    parser: argparse.ArgumentParser, *, include_context: bool
) -> None:
    parser.add_argument("--database", required=True)
    parser.add_argument("--event-id", required=True)
    if include_context:
        parser.add_argument("--context-type", choices=("exact", "similar"), required=True)
        parser.add_argument("--context-id", type=int, required=True)
    parser.add_argument(
        "--scope", choices=("archival", "display_export"), required=True
    )
    parser.add_argument("--owner", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--format", choices=("human", "json"), default="human")


def _add_decision_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", required=True)
    parser.add_argument("--context-type", choices=("exact", "similar"))
    parser.add_argument("--context-id", type=int)
    parser.add_argument("--format", choices=("human", "json"), default="human")


def _add_album_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", required=True)
    parser.add_argument("--format", choices=("human", "json"), default="human")


def _add_album_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    _add_album_read_arguments(parser)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--provenance", default="owner-manual")


def _add_collection_read_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", required=True)
    parser.add_argument("--format", choices=("human", "json"), default="human")


def _add_collection_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    _add_collection_read_arguments(parser)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--action-id", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--provenance", default="owner-manual")
    parser.add_argument("--confirm-collection-action", action="store_true")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = OperationMode(args.mode)
    context = RunContext.create(mode)
    logger = configure_logging(context.run_id, verbose=args.verbose)
    catalogue_access = "none"
    if args.command == "catalogue":
        catalogue_access = {
            "init": "create-or-migrate",
            "status": "read-only",
            "import-evidence": "verified-evidence-import",
            "backup": "production-backup-control",
        }[args.catalogue_command]
    elif args.command == "production":
        catalogue_access = (
            "read-only" if args.production_command == "health" else "production-control"
        )
    elif args.command in {"inventory", "hash", "exact-duplicates"}:
        catalogue_access = "pipeline-write"
    elif args.command == "pipeline":
        catalogue_access = "read-only"
    elif args.command == "similarity":
        catalogue_access = (
            "read-only" if args.similarity_command == "reconcile" else "pipeline-write"
        )
    elif args.command == "review":
        catalogue_access = "read-only"
    elif args.command == "decision":
        catalogue_access = (
            "read-only"
            if args.decision_command in {"current", "history"}
            else "owner-decision-write"
        )
    elif args.command == "albums":
        catalogue_access = (
            "read-only"
            if args.albums_command in {"list", "show", "members", "for-content", "history"}
            else "owner-organisation-write"
        )
    elif args.command == "dates":
        catalogue_access = (
            "read-only"
            if args.dates_command in {
                "show", "evidence", "basis", "review-list", "unknown-list",
                "owner-list", "counts",
            }
            else "date-evidence-write"
        )
    elif args.command == "collections":
        catalogue_access = (
            "read-only"
            if args.collections_command in {
                "list", "show", "members", "history", "for-content"
            }
            else "owner-collection-write"
        )
    elif args.command == "plan":
        catalogue_access = (
            "read-only"
            if args.plan_command in {"list", "show", "report"}
            else "planning-control-write"
        )
    elif args.command == "quarantine":
        catalogue_access = (
            "read-only"
            if args.quarantine_command in {"status", "history"}
            else "narrow-quarantine-control"
        )
    elif args.command == "desktop":
        catalogue_access = "review-and-owner-decision"
    logger.info(
        "command=%s media_mode=%s catalogue_access=%s",
        args.command,
        mode.value,
        catalogue_access,
    )

    policy = PathSafetyPolicy()
    try:
        if args.command == "version":
            print(f"Personal Librarian {__version__}")
            return 0
        if args.command == "doctor":
            config = load_config(args.config, safety_policy=policy)
            return _doctor(config, policy)
        if args.command == "desktop":
            from personal_librarian.desktop.app import run_desktop

            return run_desktop(
                app_data_root=args.app_data_root,
                independent_backup_root=args.independent_backup_root,
            )
        if args.command == "config" and args.config_command == "show":
            config = load_config(args.config, safety_policy=policy)
            _show_config(config)
            return 0
        if args.command == "safety" and args.safety_command == "check-path":
            return _check_path(args, mode, policy)
        if args.command == "catalogue" and args.catalogue_command == "init":
            status = initialise_catalogue(args.database, safety_policy=policy)
            _show_catalogue_status(status)
            return 0
        if args.command == "catalogue" and args.catalogue_command == "status":
            status = get_catalogue_status(args.database, safety_policy=policy)
            _show_catalogue_status(status)
            return 0
        if args.command == "catalogue" and args.catalogue_command == "import-evidence":
            report = import_verified_evidence(
                database_path=args.database,
                m9_path=args.m9,
                m10_manifest_path=args.m10_manifest,
                m10_groups_path=args.m10_groups,
                m10_rows_path=args.m10_rows,
                m11_dualhash_path=args.m11_dualhash,
                m11_pairs_path=args.m11_pairs,
                m11_groups_path=args.m11_groups,
                m11_summary_path=args.m11_summary,
                safety_policy=policy,
            )
            print(report.format_human())
            print(f"RECONCILIATION_JSON: {report.to_json()}")
            return 0
        if args.command == "catalogue" and args.catalogue_command == "backup":
            if args.backup_command == "create":
                report = create_backup(
                    app_data_root=args.app_data_root, backup_root=args.backup_root,
                    backup_class=args.backup_class, reason=args.reason, safety_policy=policy,
                )
            elif args.backup_command == "list":
                report = list_backups(
                    app_data_root=args.app_data_root, backup_root=args.backup_root,
                    backup_class=args.backup_class,
                    safety_policy=policy,
                )
            elif args.backup_command == "verify":
                expected_uuid = args.expected_catalogue_uuid
                if args.app_data_root is not None:
                    health = production_health(app_data_root=args.app_data_root, safety_policy=policy)
                    production_uuid = health.values.get("catalogue_uuid")
                    if health.values.get("summary") == "FAIL" or production_uuid is None:
                        raise CatalogueError(
                            "The explicit application-data root does not identify a readable production catalogue."
                        )
                    if expected_uuid is not None and expected_uuid != production_uuid:
                        raise CatalogueError(
                            "Expected catalogue UUID differs from the explicit production catalogue."
                        )
                    expected_uuid = production_uuid
                report = verify_backup(
                    args.manifest, expected_catalogue_uuid=expected_uuid, safety_policy=policy
                )
            else:
                report = retention_report(
                    app_data_root=args.app_data_root, backup_root=args.backup_root,
                    backup_class=args.backup_class, keep_latest=args.keep_latest,
                    safety_policy=policy,
                )
            _show_structured(report, args.format)
            return 0 if report.values.get("result") != "REJECTED" else 1
        if args.command == "production" and args.production_command == "bootstrap":
            report = bootstrap_production(
                app_data_root=args.app_data_root,
                m9_path=args.m9, m10_manifest_path=args.m10_manifest,
                m10_groups_path=args.m10_groups, m10_rows_path=args.m10_rows,
                m11_dualhash_path=args.m11_dualhash, m11_pairs_path=args.m11_pairs,
                m11_groups_path=args.m11_groups, m11_summary_path=args.m11_summary,
                safety_policy=policy,
            )
            _show_structured(report, args.format)
            return 0
        if args.command == "production" and args.production_command == "health":
            report = production_health(
                app_data_root=args.app_data_root,
                independent_backup_root=args.independent_backup_root,
                safety_policy=policy,
            )
            _show_structured(report, args.format)
            return 0 if report.values.get("summary") in {"PASS", "WARN"} else 1
        if args.command == "production" and args.production_command == "recover":
            report = recover_production(
                app_data_root=args.app_data_root, manifest_path=args.manifest,
                actor=args.actor,
                confirm_restore_catalogue=args.confirm_restore_catalogue,
                safety_policy=policy,
            )
            _show_structured(report, args.format)
            return 0
        if args.command == "inventory" and args.inventory_command == "scan":
            report = run_inventory(
                database_path=args.database, job_id=args.job_id, source=args.source,
                root=args.root, max_media_items=args.limit, safety_policy=policy,
            )
            _show_pipeline_report(report)
            return 0
        if args.command == "hash" and args.hash_command == "sha256":
            report = run_sha256(
                database_path=args.database, job_id=args.job_id,
                inventory_job_id=args.inventory_job, source=args.source, root=args.root,
                max_items=args.limit, safety_policy=policy,
            )
            _show_pipeline_report(report)
            return 0 if report.metrics["hash_errors"] == 0 else 1
        if (
            args.command == "exact-duplicates"
            and args.exact_duplicates_command == "report"
        ):
            report = derive_exact_duplicates(
                database_path=args.database, job_id=args.job_id,
                hash_job_id=args.hash_job, safety_policy=policy,
            )
            _show_pipeline_report(report)
            return 0
        if args.command == "pipeline" and args.pipeline_command == "reconcile":
            report = reconcile_historical_baseline(args.database, safety_policy=policy)
            print(report.format_human())
            print(f"RECONCILIATION_JSON: {report.to_json()}")
            return 0 if report.matches_baseline else 1
        if args.command == "similarity" and args.similarity_command == "hash":
            report = run_perceptual_hashing(
                database_path=args.database,
                job_id=args.job_id,
                limit=args.limit,
                hash_suite_version=args.hash_suite_version,
                safety_policy=policy,
            )
            _show_pipeline_report(report)
            return 0 if report.metrics["phash_errors"] == 0 else 1
        if args.command == "similarity" and args.similarity_command == "analyse":
            report = run_similarity_analysis(
                database_path=args.database,
                job_id=args.job_id,
                hash_job_id=args.hash_job,
                limit=args.limit,
                rule_version=args.rule_version,
                safety_policy=policy,
            )
            _show_pipeline_report(report)
            return 0
        if args.command == "similarity" and args.similarity_command == "report":
            report = run_similarity_groups(
                database_path=args.database,
                job_id=args.job_id,
                analysis_job_id=args.analysis_job,
                safety_policy=policy,
            )
            _show_pipeline_report(report)
            return 0
        if args.command == "similarity" and args.similarity_command == "reconcile":
            report = reconcile_m11_baseline(args.database, safety_policy=policy)
            print(report.format_human())
            print(f"RECONCILIATION_JSON: {report.to_json()}")
            return 0 if report.matches_baseline else 1
        if args.command == "review":
            if args.review_type == "exact" and args.review_command == "list":
                result = list_exact_reviews(
                    database_path=args.database, status=args.status,
                    limit=args.limit, offset=args.offset, safety_policy=policy,
                )
            elif args.review_type == "exact":
                result = show_exact_review(
                    database_path=args.database, context_id=args.context_id,
                    safety_policy=policy,
                )
            elif args.review_command == "list":
                result = list_similar_reviews(
                    database_path=args.database, status=args.status,
                    limit=args.limit, offset=args.offset, safety_policy=policy,
                )
            else:
                result = show_similar_review(
                    database_path=args.database, context_id=args.context_id,
                    safety_policy=policy,
                )
            _show_structured(result, args.format)
            return 0
        if args.command == "decision" and args.decision_command == "nominate":
            result = decision_nominate(
                database_path=args.database, event_id=args.event_id,
                context_type=args.context_type, context_id=args.context_id,
                physical_instance_id=args.physical_instance_id,
                canonical_scope=args.scope, owner=args.owner, reason=args.reason,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "decision" and args.decision_command in {"approve", "reject"}:
            operation = (
                decision_approve if args.decision_command == "approve" else decision_reject
            )
            result = operation(
                database_path=args.database, event_id=args.event_id,
                nomination_id=args.nomination_id,
                physical_instance_id=args.physical_instance_id,
                canonical_scope=args.scope, owner=args.owner, reason=args.reason,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "decision" and args.decision_command == "supersede":
            result = decision_supersede(
                database_path=args.database, event_id=args.event_id,
                nomination_id=args.nomination_id,
                prior_approval_id=args.prior_approval_id,
                physical_instance_id=args.physical_instance_id,
                canonical_scope=args.scope, owner=args.owner, reason=args.reason,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "decision" and args.decision_command == "abstain":
            result = decision_abstain(
                database_path=args.database, event_id=args.event_id,
                context_type=args.context_type, context_id=args.context_id,
                content_identity_id=args.content_identity_id,
                canonical_scope=args.scope, owner=args.owner, reason=args.reason,
                prior_approval_id=args.prior_approval_id,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "decision" and args.decision_command == "current":
            result = current_decisions(
                database_path=args.database, context_type=args.context_type,
                context_id=args.context_id, safety_policy=policy,
            )
            _show_structured({"current_decisions": result}, args.format)
            return 0
        if args.command == "decision" and args.decision_command == "history":
            result = decision_history(
                database_path=args.database, context_type=args.context_type,
                context_id=args.context_id, limit=args.limit, offset=args.offset,
                safety_policy=policy,
            )
            _show_structured({"decision_history": result}, args.format)
            return 0
        if args.command == "albums":
            common = {"database_path": args.database, "safety_policy": policy}
            if args.albums_command == "list":
                result = list_albums(
                    **common, include_archived=args.include_archived,
                    limit=args.limit, offset=args.offset,
                )
            elif args.albums_command == "create":
                result = create_album(
                    **common, name=args.name, description=args.description,
                    actor=args.actor, reason=args.reason, provenance=args.provenance,
                )
            elif args.albums_command == "show":
                result = get_album(**common, album_uuid=args.album_uuid)
            elif args.albums_command == "rename":
                result = rename_album(
                    **common, album_uuid=args.album_uuid, name=args.name,
                    actor=args.actor, reason=args.reason, provenance=args.provenance,
                )
            elif args.albums_command == "archive":
                result = archive_album(
                    **common, album_uuid=args.album_uuid, actor=args.actor,
                    reason=args.reason, provenance=args.provenance,
                )
            elif args.albums_command == "restore":
                result = restore_album(
                    **common, album_uuid=args.album_uuid, actor=args.actor,
                    reason=args.reason, provenance=args.provenance,
                )
            elif args.albums_command == "add-content":
                result = add_content_to_album(
                    **common, album_uuid=args.album_uuid,
                    content_identity_id=args.content_identity_id, actor=args.actor,
                    reason=args.reason, provenance=args.provenance,
                )
            elif args.albums_command == "remove-content":
                result = remove_content_from_album(
                    **common, album_uuid=args.album_uuid,
                    content_identity_id=args.content_identity_id, actor=args.actor,
                    reason=args.reason, provenance=args.provenance,
                )
            elif args.albums_command == "members":
                result = list_album_members(
                    **common, album_uuid=args.album_uuid,
                    include_removed=args.include_removed,
                    limit=args.limit, offset=args.offset,
                )
            elif args.albums_command == "for-content":
                result = list_albums_for_content(
                    **common, content_identity_id=args.content_identity_id,
                    include_removed=args.include_removed,
                )
            else:
                result = organisation_history(
                    **common, album_uuid=args.album_uuid,
                    content_identity_id=args.content_identity_id,
                    limit=args.limit, offset=args.offset,
                )
            _show_structured(result, args.format)
            return 0
        if args.command == "dates":
            common = {"database_path": args.database, "safety_policy": policy}
            if args.dates_command == "show":
                result = get_preferred_date(
                    **common, content_identity_id=args.content_identity_id
                )
            elif args.dates_command == "evidence":
                result = list_date_evidence(
                    **common, content_identity_id=args.content_identity_id,
                    limit=args.limit, offset=args.offset,
                )
            elif args.dates_command == "basis":
                result = list_preferred_basis(
                    **common, content_identity_id=args.content_identity_id
                )
            elif args.dates_command == "review-list":
                result = list_preferred_identities(
                    **common, status=PreferredStatus.NEEDS_REVIEW,
                    limit=args.limit, offset=args.offset,
                )
            elif args.dates_command == "unknown-list":
                result = list_preferred_identities(
                    **common, status=PreferredStatus.UNKNOWN,
                    limit=args.limit, offset=args.offset,
                )
            elif args.dates_command == "owner-list":
                result = list_owner_overrides(
                    **common, limit=args.limit, offset=args.offset
                )
            elif args.dates_command == "counts":
                result = preferred_date_counts(**common)
            elif args.dates_command == "run":
                result = run_date_evidence_pipeline(
                    **common, job_id=args.job_id, limit=args.limit,
                    after_physical_instance_id=args.after_physical_instance_id,
                )
            else:
                if not args.confirm_owner_date:
                    raise CatalogueError(
                        "Owner date action requires --confirm-owner-date."
                    )
                result = set_owner_preferred_date(
                    **common, content_identity_id=args.content_identity_id,
                    value=args.value, actor=args.actor, action_id=args.action_id,
                    reason=args.reason, provenance=args.provenance,
                )
            _show_structured(result, args.format)
            return 0
        if args.command == "collections":
            common = {"database_path": args.database, "safety_policy": policy}
            if args.collections_command == "list":
                result = list_collections(
                    **common, state=args.state, limit=args.limit, offset=args.offset
                )
            elif args.collections_command == "show":
                result = get_collection(
                    **common, collection_uuid=args.collection_uuid
                )
            elif args.collections_command == "members":
                result = list_collection_members(
                    **common, collection_uuid=args.collection_uuid,
                    include_removed=args.include_removed,
                    limit=args.limit, offset=args.offset,
                )
            elif args.collections_command == "history":
                result = collection_history(
                    **common, collection_uuid=args.collection_uuid,
                    limit=args.limit, offset=args.offset,
                )
            elif args.collections_command == "for-content":
                result = list_collections_for_content(
                    **common, content_identity_id=args.content_identity_id,
                    include_removed=args.include_removed,
                    limit=args.limit, offset=args.offset,
                )
            else:
                if not args.confirm_collection_action:
                    raise CatalogueError(
                        "Collection mutation requires --confirm-collection-action."
                    )
                mutation = {
                    "actor": args.actor, "action_id": args.action_id,
                    "reason": args.reason, "provenance": args.provenance,
                }
                if args.collections_command == "create":
                    result = create_collection(
                        **common, **mutation, name=args.name,
                        description=args.description,
                    )
                elif args.collections_command == "rename":
                    result = rename_collection(
                        **common, **mutation, collection_uuid=args.collection_uuid,
                        name=args.name,
                    )
                elif args.collections_command == "archive":
                    result = archive_collection(
                        **common, **mutation, collection_uuid=args.collection_uuid
                    )
                elif args.collections_command == "restore":
                    result = restore_collection(
                        **common, **mutation, collection_uuid=args.collection_uuid
                    )
                else:
                    operation = {
                        "add": add_content_to_collection,
                        "remove": remove_content_from_collection,
                        "restore-member": restore_content_to_collection,
                    }[args.collections_command]
                    result = operation(
                        **common, **mutation, collection_uuid=args.collection_uuid,
                        content_identity_id=args.content_identity_id,
                    )
            _show_structured(result, args.format)
            return 0
        if args.command == "plan" and args.plan_command == "create":
            result = create_plan(
                database_path=args.database, policy_id=args.policy,
                context_type=args.context_type, context_id=args.context_id,
                canonical_scope=args.scope, approval_event_id=args.approval_event_id,
                destination_root=args.destination_root, owner=args.owner,
                source_physical_instance_ids=args.source_instance_id,
                safety_margin_bytes=args.safety_margin_bytes, reason=args.reason,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "plan" and args.plan_command == "list":
            result = list_plans(
                database_path=args.database, status=args.status,
                limit=args.limit, offset=args.offset, safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "plan" and args.plan_command == "show":
            result = show_plan(
                database_path=args.database, plan_id=args.plan_id, safety_policy=policy
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "plan" and args.plan_command == "report":
            result = plan_report(
                database_path=args.database, plan_id=args.plan_id, safety_policy=policy
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "plan" and args.plan_command == "preflight":
            result = preflight_plan(
                database_path=args.database, plan_id=args.plan_id,
                actor=args.actor, safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "plan" and args.plan_command == "invalidate":
            result = invalidate_plan(
                database_path=args.database, plan_id=args.plan_id,
                event_id=args.event_id, owner=args.owner, reason=args.reason,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "quarantine" and args.quarantine_command == "execute":
            result = execute_quarantine(
                database_path=args.database, plan_id=args.plan_id, item_id=args.item_id,
                quarantine_root=args.quarantine_root, actor=args.actor,
                confirm_quarantine=args.confirm_quarantine, safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "quarantine" and args.quarantine_command == "status":
            result = quarantine_status(
                database_path=args.database, execution_id=args.execution_id,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "quarantine" and args.quarantine_command == "history":
            result = quarantine_history(
                database_path=args.database, plan_id=args.plan_id, item_id=args.item_id,
                limit=args.limit, offset=args.offset, safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "quarantine" and args.quarantine_command == "reconcile":
            result = reconcile_quarantine(
                database_path=args.database, execution_id=args.execution_id,
                actor=args.actor, safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
        if args.command == "quarantine" and args.quarantine_command == "restore":
            result = restore_quarantine(
                database_path=args.database, execution_id=args.execution_id,
                actor=args.actor, confirm_restore=args.confirm_restore,
                safety_policy=policy,
            )
            _show_structured(result, args.format)
            return 0
    except (CatalogueError, ConfigError) as exc:
        logger.error("command_error=%s", exc)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    logger.error("unhandled_command")
    return 2


def _doctor(config: AppConfig, policy: PathSafetyPolicy) -> int:
    python_ok = sys.version_info >= (3, 13)
    retired_probe = policy.check_path(r"Z:\_policy_probe", intent=PathIntent.READ)
    action_probe = assess_operation(OperationMode.ACTION, PathIntent.WRITE)
    checks = [
        (python_ok, "python", platform.python_version()),
        (True, "package", __version__),
        (True, "working-directory", str(Path.cwd())),
        (True, "configuration", config.source_file or "safe defaults; no file loaded"),
        (not retired_probe.allowed and retired_probe.code == "RETIRED_DRIVE", "retired-z-policy", retired_probe.code),
        (not action_probe.allowed, "action-mode", action_probe.code),
    ]
    for passed, name, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
    return 0 if all(passed for passed, _, _ in checks) else 1


def _show_config(config: AppConfig) -> None:
    for key, value in config.as_dict().items():
        print(f"{key}: {value if value is not None else '<not configured>'}")


def _check_path(args: argparse.Namespace, mode: OperationMode, policy: PathSafetyPolicy) -> int:
    intent = PathIntent(args.intent)
    path_result = policy.check_path(args.path, intent=intent, base_path=args.base)
    operation_result = assess_operation(mode, intent)
    overall_allowed = path_result.allowed and operation_result.allowed
    print(f"allowed: {str(overall_allowed).lower()}")
    print(f"path_allowed: {str(path_result.allowed).lower()}")
    print(f"path_code: {path_result.code}")
    print(f"operation_allowed: {str(operation_result.allowed).lower()}")
    print(f"operation_code: {operation_result.code}")
    print(f"intent: {intent.value}")
    print(f"raw_path: {path_result.raw_path}")
    print(f"assessed_path: {path_result.assessed_path or '<none>'}")
    print(f"reason: {path_result.reason}")
    return 0 if overall_allowed else 2


def _show_catalogue_status(status: CatalogueStatus) -> None:
    print(f"database: {status.database_path}")
    print(f"schema_version: {status.schema_version}")
    print(f"current_schema_version: {status.current_schema_version}")
    print(f"up_to_date: {str(status.up_to_date).lower()}")
    print(f"foreign_keys: {'enabled' if status.foreign_keys_enabled else 'disabled'}")
    print(f"tables: {len(status.tables)}")


def _show_pipeline_report(report) -> None:
    print(report.format_human())
    print(f"PIPELINE_JSON: {report.to_json()}")


def _show_structured(value: object, output_format: str) -> None:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if output_format == "human" else None,
    )
    encoding = sys.stdout.encoding or "utf-8"
    print(rendered.encode(encoding, errors="backslashreplace").decode(encoding))


if __name__ == "__main__":
    raise SystemExit(main())
