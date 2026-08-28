"""Reproducible, read-only-against-media inventory and SHA-256 pipeline."""

from personal_librarian.pipeline.exact_duplicates import derive_exact_duplicates
from personal_librarian.pipeline.date_evidence import run_date_evidence_pipeline
from personal_librarian.pipeline.hashing import run_sha256
from personal_librarian.pipeline.inventory import run_inventory
from personal_librarian.pipeline.near_duplicate_reconciliation import reconcile_m11_baseline
from personal_librarian.pipeline.perceptual_hashing import run_perceptual_hashing
from personal_librarian.pipeline.reconciliation import reconcile_historical_baseline
from personal_librarian.pipeline.similarity import run_similarity_analysis
from personal_librarian.pipeline.similarity_groups import run_similarity_groups

__all__ = [
    "derive_exact_duplicates",
    "run_date_evidence_pipeline",
    "reconcile_m11_baseline",
    "reconcile_historical_baseline",
    "run_inventory",
    "run_perceptual_hashing",
    "run_sha256",
    "run_similarity_analysis",
    "run_similarity_groups",
]
