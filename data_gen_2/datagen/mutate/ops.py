"""All mutation operations registered into registry.

Covers:
none, drop_po_ref, drop_vendor_block, po_typo, swap_po_ref, add_extra_line,
price_drift, arith_break, reword_descriptions, missing_field, lookalike_vendor,
change_bank, change_currency, make_credit_note, shift_date, reformat,
embed_tax, renumber_format, rerender, resend_identical, new_number_same_amount
"""

from __future__ import annotations

import copy
import datetime
from decimal import Decimal
import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from datagen.constants import REFERENCE_DATE
from datagen.loader import resolve_offset_date
from datagen.models import (
    Document,
    DocumentLine,
    DocumentOmit,
    DocumentFlags,
    VendorBlock,
)
from datagen.money import (
    compute_line_tax,
    compute_line_total,
    compute_totals,
    quantize_money,
    to_decimal,
)
from datagen.mutate.drift import compute_drifted_lines
from datagen.mutate.namegen import generate_lookalike_name
from datagen.mutate.registry import (
    DerivedExpectation,
    Mutation,
    MutationContext,
    registry,
)
from datagen.norm import normalize_invoice_number


# --- 1. none ---
class EmptyParams(BaseModel):
    pass


class NoneMutation(Mutation):
    name = "none"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        return doc.model_copy(deep=True)


# --- 2. drop_po_ref ---
class DropPORefMutation(Mutation):
    name = "drop_po_ref"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.po_reference = None
        return new_doc


# --- 3. drop_vendor_block ---
class DropVendorBlockParams(BaseModel):
    keep: Optional[Literal["none", "name"]] = "none"
    also_drop_po_ref: bool = False


class DropVendorBlockMutation(Mutation):
    name = "drop_vendor_block"
    params_model = DropVendorBlockParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        keep = params.get("keep", "none")
        if keep == "name" and new_doc.vendor_block:
            new_doc.vendor_block = VendorBlock(name=new_doc.vendor_block.name)
        else:
            new_doc.vendor_block = None

        if params.get("also_drop_po_ref", False):
            new_doc.po_reference = None
        return new_doc


# --- 4. po_typo ---
DIGIT_TO_LETTER = {
    "0": "O",
    "1": "I",
    "5": "S",
    "8": "B",
}


class POTypoMutation(Mutation):
    name = "po_typo"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if not doc.po_reference:
            return ["po_typo requires po_reference to be present"]
        # Find rightmost eligible digit
        s = doc.po_reference
        for ch in reversed(s):
            if ch in DIGIT_TO_LETTER:
                return []
        return [f"po_reference '{doc.po_reference}' has no eligible digit (0, 1, 5, 8) for po_typo"]

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        s = list(new_doc.po_reference)
        # replace rightmost eligible digit
        for idx in range(len(s) - 1, -1, -1):
            if s[idx] in DIGIT_TO_LETTER:
                s[idx] = DIGIT_TO_LETTER[s[idx]]
                break
        new_po_ref = "".join(s)
        if new_po_ref in ctx.pos_by_id:
            raise ValueError(f"po_typo mutated po_ref '{new_po_ref}' collisions with an existing PO id")
        new_doc.po_reference = new_po_ref
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="INVALID_PO_REF")


# --- 5. swap_po_ref ---
class SwapPORefParams(BaseModel):
    target_po_id: str


class SwapPORefMutation(Mutation):
    name = "swap_po_ref"
    params_model = SwapPORefParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        target_po_id = params.get("target_po_id")
        if not target_po_id:
            return ["swap_po_ref requires target_po_id param"]
        if target_po_id not in ctx.pos_by_id:
            return [f"target_po_id '{target_po_id}' not found in POs"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.po_reference = params["target_po_id"]
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        target_po = ctx.pos_by_id[params["target_po_id"]]
        orig_vendor_id = ctx.scenario.invoice.vendor_id if ctx.scenario.invoice else None
        if target_po.vendor_id != orig_vendor_id:
            return DerivedExpectation(decision="REJECTED", reason_code="VENDOR_MISMATCH")
        return None


# --- 6. add_extra_line ---
class AddExtraLineParams(BaseModel):
    kind: Literal["freight"] = "freight"
    pct_of_total: Optional[float] = None
    amount: Optional[Union[float, Decimal]] = None


class AddExtraLineMutation(Mutation):
    name = "add_extra_line"
    params_model = AddExtraLineParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        pct = params.get("pct_of_total")
        amt = params.get("amount")
        if pct is None and amt is None:
            return ["add_extra_line requires either pct_of_total or amount"]
        if pct is not None:
            # Check band boundary proximity: not within 0.2 of 2.0 or 5.0
            if abs(pct - 2.0) < 0.2 or abs(pct - 5.0) < 0.2:
                return [f"pct_of_total {pct} is within 0.2 of band boundary (2.0 or 5.0)"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        pct = params.get("pct_of_total")
        if pct is not None:
            clean_grand = to_decimal(doc.grand_total or 0.0)
            extra_amt = quantize_money(to_decimal(pct) / Decimal("100") * clean_grand)
        else:
            extra_amt = quantize_money(params["amount"])

        # append line
        next_line_no = max([l.line_no for l in new_doc.lines], default=0) + 1
        new_line = DocumentLine(
            line_no=next_line_no,
            description="Freight and handling",
            uom="pcs",
            qty=1,
            unit_price=float(extra_amt),
            line_total=float(extra_amt),
            tax_rate=0.0,
        )
        new_doc.lines.append(new_line)

        # recompute totals
        line_tuples = [(to_decimal(l.line_total), compute_line_tax(l.line_total, l.tax_rate)) for l in new_doc.lines]
        subtotal, tax_total, grand_total = compute_totals(line_tuples)
        new_doc.subtotal = float(subtotal)
        new_doc.tax_total = float(tax_total)
        new_doc.grand_total = float(grand_total)
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        pct = params.get("pct_of_total")
        if pct is not None:
            if pct <= 2.0:
                return DerivedExpectation(decision="APPROVED", reason_code="APPROVED_WITH_NOTE")
            elif pct <= 5.0:
                return DerivedExpectation(decision="NEEDS_REVIEW")
            else:
                return DerivedExpectation(decision="REJECTED", reason_code="OVERBILLED")
        return None


# --- 7. price_drift ---
class PriceDriftParams(BaseModel):
    min_drift_pct: float = 5.0


class PriceDriftMutation(Mutation):
    name = "price_drift"
    params_model = PriceDriftParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if len(doc.lines) < 2:
            return ["price_drift requires at least 2 lines"]
        # uniform tax rate check
        first_tax = doc.lines[0].tax_rate
        for l in doc.lines:
            if l.tax_rate != first_tax:
                return ["price_drift requires all lines to have uniform tax rate"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        min_drift = params.get("min_drift_pct", 5.0)
        target_subtotal = to_decimal(doc.subtotal or 0.0)

        lines_in = [{"qty": l.qty, "unit_price": to_decimal(l.unit_price), "tax_rate": to_decimal(l.tax_rate)} for l in new_doc.lines]
        drifted = compute_drifted_lines(lines_in, target_subtotal, min_drift_pct=min_drift, rng=ctx.rng)

        for i, (new_qty, new_price) in enumerate(drifted):
            new_doc.lines[i].qty = new_qty
            new_doc.lines[i].unit_price = float(new_price)
            new_doc.lines[i].line_total = float(quantize_money(to_decimal(new_qty) * new_price))

        # Recompute to verify arithmetic
        line_tuples = [(to_decimal(l.line_total), compute_line_tax(l.line_total, l.tax_rate)) for l in new_doc.lines]
        sub, tax, grand = compute_totals(line_tuples)
        if sub != target_subtotal:
            raise ValueError(f"Drift subtotal mismatch: got {sub}, expected {target_subtotal}")
        new_doc.subtotal = float(sub)
        new_doc.tax_total = float(tax)
        new_doc.grand_total = float(grand)
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="PRICE_DRIFT")


# --- 8. arith_break ---
class ArithBreakParams(BaseModel):
    delta: Union[float, Decimal]


class ArithBreakMutation(Mutation):
    name = "arith_break"
    params_model = ArithBreakParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        delta = to_decimal(params.get("delta", 0))
        # abs(delta) > 5 * rounding_tolerance (default 1.00 -> 5.00)
        if abs(delta) <= Decimal("5.00"):
            return [f"abs(delta) {abs(delta)} must be > 5 * rounding_tolerance (5.00)"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        delta = to_decimal(params["delta"])
        clean_grand = to_decimal(new_doc.grand_total or 0.0)
        new_doc.grand_total = float(quantize_money(clean_grand + delta))
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="ARITHMETIC_MISMATCH")


# --- 9. reword_descriptions ---
class RewordDescriptionsParams(BaseModel):
    drop_po_ref: bool = False


class RewordDescriptionsMutation(Mutation):
    name = "reword_descriptions"
    params_model = RewordDescriptionsParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        po = ctx.pos_by_id.get(ctx.scenario.po_id)
        if po:
            for idx, line in enumerate(new_doc.lines):
                # find catalog item
                po_line = next((pl for pl in po.lines if pl.line_no == idx + 1), None)
                if po_line:
                    cat_item = ctx.catalog_by_sku.get(po_line.sku)
                    if cat_item and cat_item.reworded:
                        # first reworded variant or round-robin
                        chosen = cat_item.reworded[idx % len(cat_item.reworded)]
                        line.description = chosen

        if params.get("drop_po_ref", False):
            new_doc.po_reference = None
        return new_doc


# --- 10. missing_field ---
class MissingFieldParams(BaseModel):
    field: Literal["invoice_number", "invoice_date", "grand_total"]
    omit_label: bool = False


class MissingFieldMutation(Mutation):
    name = "missing_field"
    params_model = MissingFieldParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        field = params.get("field")
        if field not in ["invoice_number", "invoice_date", "grand_total"]:
            return [f"Invalid missing_field target: {field}"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        field = params["field"]
        omit_label = params.get("omit_label", False)
        if field == "invoice_number":
            new_doc.invoice_number = None
        elif field == "invoice_date":
            new_doc.invoice_date = None
        elif field == "grand_total":
            new_doc.grand_total = None

        new_doc.omit.fields.append(field)
        new_doc.omit.omit_label = omit_label
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="MISSING_FIELDS")


# --- 11. lookalike_vendor ---
class LookalikeVendorMutation(Mutation):
    name = "lookalike_vendor"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if not doc.vendor_block or not doc.vendor_block.name:
            return ["lookalike_vendor requires existing vendor_block.name"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        current_name = new_doc.vendor_block.name
        other_names = [v.name for v_id, v in ctx.vendors_by_id.items() if v.name != current_name]

        match_th = ctx.constants.get("vendor_match_threshold", 0.90) if ctx.constants else 0.90
        rej_th = ctx.constants.get("vendor_reject_threshold", 0.75) if ctx.constants else 0.75

        lookalike_name = generate_lookalike_name(current_name, other_names, match_th, rej_th)

        # replace name, drop GSTIN, email, phone, bank; keep address
        new_doc.vendor_block.name = lookalike_name
        new_doc.vendor_block.gstin = None
        new_doc.vendor_block.email = None
        new_doc.vendor_block.phone = None
        new_doc.vendor_block.bank_account = None
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="VENDOR_UNCLEAR")


# --- 12. change_bank ---
class ChangeBankParams(BaseModel):
    new_bank_account: Optional[str] = "HDFC00099999999"


class ChangeBankMutation(Mutation):
    name = "change_bank"
    params_model = ChangeBankParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        if new_doc.vendor_block:
            new_doc.vendor_block.bank_account = params.get("new_bank_account", "HDFC00099999999")
        return new_doc


# --- 13. change_currency ---
class ChangeCurrencyParams(BaseModel):
    currency: str


class ChangeCurrencyMutation(Mutation):
    name = "change_currency"
    params_model = ChangeCurrencyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if not params.get("currency"):
            return ["change_currency requires currency param"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.currency = params["currency"]
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        po = ctx.pos_by_id.get(ctx.scenario.po_id)
        if po and po.currency != params["currency"]:
            return DerivedExpectation(decision="REJECTED", reason_code="CURRENCY_MISMATCH")
        return None


# --- 14. make_credit_note ---
class MakeCreditNoteMutation(Mutation):
    name = "make_credit_note"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.title = "CREDIT NOTE"
        new_doc.document_type = "credit_note"
        for line in new_doc.lines:
            line.line_total = -abs(line.line_total)
            line.unit_price = -abs(line.unit_price)
        if new_doc.subtotal is not None:
            new_doc.subtotal = -abs(new_doc.subtotal)
        if new_doc.tax_total is not None:
            new_doc.tax_total = -abs(new_doc.tax_total)
        if new_doc.grand_total is not None:
            new_doc.grand_total = -abs(new_doc.grand_total)
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="UNSUPPORTED_DOCUMENT_TYPE")


# --- 15. shift_date ---
class ShiftDateParams(BaseModel):
    offset_days: int


class ShiftDateMutation(Mutation):
    name = "shift_date"
    params_model = ShiftDateParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if "offset_days" not in params:
            return ["shift_date requires offset_days param"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.invoice_date = resolve_offset_date(params["offset_days"])
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        offset = params["offset_days"]
        po = ctx.pos_by_id.get(ctx.scenario.po_id)
        po_offset = po.po_date.offset_days if po else 0
        if offset > 0 or offset < -90 or (po and offset < po_offset):
            return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="DATE_INVALID")
        return None


# --- 16. reformat ---
class ReformatParams(BaseModel):
    number_format: Optional[Literal["plain", "indian", "eu"]] = None
    currency_style: Optional[Literal["Rs.", "₹", "INR"]] = None
    date_style: Optional[Literal["dmy_slash", "dmy_mon", "iso"]] = None


class ReformatMutation(Mutation):
    name = "reformat"
    params_model = ReformatParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        # Check day-of-month <= 12 and date_style == dmy_slash
        date_style = params.get("date_style")
        if date_style == "dmy_slash" and new_doc.invoice_date:
            try:
                parts = new_doc.invoice_date.split("-")
                day = int(parts[2])
                if day <= 12:
                    new_doc.flags.ambiguous_date = True
            except Exception:
                pass
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        date_style = params.get("date_style")
        if date_style == "dmy_slash" and ctx.scenario.invoice:
            # Check day
            d_str = resolve_offset_date(ctx.scenario.invoice.invoice_date.offset_days)
            if int(d_str.split("-")[2]) <= 12:
                return None
        return None


# --- 17. embed_tax ---
class EmbedTaxMutation(Mutation):
    name = "embed_tax"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.tax_mode = "embedded"

        # Line unit_price/line_total become tax-inclusive (round half up)
        total_embedded = Decimal("0.00")
        target_grand = to_decimal(new_doc.grand_total or 0.0)

        for line in new_doc.lines:
            orig_p = to_decimal(line.unit_price)
            tax_r = to_decimal(line.tax_rate)
            inc_price = quantize_money(orig_p * (Decimal("1.0") + tax_r / Decimal("100")))
            line.unit_price = float(inc_price)
            line.line_total = float(quantize_money(to_decimal(line.qty) * inc_price))
            total_embedded += to_decimal(line.line_total)

        # Fix rounding residue on the last line
        residue = target_grand - total_embedded
        if residue != Decimal("0.00") and new_doc.lines:
            last = new_doc.lines[-1]
            last.line_total = float(to_decimal(last.line_total) + residue)

        new_doc.subtotal = None
        new_doc.tax_total = None
        return new_doc


# --- 18. renumber_format ---
class RenumberFormatParams(BaseModel):
    style: Literal["strip_separators"] = "strip_separators"


class RenumberFormatMutation(Mutation):
    name = "renumber_format"
    params_model = RenumberFormatParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if not doc.invoice_number:
            return ["renumber_format requires invoice_number"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        # strip separators
        new_doc.invoice_number = re.sub(r"[\s\-\/\#\_\:\.]+", "", new_doc.invoice_number)
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        if ctx.scenario.relation and ctx.scenario.relation.type == "duplicate_of":
            return DerivedExpectation(decision="REJECTED", reason_code="DUPLICATE_EXACT")
        return None


# --- 19. rerender ---
class RerenderMutation(Mutation):
    name = "rerender"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        return doc.model_copy(deep=True)

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        if ctx.scenario.relation and ctx.scenario.relation.type == "duplicate_of":
            return DerivedExpectation(decision="REJECTED", reason_code="DUPLICATE_EXACT")
        return None


# --- 20. resend_identical ---
class ResendIdenticalMutation(Mutation):
    name = "resend_identical"
    params_model = EmptyParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if not ctx.scenario.derive_from:
            return ["resend_identical requires derive_from"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        return doc.model_copy(deep=True)

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        # derived expected = source expected
        return None


# --- 21. new_number_same_amount ---
class NewNumberSameAmountParams(BaseModel):
    new_invoice_no: str
    date_delta_days: int = 0


class NewNumberSameAmountMutation(Mutation):
    name = "new_number_same_amount"
    params_model = NewNumberSameAmountParams

    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        if not params.get("new_invoice_no"):
            return ["new_number_same_amount requires new_invoice_no"]
        return []

    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        new_doc = doc.model_copy(deep=True)
        new_doc.invoice_number = params["new_invoice_no"]
        if params.get("date_delta_days", 0) != 0 and new_doc.invoice_date:
            parts = new_doc.invoice_date.split("-")
            d = datetime.date(int(parts[0]), int(parts[1]), int(parts[2])) + datetime.timedelta(days=params["date_delta_days"])
            new_doc.invoice_date = d.isoformat()
        return new_doc

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        return DerivedExpectation(decision="NEEDS_REVIEW", reason_code="DUPLICATE_POSSIBLE")


# Register all mutations
for m_cls in [
    NoneMutation,
    DropPORefMutation,
    DropVendorBlockMutation,
    POTypoMutation,
    SwapPORefMutation,
    AddExtraLineMutation,
    PriceDriftMutation,
    ArithBreakMutation,
    RewordDescriptionsMutation,
    MissingFieldMutation,
    LookalikeVendorMutation,
    ChangeBankMutation,
    ChangeCurrencyMutation,
    MakeCreditNoteMutation,
    ShiftDateMutation,
    ReformatMutation,
    EmbedTaxMutation,
    RenumberFormatMutation,
    RerenderMutation,
    ResendIdenticalMutation,
    NewNumberSameAmountMutation,
]:
    registry.register(m_cls())
