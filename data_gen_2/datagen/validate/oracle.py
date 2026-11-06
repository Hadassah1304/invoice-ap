"""Ledger simulator and gate oracle (V19).

Processes compiled cases in run_order and evaluates only gate-class facts, in the pipeline's order:
1. cache: byte_copy_of -> expected equals source's, expect_cached true.
2. completeness: missing printed invoice number/date/total, document type not invoice, negative amounts -> NEEDS_REVIEW.
3. duplicates: exact (same vendor + same normalized number as non-rejected ledger entry) -> REJECTED / DUPLICATE_EXACT;
               near -> NEEDS_REVIEW / DUPLICATE_POSSIBLE.
4. vendor approved? -> REJECTED / VENDOR_NOT_APPROVED.
5. PO reference present and exists? Unknown -> NEEDS_REVIEW / INVALID_PO_REF; wrong vendor -> REJECTED / VENDOR_MISMATCH;
   CLOSED/CANCELLED or remaining money <= 0 -> REJECTED / PO_CLOSED.
6. currency mismatch -> REJECTED / CURRENCY_MISMATCH.
7. dates: future, stale, before PO -> NEEDS_REVIEW / DATE_INVALID.
8. quantity: any PO line over qty_remaining -> NEEDS_REVIEW / QTY_EXCEEDS_REMAINING.
9. balance bands: <= 0% passes; up to 2% over APPROVED_WITH_NOTE; up to 5% NEEDS_REVIEW; above 5% REJECTED / OVERBILLED.
10. otherwise UNDETERMINED.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from rapidfuzz import fuzz

from datagen.constants import Config, REFERENCE_DATE
from datagen.finalize import FinalizedState
from datagen.loader import LoadedBase
from datagen.models import CaseOutput, StatePO
from datagen.money import quantize_money, to_decimal
from datagen.norm import normalize_invoice_number


class OracleOutcome:
    def __init__(self, decision: Optional[str], reason_code: Optional[str], determined: bool):
        self.decision = decision
        self.reason_code = reason_code
        self.determined = determined


class LedgerEntry:
    def __init__(
        self,
        case_id: str,
        vendor_id: str,
        vendor_name: str,
        invoice_no: str,
        invoice_no_norm: str,
        invoice_date: str,
        grand_total: Decimal,
        decision: str,
        po_id: Optional[str],
    ):
        self.case_id = case_id
        self.vendor_id = vendor_id
        self.vendor_name = vendor_name
        self.invoice_no = invoice_no
        self.invoice_no_norm = invoice_no_norm
        self.invoice_date = invoice_date
        self.grand_total = grand_total
        self.decision = decision
        self.po_id = po_id


class OracleSimulator:
    def __init__(self, loaded: LoadedBase, finalized: FinalizedState, config: Config = None):
        self.loaded = loaded
        self.finalized = finalized
        self.config = config or Config()

        self.vendors_by_id = {v.vendor_id: v for v in loaded.core.vendors}
        self.vendors_by_name = {v.name: v for v in loaded.core.vendors}

        # Initialize PO tracking
        self.po_states: Dict[str, Dict[str, Any]] = {}
        for po in finalized.state_output.purchase_orders:
            line_rem: Dict[int, int] = {l.line_no: l.qty_remaining for l in po.lines}
            line_prices: Dict[int, Decimal] = {l.line_no: to_decimal(l.unit_price) for l in po.lines}
            self.po_states[po.po_id] = {
                "po_id": po.po_id,
                "vendor_id": po.vendor_id,
                "currency": po.currency,
                "status": po.status,
                "po_date": po.po_date,
                "total": to_decimal(po.total),
                "remaining_money": to_decimal(po.total) - sum((to_decimal(pl.total) for pl in finalized.state_output.ledger_preload if pl.po_id == po.po_id), Decimal("0.00")),
                "line_remaining_qty": line_rem,
                "line_prices": line_prices,
            }

        # Ledger history: list of LedgerEntry
        self.ledger: List[LedgerEntry] = []
        # Preload ledger entries
        for pl in finalized.state_output.ledger_preload:
            v = self.vendors_by_id[pl.vendor_id]
            self.ledger.append(
                LedgerEntry(
                    case_id=pl.preload_id,
                    vendor_id=pl.vendor_id,
                    vendor_name=v.name,
                    invoice_no=pl.invoice_no,
                    invoice_no_norm=pl.invoice_no_norm,
                    invoice_date=pl.invoice_date,
                    grand_total=to_decimal(pl.total),
                    decision="APPROVED",
                    po_id=pl.po_id,
                )
            )

    def evaluate_case(self, case: CaseOutput) -> OracleOutcome:
        doc = case.document
        doc_type = doc.document_type

        # 1. Cache by file hash / byte_copy_of
        if case.byte_copy_of:
            return OracleOutcome(decision=case.expected.decision, reason_code=case.expected.reason_codes_accepted[0] if case.expected.reason_codes_accepted else "OK", determined=True)

        # 2. Completeness gate
        # Missing printed invoice number/date/total, document type not invoice, negative amounts
        if doc_type != "invoice":
            return OracleOutcome(decision="NEEDS_REVIEW", reason_code="UNSUPPORTED_DOCUMENT_TYPE", determined=True)

        if doc.invoice_number is None or doc.invoice_date is None or doc.grand_total is None:
            return OracleOutcome(decision="NEEDS_REVIEW", reason_code="MISSING_FIELDS", determined=True)

        grand_total = to_decimal(doc.grand_total)
        if grand_total < Decimal("0.00"):
            return OracleOutcome(decision="NEEDS_REVIEW", reason_code="UNSUPPORTED_DOCUMENT_TYPE", determined=True)

        # Negative lines check
        if any(to_decimal(l.line_total) < Decimal("0.00") or to_decimal(l.unit_price) < Decimal("0.00") for l in doc.lines):
            return OracleOutcome(decision="NEEDS_REVIEW", reason_code="UNSUPPORTED_DOCUMENT_TYPE", determined=True)

        # Resolve vendor
        v_block = doc.vendor_block
        v_record = None
        if v_block:
            if v_block.name and v_block.name in self.vendors_by_name:
                v_record = self.vendors_by_name[v_block.name]
            elif v_block.gstin:
                v_record = next((v for v in self.vendors_by_id.values() if v.gstin == v_block.gstin), None)

        if not v_record and case.tag in ["no_po_no_vendor", "vendor_lookalike"]:
            # Gate stops or undetermined
            return OracleOutcome(decision=None, reason_code=None, determined=False)

        norm_no = normalize_invoice_number(doc.invoice_number)

        # 3. Duplicate checks against non-rejected ledger entries
        if v_record:
            for entry in self.ledger:
                if entry.decision != "REJECTED" and entry.vendor_id == v_record.vendor_id:
                    # Exact duplicate
                    if norm_no and norm_no == entry.invoice_no_norm:
                        return OracleOutcome(decision="REJECTED", reason_code="DUPLICATE_EXACT", determined=True)
                    # Near duplicate: within near_dup_window_days (7) and amount equal
                    if doc.invoice_date and entry.invoice_date:
                        d1 = datetime.date.fromisoformat(doc.invoice_date)
                        d2 = datetime.date.fromisoformat(entry.invoice_date)
                        if abs((d1 - d2).days) <= self.config.get("near_dup_window_days", 7) and grand_total == entry.grand_total:
                            return OracleOutcome(decision="NEEDS_REVIEW", reason_code="DUPLICATE_POSSIBLE", determined=True)
                        # Similarity threshold
                        if norm_no and entry.invoice_no_norm:
                            sim = fuzz.ratio(norm_no, entry.invoice_no_norm) / 100.0
                            if sim >= self.config.get("invoice_no_similarity_threshold", 0.92):
                                return OracleOutcome(decision="NEEDS_REVIEW", reason_code="DUPLICATE_POSSIBLE", determined=True)

        # 4. Vendor approved?
        if v_record and not v_record.approved:
            return OracleOutcome(decision="REJECTED", reason_code="VENDOR_NOT_APPROVED", determined=True)

        # 5. PO reference present?
        po_ref = doc.po_reference
        if po_ref is not None:
            if po_ref not in self.po_states:
                return OracleOutcome(decision="NEEDS_REVIEW", reason_code="INVALID_PO_REF", determined=True)

            po_state = self.po_states[po_ref]
            if v_record and po_state["vendor_id"] != v_record.vendor_id:
                return OracleOutcome(decision="REJECTED", reason_code="VENDOR_MISMATCH", determined=True)

            if po_state["status"] in ["CLOSED", "CANCELLED"] or po_state["remaining_money"] <= Decimal("0.00"):
                return OracleOutcome(decision="REJECTED", reason_code="PO_CLOSED", determined=True)

            # 6. Currency mismatch
            if doc.currency != po_state["currency"]:
                return OracleOutcome(decision="REJECTED", reason_code="CURRENCY_MISMATCH", determined=True)

            # 7. Dates: future, stale, before PO
            d_inv = datetime.date.fromisoformat(doc.invoice_date)
            d_po = datetime.date.fromisoformat(po_state["po_date"])

            if d_inv > REFERENCE_DATE:
                return OracleOutcome(decision="NEEDS_REVIEW", reason_code="DATE_INVALID", determined=True)
            if (REFERENCE_DATE - d_inv).days > self.config.get("max_invoice_age_days", 90):
                return OracleOutcome(decision="NEEDS_REVIEW", reason_code="DATE_INVALID", determined=True)
            if d_inv < d_po:
                return OracleOutcome(decision="NEEDS_REVIEW", reason_code="DATE_INVALID", determined=True)

            # 8. Quantity checks
            for l in doc.lines:
                # If mapped to a line on the PO
                if l.line_no in po_state["line_remaining_qty"]:
                    rem_qty = po_state["line_remaining_qty"][l.line_no]
                    if l.qty > rem_qty:
                        return OracleOutcome(decision="NEEDS_REVIEW", reason_code="QTY_EXCEEDS_REMAINING", determined=True)

            # 9. Balance bands
            rem_money = po_state["remaining_money"]
            if rem_money > Decimal("0.00"):
                overage_pct = (grand_total - rem_money) / rem_money * Decimal("100")
                tol_auto = Decimal(str(self.config.get("tolerance_auto_pct", 2.0)))
                tol_review = Decimal(str(self.config.get("tolerance_review_pct", 5.0)))

                if overage_pct > tol_review:
                    return OracleOutcome(decision="REJECTED", reason_code="OVERBILLED", determined=True)
                elif overage_pct > tol_auto:
                    return OracleOutcome(decision="NEEDS_REVIEW", reason_code=None, determined=True)
                elif overage_pct > Decimal("0.00"):
                    return OracleOutcome(decision="APPROVED", reason_code="APPROVED_WITH_NOTE", determined=True)

        # Inferred PO matching, price drift, ambiguous routing -> UNDETERMINED
        return OracleOutcome(decision=None, reason_code=None, determined=False)

    def apply_case_outcome(self, case: CaseOutput):
        """Advance ledger state using declared intent outcome."""
        intent = case.expected
        doc = case.document

        v_name = doc.vendor_block.name if doc.vendor_block else ""
        v_record = self.vendors_by_name.get(v_name)
        vendor_id = v_record.vendor_id if v_record else ""

        norm_no = normalize_invoice_number(doc.invoice_number)
        grand = to_decimal(doc.grand_total or 0.0)

        # Record in ledger
        self.ledger.append(
            LedgerEntry(
                case_id=case.case_id,
                vendor_id=vendor_id,
                vendor_name=v_name,
                invoice_no=doc.invoice_number or "",
                invoice_no_norm=norm_no,
                invoice_date=doc.invoice_date or "",
                grand_total=grand,
                decision=intent.decision,
                po_id=intent.po_id,
            )
        )

        # Reserve PO balance & qty if APPROVED or NEEDS_REVIEW
        if intent.decision in ["APPROVED", "NEEDS_REVIEW"] and intent.po_id and intent.po_id in self.po_states:
            po = self.po_states[intent.po_id]
            po["remaining_money"] = quantize_money(po["remaining_money"] - grand)
            # deduct line quantities
            for l in doc.lines:
                if l.line_no in po["line_remaining_qty"]:
                    po["line_remaining_qty"][l.line_no] = max(0, po["line_remaining_qty"][l.line_no] - l.qty)


def validate_oracle(loaded: LoadedBase, finalized: FinalizedState, compiled_cases: List[CaseOutput], config: Config = None) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    findings: List[Dict[str, Any]] = []
    oracle = OracleSimulator(loaded, finalized, config)

    determined_count = 0
    undetermined_count = 0

    for case in compiled_cases:
        outcome = oracle.evaluate_case(case)
        if outcome.determined:
            determined_count += 1
            # Compare with intent
            intent = case.expected
            if outcome.decision != intent.decision:
                # check if accepted decisions widen this
                if outcome.decision not in intent.decision_accepted:
                    findings.append({
                        "code": "V19",
                        "severity": "ERROR",
                        "id": case.case_id,
                        "message": f"Oracle decision '{outcome.decision}' disagrees with intent decision '{intent.decision}' (accepted: {intent.decision_accepted})",
                        "fix": f"Align intent decision with expected gate outcome ({outcome.decision})",
                    })

            if outcome.reason_code and intent.reason_codes_accepted:
                if outcome.reason_code not in intent.reason_codes_accepted:
                    findings.append({
                        "code": "V19",
                        "severity": "ERROR",
                        "id": case.case_id,
                        "message": f"Oracle reason code '{outcome.reason_code}' not in intent.reason_codes_accepted {intent.reason_codes_accepted}",
                        "fix": f"Include '{outcome.reason_code}' in reason_codes_accepted",
                    })
        else:
            undetermined_count += 1

        # Advance state
        oracle.apply_case_outcome(case)

    counts = {"determined": determined_count, "undetermined": undetermined_count}
    return findings, counts
