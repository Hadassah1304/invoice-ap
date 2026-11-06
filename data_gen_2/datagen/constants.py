"""Global constants and configuration values for dataset generation.

Reads contract defaults, and optionally overlays values from --pipeline-config.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

REFERENCE_DATE_STR = "2026-11-06"
REFERENCE_DATE = datetime.date(2026, 11, 6)

# Defaults from 00_CONTRACT.md section 2 & config.yaml
DEFAULT_CONSTANTS: Dict[str, Any] = {
    "REFERENCE_DATE": REFERENCE_DATE_STR,
    "near_dup_window_days": 7,
    "near_dup_amount_tolerance_pct": 0.0,
    "invoice_no_similarity_threshold": 0.92,
    "price_variance_line_pct": 2.0,
    "tolerance_auto_pct": 2.0,
    "tolerance_review_pct": 5.0,
    "rounding_tolerance": 1.00,
    "max_invoice_age_days": 90,
    "tier3_price_tolerance_pct": 5.0,
    "tier3_item_similarity_threshold": 0.88,
    "vendor_match_threshold": 0.90,
    "vendor_reject_threshold": 0.75,
    "tier2_min_score": 0.80,
    "tier2_min_margin": 0.15,
}

# Target scenario counts per family and per tag (02_PIPELINE_SCRIPTS.md section 8 V22)
TARGET_FAMILY_COUNTS: Dict[str, int] = {
    "R": 12,
    "B": 12,
    "I": 11,
    "N": 23,
}

# Target tags per family from 00_CONTRACT.md 7.4
FAMILY_TAGS: Dict[str, List[str]] = {
    "R": [
        "no_po_vendor_known",
        "no_po_no_vendor",
        "burger_clear_winner",
        "burger_tie",
        "po_typo",
        "po_other_vendor",
        "po_closed",
        "po_cancelled",
        "reworded_items",
    ],
    "B": [
        "split_1",
        "split_2",
        "split_3",
        "split_4",
        "split_qty_1",
        "split_qty_2",
        "tol_warn",
        "tol_review",
        "tol_reject",
        "extra_freight_line",
        "happy_partial_delivery",
    ],
    "I": [
        "dup_orig",
        "dup_resend_identical",
        "dup_exact",
        "dup_near_format",
        "dup_rescan",
        "dup_possible",
        "same_invno_other_vendor",
        "vendor_lookalike",
        "vendor_unapproved",
        "bank_changed",
        "currency_mismatch",
    ],
    "N": [
        "happy_explicit",
        "price_drift",
        "arith_mismatch",
        "missing_invno",
        "missing_date",
        "missing_total",
        "scan_blur_stamp",
        "credit_note",
        "future_dated",
        "stale",
        "date_before_po",
        "number_formats_indian",
        "number_formats_eu_ambiguous",
        "tax_embedded",
    ],
}

ALL_VALID_TAGS: set[str] = {tag for tags in FAMILY_TAGS.values() for tag in tags}

VALID_DECISIONS: set[str] = {"APPROVED", "REJECTED", "NEEDS_REVIEW"}

VALID_REASON_CODES: set[str] = {
    "OK",
    "APPROVED_WITH_NOTE",
    "MISSING_FIELDS",
    "LOW_CONFIDENCE_EXTRACTION",
    "GROUNDING_FAILED",
    "ARITHMETIC_MISMATCH",
    "DUPLICATE_EXACT",
    "DUPLICATE_POSSIBLE",
    "VENDOR_NOT_APPROVED",
    "VENDOR_UNCLEAR",
    "VENDOR_MISMATCH",
    "INVALID_PO_REF",
    "PO_CLOSED",
    "NO_MATCHING_PO",
    "AMBIGUOUS_PO",
    "INFERRED_MATCH",
    "OVERBILLED",
    "QTY_EXCEEDS_REMAINING",
    "PRICE_DRIFT",
    "CURRENCY_MISMATCH",
    "DATE_INVALID",
    "TAX_MISMATCH",
    "UNSUPPORTED_DOCUMENT_TYPE",
    "UNREADABLE_DOCUMENT",
}


class Config:
    def __init__(self, overrides: Optional[Dict[str, Any]] = None):
        self.values = dict(DEFAULT_CONSTANTS)
        if overrides:
            self.values.update(overrides)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    @classmethod
    def from_pipeline_config(cls, path: Optional[Path]) -> "Config":
        if not path or not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        overrides: Dict[str, Any] = {}
        # Mapping config.yaml keys to our constants
        dups = raw.get("duplicates", {})
        if "near_dup_window_days" in dups:
            overrides["near_dup_window_days"] = dups["near_dup_window_days"]
        if "near_dup_amount_tolerance_pct" in dups:
            overrides["near_dup_amount_tolerance_pct"] = float(dups["near_dup_amount_tolerance_pct"])
        if "invoice_no_similarity_threshold" in dups:
            overrides["invoice_no_similarity_threshold"] = float(dups["invoice_no_similarity_threshold"])

        val = raw.get("validation", {})
        if "price_variance_line_pct" in val:
            overrides["price_variance_line_pct"] = float(val["price_variance_line_pct"])
        if "tolerance_auto_pct" in val:
            overrides["tolerance_auto_pct"] = float(val["tolerance_auto_pct"])
        if "tolerance_review_pct" in val:
            overrides["tolerance_review_pct"] = float(val["tolerance_review_pct"])
        if "rounding_tolerance" in val:
            overrides["rounding_tolerance"] = float(val["rounding_tolerance"])
        if "max_invoice_age_days" in val:
            overrides["max_invoice_age_days"] = int(val["max_invoice_age_days"])

        vendor = raw.get("vendor", {})
        if "match_threshold" in vendor:
            overrides["vendor_match_threshold"] = float(vendor["match_threshold"])
        if "reject_threshold" in vendor:
            overrides["vendor_reject_threshold"] = float(vendor["reject_threshold"])

        matching = raw.get("matching", {})
        tier2 = matching.get("tier2", {})
        if "min_score" in tier2:
            overrides["tier2_min_score"] = float(tier2["min_score"])
        if "min_margin" in tier2:
            overrides["tier2_min_margin"] = float(tier2["min_margin"])

        tier3 = matching.get("tier3", {})
        if "price_tolerance_pct" in tier3:
            overrides["tier3_price_tolerance_pct"] = float(tier3["price_tolerance_pct"])
        if "item_similarity_threshold" in tier3:
            overrides["tier3_item_similarity_threshold"] = float(tier3["item_similarity_threshold"])

        return cls(overrides)
