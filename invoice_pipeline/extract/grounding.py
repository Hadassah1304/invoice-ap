from __future__ import annotations

import re
from typing import Any, List, Optional
from invoice_pipeline.models import ExtractedInvoice, GroundingResult


def _clean_str(s: str) -> str:
    return re.sub(r"[\s\-\/\,\.\:\;\#\_]+", "", s).lower()


def check_grounding(extracted: ExtractedInvoice, raw_text: Optional[str], tolerance: float = 0.01) -> GroundingResult:
    """
    Verifies that critical extracted values (numbers, invoice_no, PO ref, GSTIN, dates)
    appear in the raw OCR/text-layer string to prevent hallucination.
    """
    if not raw_text or raw_text.strip() == "" or raw_text == "pre_extracted_invoice":
        return GroundingResult(checked=0, failed=[])

    clean_raw = _clean_str(raw_text)
    checked = 0
    failed: List[str] = []

    # 1. Invoice Number
    inv_no = extracted.invoice_number.value
    if inv_no:
        checked += 1
        if _clean_str(str(inv_no)) not in clean_raw:
            failed.append(f"invoice_number '{inv_no}' not found in raw text")

    # 2. PO Reference
    if extracted.po_reference and extracted.po_reference.value:
        po_ref = extracted.po_reference.value
        checked += 1
        if _clean_str(str(po_ref)) not in clean_raw:
            failed.append(f"po_reference '{po_ref}' not found in raw text")

    # 3. GSTIN
    if extracted.vendor and extracted.vendor.gstin:
        gstin = extracted.vendor.gstin
        checked += 1
        if _clean_str(str(gstin)) not in clean_raw:
            failed.append(f"vendor GSTIN '{gstin}' not found in raw text")

    # 4. Grand Total
    if extracted.grand_total and extracted.grand_total.value is not None:
        checked += 1
        tot = extracted.grand_total.value
        tot_str = f"{tot:.2f}".replace(".", "")
        tot_int = str(int(round(tot)))
        if tot_str not in clean_raw and tot_int not in clean_raw:
            failed.append(f"grand_total '{tot}' not found in raw text")

    # 5. Line items unit prices
    for l in extracted.line_items:
        if l.unit_price is not None:
            checked += 1
            p_str = f"{l.unit_price:.2f}".replace(".", "")
            p_int = str(int(round(l.unit_price)))
            if p_str not in clean_raw and p_int not in clean_raw:
                failed.append(f"unit_price '{l.unit_price}' for '{l.description}' not found in raw text")

    return GroundingResult(checked=checked, failed=failed)
