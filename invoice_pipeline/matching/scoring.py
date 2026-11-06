from __future__ import annotations

import datetime
from typing import Any, List, Optional
from invoice_pipeline.config import MatchingConfig
from invoice_pipeline.models import CandidateSignals, LineMatchDetail, POCandidate


def score_candidate_po(
    po: dict,
    po_items: List[dict],
    invoice_lines: List[Any],
    line_matches: List[LineMatchDetail],
    invoice_total: float,
    po_consumed_amount: float,
    invoice_date_str: Optional[str],
    config: MatchingConfig,
) -> POCandidate:
    """Computes candidate score in [0, 1] as a weighted sum of signals."""
    weights = config.weights
    po_items_by_id = {it["row_id"]: it for it in po_items}
    total_inv_lines = len(invoice_lines) if invoice_lines else 1

    # Signal 1: price (aligned with price_tolerance_pct)
    matched_count = 0
    price_ok_count = 0
    qty_ok_count = 0

    for lm in line_matches:
        if lm.po_item_row_id and lm.po_item_row_id in po_items_by_id:
            matched_count += 1
            po_it = po_items_by_id[lm.po_item_row_id]
            inv_l = next((l for l in invoice_lines if l.line_no == lm.invoice_line_no), None)
            if inv_l and float(po_it["unit_price"]) > 0:
                po_price = float(po_it["unit_price"])
                inv_price = float(inv_l.unit_price or 0.0)
                diff_pct = abs(inv_price - po_price) / po_price * 100.0
                if diff_pct <= config.tier3.price_tolerance_pct:
                    price_ok_count += 1
                elif diff_pct <= config.tier3.price_tolerance_pct * 2:
                    price_ok_count += 0.5  # partial credit

            if inv_l and inv_l.quantity is not None:
                if float(inv_l.quantity) <= float(po_it["qty_remaining"]) + 1e-4:
                    qty_ok_count += 1

    price_score = price_ok_count / max(1, matched_count) if matched_count > 0 else 0.0
    qty_score = qty_ok_count / max(1, matched_count) if matched_count > 0 else 0.0
    line_cov_score = matched_count / total_inv_lines

    # Signal 3: total_coverage
    po_total = float(po["total"])
    rem_balance = max(0.0, po_total - po_consumed_amount)
    if rem_balance > 0 and invoice_total > 0:
        if abs(invoice_total - rem_balance) < 1.0:
            total_cov_score = 1.0  # Exact match
        elif invoice_total < rem_balance:
            ratio = invoice_total / rem_balance
            total_cov_score = min(0.80, ratio)
        else:
            # Overbilled
            over = invoice_total - rem_balance
            total_cov_score = max(0.0, 0.5 - (over / rem_balance))
    else:
        total_cov_score = 0.0

    # Signal 5: date
    date_score = 0.5
    if invoice_date_str and po.get("po_date"):
        try:
            inv_d = datetime.date.fromisoformat(str(invoice_date_str))
            po_date_val = po["po_date"]
            if isinstance(po_date_val, datetime.date):
                po_d = po_date_val
            else:
                po_d = datetime.date.fromisoformat(str(po_date_val))
            days_diff = (inv_d - po_d).days
            terms = po.get("payment_terms_days") or 30
            if days_diff < 0:
                date_score = 0.0  # before PO date
            elif days_diff <= terms + 30:
                date_score = 1.0
            else:
                date_score = max(0.1, 1.0 - ((days_diff - (terms + 30)) / 90.0))
        except ValueError:
            date_score = 0.5

    signals = CandidateSignals(
        price=round(price_score, 4),
        quantity=round(qty_score, 4),
        total_coverage=round(total_cov_score, 4),
        line_coverage=round(line_cov_score, 4),
        date=round(date_score, 4),
    )

    final_score = (
        weights.price * signals.price
        + weights.quantity * signals.quantity
        + weights.total_coverage * signals.total_coverage
        + weights.line_coverage * signals.line_coverage
        + weights.date * signals.date
    )

    notes = []
    if price_score == 1.0 and matched_count > 0:
        notes.append("All matched unit prices align with PO")
    if total_cov_score == 1.0:
        notes.append("Invoice total exactly equals remaining PO balance")
    elif total_cov_score > 0:
        notes.append(f"Invoice consumes {int((invoice_total/max(1, rem_balance))*100)}% of remaining PO balance")
    if line_cov_score < 1.0:
        notes.append(f"Only {matched_count}/{total_inv_lines} invoice lines matched")

    return POCandidate(
        po_id=po["po_id"],
        score=round(final_score, 4),
        signals=signals,
        notes=notes,
        line_matches=line_matches,
    )
