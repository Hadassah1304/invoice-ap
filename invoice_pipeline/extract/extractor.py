from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from invoice_pipeline.config import LLMConfig
from invoice_pipeline.extract.grounding import check_grounding
from invoice_pipeline.extract.llm_client import LLMClient
from invoice_pipeline.models import (
    ExtractedInvoice,
    ExtractedLineItem,
    ExtractedVendor,
    ExtractionSource,
    FieldValue,
    GroundingResult,
)


class Extractor:
    """Coordinates text or vision extraction and constructs validated ExtractedInvoice model."""

    def __init__(self, config: LLMConfig, llm_client: Optional[LLMClient] = None) -> None:
        self.config = config
        self.llm_client = llm_client or LLMClient(config)

    def extract(
        self,
        raw_text: str,
        source: ExtractionSource,
        page_images: Optional[List[Any]] = None,
        pre_extracted_json: Optional[Dict[str, Any]] = None,
        needs_vision: bool = False,
    ) -> Tuple[ExtractedInvoice, int, int]:
        """
        Extracts structured invoice data without hallucinating default numbers or confidences.
        Supports automatic vision fallback when OCR text is weak or key fields are missing.
        """
        in_tok, out_tok = 0, 0
        if pre_extracted_json:
            data = pre_extracted_json
        else:
            mode = self.config.extraction.input_mode
            # Auto mode uses images if needs_vision is True or input_mode == 'image'
            if (mode == "image" or (mode == "auto" and needs_vision)) and page_images:
                data, in_tok, out_tok = self.llm_client.extract_from_images(page_images)
            else:
                data, in_tok, out_tok = self.llm_client.extract_from_text(raw_text)

        # Parse vendor without fabricating defaults
        v_data = data.get("vendor") or {}
        vendor = ExtractedVendor(
            name=v_data.get("name"),
            gstin=v_data.get("gstin"),
            email=v_data.get("email"),
            phone=v_data.get("phone"),
            address=v_data.get("address"),
            bank_account=v_data.get("bank_account"),
            confidence=float(v_data.get("confidence") or 0.0),
        )

        def make_field(f_dict: Optional[dict]) -> FieldValue:
            if not f_dict or not isinstance(f_dict, dict):
                return FieldValue(value=None, confidence=0.0)
            val = f_dict.get("value")
            # Empty string means null
            if val == "":
                val = None
            conf = float(f_dict.get("confidence") or 0.0)
            return FieldValue(
                value=val,
                confidence=conf,
                ambiguous=f_dict.get("ambiguous"),
            )

        inv_num = make_field(data.get("invoice_number"))
        inv_date = make_field(data.get("invoice_date"))
        due_date = make_field(data.get("due_date")) if "due_date" in data else None
        po_ref = make_field(data.get("po_reference")) if "po_reference" in data else None
        currency = make_field(data.get("currency"))
        subtotal = make_field(data.get("subtotal")) if "subtotal" in data else None
        tax_total = make_field(data.get("tax_total")) if "tax_total" in data else None
        grand_total = make_field(data.get("grand_total"))

        # Line items: never guess quantity=1.0 or price=0.0 if not on document
        lines: List[ExtractedLineItem] = []
        for l in data.get("line_items", []):
            desc = l.get("description")
            if not desc:
                continue
            qty = float(l["quantity"]) if l.get("quantity") is not None else None
            u_price = float(l["unit_price"]) if l.get("unit_price") is not None else None
            l_total = float(l["line_total"]) if l.get("line_total") is not None else None
            t_rate = float(l["tax_rate"]) if l.get("tax_rate") is not None else None
            conf = float(l.get("confidence") or 0.0)

            lines.append(
                ExtractedLineItem(
                    line_no=int(l["line_no"]) if l.get("line_no") is not None else len(lines) + 1,
                    description=str(desc),
                    quantity=qty,
                    uom=l.get("uom"),
                    unit_price=u_price,
                    line_total=l_total,
                    tax_rate=t_rate,
                    confidence=conf,
                )
            )

        # Missing fields calculation
        missing = []
        if not inv_num.value:
            missing.append("invoice_number")
        if not inv_date.value:
            missing.append("invoice_date")
        if grand_total.value is None:
            missing.append("grand_total")
        if not vendor.name and not vendor.gstin:
            missing.append("vendor")
        if not lines:
            missing.append("line_items")

        extracted = ExtractedInvoice(
            source=source,
            vendor=vendor,
            invoice_number=inv_num,
            invoice_date=inv_date,
            due_date=due_date,
            po_reference=po_ref,
            currency=currency,
            line_items=lines,
            subtotal=subtotal,
            tax_total=tax_total,
            grand_total=grand_total,
            document_type=data.get("document_type", "invoice"),
            raw_text=raw_text,
            missing_fields=missing,
        )

        return extracted, in_tok, out_tok
