from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from invoice_pipeline.models import (
    ExtractedInvoice,
    ExtractedLineItem,
    ExtractedVendor,
    ExtractionSource,
    FieldValue,
    GroundingResult,
)


def build_extracted_invoice(
    document: Any,
    file_name: str,
    file_hash: str,
    page_count: int = 1,
) -> ExtractedInvoice:
    """Construct an ExtractedInvoice-shaped object directly from case.document printed values."""
    omit_fields = document.omit.fields if hasattr(document, "omit") and document.omit else []
    flags = getattr(document, "flags", None)
    ambiguous_date = getattr(flags, "ambiguous_date", False) if flags else False

    missing_fields: List[str] = []

    # Vendor block
    vb = getattr(document, "vendor_block", None)
    v_name = None
    v_gstin = None
    v_email = None
    v_phone = None
    v_addr = None
    v_bank = None

    if "vendor_block" in omit_fields or "vendor" in omit_fields or vb is None:
        missing_fields.append("vendor")
    else:
        v_name = getattr(vb, "name", None) if "vendor_name" not in omit_fields else None
        v_gstin = getattr(vb, "gstin", None) if "gstin" not in omit_fields else None
        v_email = getattr(vb, "email", None)
        v_phone = getattr(vb, "phone", None)
        v_addr = getattr(vb, "address", None)
        v_bank = getattr(vb, "bank_account", None)
        if not v_name and not v_gstin:
            missing_fields.append("vendor")

    vendor_obj = ExtractedVendor(
        name=v_name,
        gstin=v_gstin,
        email=v_email,
        phone=v_phone,
        address=v_addr,
        bank_account=v_bank,
        confidence=1.0 if (v_name or v_gstin) else 0.0,
    )

    # Invoice Number
    raw_inv_num = getattr(document, "invoice_number", None)
    if "invoice_number" in omit_fields or raw_inv_num is None:
        inv_num_val = None
        inv_num_conf = 0.0
        missing_fields.append("invoice_number")
    else:
        inv_num_val = raw_inv_num
        inv_num_conf = 1.0
    invoice_number = FieldValue(value=inv_num_val, confidence=inv_num_conf)

    # Invoice Date
    raw_inv_date = getattr(document, "invoice_date", None)
    if "invoice_date" in omit_fields or raw_inv_date is None:
        inv_date_val = None
        inv_date_conf = 0.0
        missing_fields.append("invoice_date")
    else:
        inv_date_val = raw_inv_date
        inv_date_conf = 1.0
    invoice_date = FieldValue(value=inv_date_val, confidence=inv_date_conf, ambiguous=ambiguous_date)

    # Due Date
    raw_due_date = getattr(document, "due_date", None)
    due_date = FieldValue(value=raw_due_date, confidence=1.0 if raw_due_date is not None else 0.0) if raw_due_date is not None else None

    # PO Reference
    raw_po_ref = getattr(document, "po_reference", None)
    if "po_reference" in omit_fields:
        po_reference = None
    elif raw_po_ref is not None:
        po_reference = FieldValue(value=raw_po_ref, confidence=1.0)
    else:
        po_reference = None

    # Currency
    curr = getattr(document, "currency", "INR") or "INR"
    currency = FieldValue(value=curr, confidence=1.0)

    # Line Items
    doc_lines = getattr(document, "lines", []) or []
    extracted_lines: List[ExtractedLineItem] = []
    for line in doc_lines:
        line_no = getattr(line, "line_no", None)
        desc = getattr(line, "description", "") or ""
        qty = float(getattr(line, "qty", 0))
        uom = getattr(line, "uom", "pcs") or "pcs"
        unit_price = float(getattr(line, "unit_price", 0.0))
        line_total = float(getattr(line, "line_total", 0.0))
        tax_rate = float(getattr(line, "tax_rate", 0.0))
        extracted_lines.append(
            ExtractedLineItem(
                line_no=line_no,
                description=desc,
                quantity=qty,
                uom=uom,
                unit_price=unit_price,
                line_total=line_total,
                tax_rate=tax_rate,
                confidence=1.0,
            )
        )
    if not extracted_lines:
        missing_fields.append("line_items")

    # Subtotal
    raw_subtotal = getattr(document, "subtotal", None)
    if "subtotal" in omit_fields or raw_subtotal is None:
        subtotal = None
    else:
        subtotal = FieldValue(value=float(raw_subtotal), confidence=1.0)

    # Tax Total
    raw_tax_total = getattr(document, "tax_total", None)
    if "tax_total" in omit_fields or raw_tax_total is None:
        tax_total = None
    else:
        tax_total = FieldValue(value=float(raw_tax_total), confidence=1.0)

    # Grand Total
    raw_grand_total = getattr(document, "grand_total", None)
    if "grand_total" in omit_fields or raw_grand_total is None:
        grand_total_val = None
        grand_total_conf = 0.0
        missing_fields.append("grand_total")
    else:
        grand_total_val = float(raw_grand_total)
        grand_total_conf = 1.0
    grand_total = FieldValue(value=grand_total_val, confidence=grand_total_conf)

    # Document Type
    doc_type = getattr(document, "document_type", "invoice") or "invoice"

    # Assemble ExtractionSource
    source = ExtractionSource(
        file_name=file_name,
        file_hash=file_hash,
        extraction_method="synthetic",
        ocr_confidence=1.0,
        page_count=page_count,
    )

    # Deduplicate missing_fields while preserving order
    unique_missing = list(dict.fromkeys(missing_fields))

    return ExtractedInvoice(
        source=source,
        vendor=vendor_obj,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        po_reference=po_reference,
        currency=currency,
        line_items=extracted_lines,
        subtotal=subtotal,
        tax_total=tax_total,
        grand_total=grand_total,
        document_type=doc_type,
        raw_text=None,
        missing_fields=unique_missing,
        grounding=GroundingResult(checked=0, failed=[]),
    )


def save_extracted_json(extracted: ExtractedInvoice, output_path: str):
    """Write validated ExtractedInvoice to disk formatted with 2-space indentation."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(extracted.model_dump_json(indent=2) + "\n")
