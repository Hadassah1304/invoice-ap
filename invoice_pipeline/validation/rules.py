from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from invoice_pipeline.config import ValidationConfig
from invoice_pipeline.models import RuleResult, RuleStatusEnum, SeverityEnum
from invoice_pipeline.normalize.normalizers import parse_date


class ValidationContext:
    def __init__(
        self,
        config: ValidationConfig,
        extracted_invoice: Any,
        po_data: Optional[dict] = None,
        po_items: Optional[List[dict]] = None,
        consumed_balance: float = 0.0,
        vendor_data: Optional[dict] = None,
        line_matches: Optional[List[Any]] = None,
        as_of_date: Optional[datetime.date] = None,
    ) -> None:
        self.config = config
        self.inv = extracted_invoice
        self.po = po_data
        self.po_items = po_items or []
        self.consumed_balance = consumed_balance
        self.vendor = vendor_data
        self.line_matches = line_matches or []
        self.as_of_date = as_of_date or datetime.date.today()


def check_arithmetic(ctx: ValidationContext) -> RuleResult:
    """sum of line totals ≈ subtotal; subtotal + tax ≈ grand total."""
    rounding_tol = ctx.config.rounding_tolerance
    subtotal = ctx.inv.subtotal.value if ctx.inv.subtotal else None
    tax_total = ctx.inv.tax_total.value if ctx.inv.tax_total else 0.0
    grand_total = ctx.inv.grand_total.value if ctx.inv.grand_total else None

    lines = ctx.inv.line_items or []
    valid_line_totals = [l.line_total for l in lines if l.line_total is not None]
    lines_sum = sum(valid_line_totals) if valid_line_totals else None

    # Check 1: Lines sum vs subtotal (if both available)
    if lines_sum is not None and subtotal is not None:
        if abs(lines_sum - float(subtotal)) > rounding_tol:
            return RuleResult(
                rule="arithmetic",
                status=RuleStatusEnum.FLAG,
                severity=SeverityEnum.HARD,
                message=f"Line items total ({lines_sum:.2f}) does not match subtotal ({float(subtotal):.2f})",
                data={"lines_sum": lines_sum, "subtotal": float(subtotal), "tolerance": rounding_tol},
            )

    # Check 2: subtotal + tax ≈ grand total (if grand total available)
    if grand_total is not None:
        base = float(subtotal) if subtotal is not None else lines_sum
        if base is not None:
            expected = base + float(tax_total or 0.0)
            if abs(expected - float(grand_total)) > rounding_tol:
                return RuleResult(
                    rule="arithmetic",
                    status=RuleStatusEnum.FLAG,
                    severity=SeverityEnum.HARD,
                    message=f"Computed total ({expected:.2f}) does not match grand total ({float(grand_total):.2f})",
                    data={"computed_total": expected, "grand_total": float(grand_total), "diff": abs(expected - float(grand_total))},
                )

    return RuleResult(
        rule="arithmetic",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="Arithmetic checks passed",
    )


def check_line_price_variance(ctx: ValidationContext) -> RuleResult:
    """Check unit price drift per line vs matched PO lines."""
    if not ctx.po or not ctx.line_matches:
        return RuleResult(
            rule="line_price_variance",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No PO or matched lines to check price variance",
        )

    po_items_by_row = {it["row_id"]: it for it in ctx.po_items}
    drifted_lines = []
    tol_pct = ctx.config.price_variance_line_pct

    for lm in ctx.line_matches:
        if lm.po_item_row_id and lm.po_item_row_id in po_items_by_row:
            po_item = po_items_by_row[lm.po_item_row_id]
            po_price = float(po_item["unit_price"])
            inv_line = next((l for l in ctx.inv.line_items if l.line_no == lm.invoice_line_no), None)
            if inv_line and inv_line.unit_price is not None and po_price > 0:
                inv_price = float(inv_line.unit_price)
                pct_diff = ((inv_price - po_price) / po_price) * 100.0
                if pct_diff > tol_pct:
                    drifted_lines.append(
                        {
                            "line_no": inv_line.line_no,
                            "item": inv_line.description,
                            "invoiced_price": inv_price,
                            "po_price": po_price,
                            "pct_increase": round(pct_diff, 2),
                        }
                    )

    if drifted_lines:
        return RuleResult(
            rule="line_price_variance",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message=f"Price drift detected on {len(drifted_lines)} line(s) beyond {tol_pct}% tolerance",
            data={"drifted_lines": drifted_lines},
        )

    return RuleResult(
        rule="line_price_variance",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="All unit prices within tolerance",
    )


def check_line_quantity(ctx: ValidationContext) -> RuleResult:
    """Invoiced qty vs qty_remaining per PO line, preventing over-consumption across multiple lines."""
    if not ctx.po or not ctx.line_matches:
        return RuleResult(
            rule="line_quantity",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No PO lines to check quantity",
        )

    po_items_by_row = {it["row_id"]: it for it in ctx.po_items}
    claimed_by_po_item = {}

    for lm in ctx.line_matches:
        if lm.po_item_row_id and lm.po_item_row_id in po_items_by_row:
            inv_line = next((l for l in ctx.inv.line_items if l.line_no == lm.invoice_line_no), None)
            if inv_line and inv_line.quantity is not None:
                claimed_by_po_item[lm.po_item_row_id] = claimed_by_po_item.get(lm.po_item_row_id, 0.0) + float(inv_line.quantity)

    over_qty_lines = []
    for row_id, claimed_qty in claimed_by_po_item.items():
        po_item = po_items_by_row[row_id]
        rem_qty = float(po_item["qty_remaining"])
        if claimed_qty > rem_qty + 1e-4:
            over_qty_lines.append(
                {
                    "item_name": po_item["item_name"],
                    "claimed_qty": claimed_qty,
                    "qty_remaining": rem_qty,
                }
            )

    if over_qty_lines:
        is_reject = ctx.config.qty_over_remaining_policy == "reject"
        return RuleResult(
            rule="line_quantity",
            status=RuleStatusEnum.FAIL if is_reject else RuleStatusEnum.FLAG,
            severity=SeverityEnum.HARD,
            message=f"Invoiced quantity exceeds remaining PO balance on {len(over_qty_lines)} item(s)",
            data={"over_qty_lines": over_qty_lines},
        )

    return RuleResult(
        rule="line_quantity",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="Quantities within remaining limits",
    )


def check_extra_or_missing_lines(ctx: ValidationContext) -> RuleResult:
    """Detect invoice lines not matched on the PO, and record absent PO lines as INFO."""
    if not ctx.po or not ctx.line_matches:
        return RuleResult(
            rule="extra_or_missing_lines",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No PO comparison available",
        )

    allowed_keywords = [w.lower() for w in ctx.config.allow_extra_lines]
    unmatched = []
    allowed_extras = []

    for l in ctx.inv.line_items:
        lm = next((m for m in ctx.line_matches if m.invoice_line_no == l.line_no), None)
        if not lm or not lm.po_item_row_id:
            desc_lower = l.description.lower()
            if any(k in desc_lower for k in allowed_keywords):
                allowed_extras.append(l.description)
            else:
                unmatched.append({"line_no": l.line_no, "description": l.description})

    # Absent PO lines (partial delivery indicator)
    matched_po_item_ids = {m.po_item_row_id for m in ctx.line_matches if m.po_item_row_id}
    absent_po_lines = [it["item_name"] for it in ctx.po_items if it["row_id"] not in matched_po_item_ids]

    if unmatched:
        return RuleResult(
            rule="extra_or_missing_lines",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message=f"Found {len(unmatched)} unexpected line(s) not present on PO",
            data={"unmatched_lines": unmatched, "allowed_extras": allowed_extras, "absent_po_lines": absent_po_lines},
        )

    if allowed_extras:
        return RuleResult(
            rule="extra_or_missing_lines",
            status=RuleStatusEnum.WARN,
            severity=SeverityEnum.INFO,
            message=f"Contains allowable additional line(s): {', '.join(allowed_extras)}",
            data={"allowed_extras": allowed_extras, "absent_po_lines": absent_po_lines},
        )

    return RuleResult(
        rule="extra_or_missing_lines",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="All invoice lines match PO items" + (f" (partial delivery: {len(absent_po_lines)} PO items unbilled)" if absent_po_lines else ""),
        data={"absent_po_lines": absent_po_lines},
    )


def check_balance_tolerance(ctx: ValidationContext) -> RuleResult:
    """PO remaining balance check and overage tolerance."""
    if not ctx.po:
        return RuleResult(
            rule="balance_tolerance",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No PO to check balance",
        )

    po_total = float(ctx.po["total"])
    remaining = max(0.0, po_total - ctx.consumed_balance)
    inv_total = float(ctx.inv.grand_total.value or 0.0)

    if remaining <= 0:
        return RuleResult(
            rule="balance_tolerance",
            status=RuleStatusEnum.FAIL,
            severity=SeverityEnum.HARD,
            message="PO has zero remaining balance",
            data={"po_total": po_total, "consumed": ctx.consumed_balance, "inv_total": inv_total},
        )

    overage = inv_total - remaining
    variance_pct = (overage / remaining) * 100.0 if overage > 0 else 0.0

    if variance_pct > ctx.config.tolerance_review_pct:
        return RuleResult(
            rule="balance_tolerance",
            status=RuleStatusEnum.FAIL,
            severity=SeverityEnum.HARD,
            message=f"Invoice total exceeds PO remaining balance by {variance_pct:.2f}% (max review limit {ctx.config.tolerance_review_pct}%)",
            data={"variance_pct": round(variance_pct, 2), "remaining": remaining, "invoice_total": inv_total},
        )
    elif variance_pct > ctx.config.tolerance_auto_pct:
        return RuleResult(
            rule="balance_tolerance",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message=f"Invoice total exceeds PO remaining balance by {variance_pct:.2f}% (requires review)",
            data={"variance_pct": round(variance_pct, 2), "remaining": remaining, "invoice_total": inv_total},
        )
    elif variance_pct > 0.0:
        return RuleResult(
            rule="balance_tolerance",
            status=RuleStatusEnum.WARN,
            severity=SeverityEnum.INFO,
            message=f"Invoice total exceeds PO balance slightly by {variance_pct:.2f}% (within auto-tolerance of {ctx.config.tolerance_auto_pct}%)",
            data={"variance_pct": round(variance_pct, 2), "remaining": remaining, "invoice_total": inv_total},
        )

    return RuleResult(
        rule="balance_tolerance",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message=f"Invoice total ({inv_total:.2f}) fits within remaining PO balance ({remaining:.2f})",
        data={"remaining": remaining, "invoice_total": inv_total},
    )


def check_currency_match(ctx: ValidationContext) -> RuleResult:
    if not ctx.po:
        return RuleResult(
            rule="currency_match",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No PO to compare currency",
        )

    inv_curr = str(ctx.inv.currency.value or "INR").upper()
    po_curr = str(ctx.po.get("currency") or "INR").upper()
    if inv_curr != po_curr:
        return RuleResult(
            rule="currency_match",
            status=RuleStatusEnum.FAIL,
            severity=SeverityEnum.HARD,
            message=f"Currency mismatch: invoice is {inv_curr}, PO is {po_curr}",
            data={"invoice_currency": inv_curr, "po_currency": po_curr},
        )

    return RuleResult(
        rule="currency_match",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message=f"Currency matches ({inv_curr})",
    )


def check_date_sanity(ctx: ValidationContext) -> RuleResult:
    inv_date_str = ctx.inv.invoice_date.value if ctx.inv.invoice_date else None
    if not inv_date_str:
        return RuleResult(
            rule="date_sanity",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="Invoice date missing",
        )

    try:
        inv_date = datetime.date.fromisoformat(str(inv_date_str))
    except ValueError:
        iso_str, _ = parse_date(str(inv_date_str))
        if iso_str:
            inv_date = datetime.date.fromisoformat(iso_str)
        else:
            return RuleResult(
                rule="date_sanity",
                status=RuleStatusEnum.FLAG,
                severity=SeverityEnum.SOFT,
                message=f"Invalid date format: {inv_date_str}",
            )

    # Use injectable as_of_date
    today = ctx.as_of_date
    if not ctx.config.allow_future_dated and inv_date > today:
        return RuleResult(
            rule="date_sanity",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message=f"Invoice date {inv_date_str} is in the future",
        )

    age_days = (today - inv_date).days
    if age_days > ctx.config.max_invoice_age_days:
        return RuleResult(
            rule="date_sanity",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message=f"Invoice is {age_days} days old (exceeds max {ctx.config.max_invoice_age_days} days)",
        )

    if ctx.po and ctx.po.get("po_date"):
        try:
            po_date_val = ctx.po["po_date"]
            if isinstance(po_date_val, datetime.date):
                po_date = po_date_val
            else:
                try:
                    po_date = datetime.date.fromisoformat(str(po_date_val))
                except ValueError:
                    po_iso, _ = parse_date(str(po_date_val))
                    po_date = datetime.date.fromisoformat(po_iso) if po_iso else None
            if po_date and inv_date < po_date:
                return RuleResult(
                    rule="date_sanity",
                    status=RuleStatusEnum.FLAG,
                    severity=SeverityEnum.SOFT,
                    message=f"Invoice date ({inv_date_str}) is before PO date ({po_date})",
                )
        except Exception:
            pass

    return RuleResult(
        rule="date_sanity",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="Invoice date is valid and within acceptable window",
    )


def check_tax(ctx: ValidationContext) -> RuleResult:
    plausible = ctx.config.tax_rates_plausible
    warnings = []
    po_items_by_row = {it["row_id"]: it for it in ctx.po_items}

    for l in ctx.inv.line_items:
        if l.tax_rate is not None and l.tax_rate not in plausible:
            warnings.append(f"Line {l.line_no} has unusual tax rate {l.tax_rate}%")

        # Compare against PO item tax_rate if available
        lm = next((m for m in ctx.line_matches if m.invoice_line_no == l.line_no), None)
        if lm and lm.po_item_row_id and lm.po_item_row_id in po_items_by_row:
            po_item = po_items_by_row[lm.po_item_row_id]
            po_tax = po_item.get("tax_rate")
            if po_tax is not None and l.tax_rate is not None and abs(float(po_tax) - float(l.tax_rate)) > 0.01:
                warnings.append(f"Line {l.line_no} tax rate {l.tax_rate}% differs from PO tax rate {po_tax}%")

    if warnings:
        return RuleResult(
            rule="tax_check",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message="; ".join(warnings),
        )

    return RuleResult(
        rule="tax_check",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="Tax rates plausible and consistent with PO",
    )


def check_uom(ctx: ValidationContext) -> RuleResult:
    """Checks Unit of Measure (UOM) consistency between invoice lines and PO lines."""
    if not ctx.po or not ctx.line_matches:
        return RuleResult(
            rule="uom_check",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No PO items to compare UOM",
        )

    po_items_by_row = {it["row_id"]: it for it in ctx.po_items}
    mismatches = []

    for lm in ctx.line_matches:
        if lm.po_item_row_id and lm.po_item_row_id in po_items_by_row:
            po_item = po_items_by_row[lm.po_item_row_id]
            inv_line = next((l for l in ctx.inv.line_items if l.line_no == lm.invoice_line_no), None)
            if inv_line and inv_line.uom and po_item.get("uom"):
                inv_uom = inv_line.uom.strip().lower()
                po_uom = po_item["uom"].strip().lower()
                if inv_uom != po_uom:
                    mismatches.append(f"Line {inv_line.line_no}: invoice UOM '{inv_uom}' vs PO UOM '{po_uom}'")

    if mismatches:
        return RuleResult(
            rule="uom_check",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message="; ".join(mismatches),
            data={"mismatches": mismatches},
        )

    return RuleResult(
        rule="uom_check",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="UOM matches PO specifications",
    )


def check_confidence(ctx: ValidationContext) -> RuleResult:
    """Flags low confidence extraction on critical fields."""
    crit_fields = [
        ("invoice_number", ctx.inv.invoice_number.confidence),
        ("invoice_date", ctx.inv.invoice_date.confidence),
        ("grand_total", ctx.inv.grand_total.confidence),
    ]
    if ctx.inv.po_reference and ctx.inv.po_reference.value:
        crit_fields.append(("po_reference", ctx.inv.po_reference.confidence))

    low = [(f, c) for f, c in crit_fields if c < 0.75]
    if low:
        msg = f"Low extraction confidence on critical field(s): {', '.join(f'{f} ({c:.2f})' for f, c in low)}"
        return RuleResult(
            rule="confidence_check",
            status=RuleStatusEnum.FLAG,
            severity=SeverityEnum.SOFT,
            message=msg,
        )

    return RuleResult(
        rule="confidence_check",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="Extraction confidence on critical fields is acceptable",
    )


def check_vendor_bank(ctx: ValidationContext) -> RuleResult:
    if not ctx.vendor or not ctx.vendor.get("bank_account"):
        return RuleResult(
            rule="vendor_bank_check",
            status=RuleStatusEnum.SKIPPED,
            severity=SeverityEnum.INFO,
            message="No master bank account stored for vendor",
        )

    extracted_bank = ctx.inv.vendor.bank_account
    if extracted_bank:
        stored = ctx.vendor["bank_account"].strip()
        clean_ext = "".join(c for c in extracted_bank if c.isalnum())
        clean_stored = "".join(c for c in stored if c.isalnum())
        if clean_ext and clean_stored and clean_ext != clean_stored:
            return RuleResult(
                rule="vendor_bank_check",
                status=RuleStatusEnum.FLAG,
                severity=SeverityEnum.SOFT,
                message=f"Bank account mismatch (fraud signal): extracted {extracted_bank} vs stored {stored}",
            )

    return RuleResult(
        rule="vendor_bank_check",
        status=RuleStatusEnum.PASS,
        severity=SeverityEnum.INFO,
        message="Bank account verified or not provided on document",
    )


ALL_RULES = [
    check_arithmetic,
    check_currency_match,
    check_date_sanity,
    check_balance_tolerance,
    check_line_price_variance,
    check_line_quantity,
    check_extra_or_missing_lines,
    check_tax,
    check_uom,
    check_confidence,
    check_vendor_bank,
]
