from __future__ import annotations

import sqlite3
from typing import Optional, Tuple
from rapidfuzz import fuzz
from invoice_pipeline.config import DuplicatesConfig
from invoice_pipeline.models import ReasonCodeEnum
from invoice_pipeline.store.repositories import InvoiceRepo


def check_duplicates(
    repo: InvoiceRepo,
    vendor_id: Optional[str],
    invoice_no_raw: Optional[str],
    invoice_no_norm: Optional[str],
    invoice_date: Optional[str],
    grand_total: Optional[float],
    config: DuplicatesConfig,
    exclude_invoice_id: Optional[int] = None,
) -> Tuple[Optional[ReasonCodeEnum], Optional[str], Optional[dict]]:
    """
    Checks for exact and near duplicates against the ledger.
    Returns (reason_code, message, matched_ledger_row).
    """
    if not vendor_id:
        return None, None, None

    # 1. Exact match (same vendor + normalized invoice number)
    if invoice_no_norm:
        exact = repo.find_duplicate_exact(vendor_id, invoice_no_norm, exclude_invoice_id=exclude_invoice_id)
        if exact:
            msg = (
                f"Exact duplicate detected: Vendor {vendor_id} already has active invoice "
                f"#{exact['invoice_no_raw']} (ID {exact['invoice_id']}, status {exact['status']})"
            )
            return ReasonCodeEnum.DUPLICATE_EXACT, msg, exact

    # 2. Near duplicate (same vendor + same total within tolerance + date within window)
    if grand_total is not None and invoice_date:
        candidates = repo.find_near_duplicates(
            vendor_id=vendor_id,
            total=grand_total,
            invoice_date=invoice_date,
            window_days=config.near_dup_window_days,
            amount_tol_pct=config.near_dup_amount_tolerance_pct,
            exclude_invoice_id=exclude_invoice_id,
        )
        for c in candidates:
            # Check invoice number similarity
            sim = 0.0
            if invoice_no_raw and c.get("invoice_no_raw"):
                sim = fuzz.ratio(invoice_no_raw.upper(), c["invoice_no_raw"].upper()) / 100.0

            # If invoice number similarity is high, or both amount and date match exactly
            dates_match = str(c.get("invoice_date")) == str(invoice_date)
            amounts_match = abs(float(c.get("total", 0.0)) - grand_total) <= 0.01

            if sim >= config.invoice_no_similarity_threshold or (amounts_match and dates_match):
                msg = (
                    f"Possible near duplicate: matches ledger invoice #{c['invoice_no_raw']} "
                    f"(ID {c['invoice_id']}, total {c['total']}, date {c['invoice_date']})"
                )
                return ReasonCodeEnum.DUPLICATE_POSSIBLE, msg, c

    return None, None, None
