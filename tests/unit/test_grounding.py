import pytest
from invoice_pipeline.extract.grounding import check_grounding
from invoice_pipeline.models import (
    ExtractedInvoice,
    ExtractionSource,
    ExtractedVendor,
    FieldValue,
    ExtractedLineItem,
)


def test_grounding():
    raw_text = """
    TAX INVOICE
    Sri Balaji Foods Pvt Ltd
    GSTIN: 36ABCDE1234F1Z5
    Invoice No: INV-2026-99
    Date: 28/10/2026
    PO Ref: PO-42

    Item: Veg Burger 150g, Qty: 10, Price: 100.00, Total: 1000.00
    Grand Total: 1000.00
    """

    inv = ExtractedInvoice(
        source=ExtractionSource(file_name="t.pdf", file_hash="123", extraction_method="text_layer"),
        vendor=ExtractedVendor(name="Sri Balaji", gstin="36ABCDE1234F1Z5"),
        invoice_number=FieldValue(value="INV-2026-99"),
        invoice_date=FieldValue(value="2026-10-28"),
        po_reference=FieldValue(value="PO-42"),
        currency=FieldValue(value="INR"),
        line_items=[
            ExtractedLineItem(line_no=1, description="Veg Burger", quantity=10, unit_price=100.0, line_total=1000.0)
        ],
        grand_total=FieldValue(value=1000.0),
        raw_text=raw_text,
    )

    grounding = check_grounding(inv, raw_text)
    assert len(grounding.failed) == 0
    assert grounding.checked > 0

    # Test hallucinated PO
    inv.po_reference.value = "PO-9999"
    g2 = check_grounding(inv, raw_text)
    assert len(g2.failed) == 1
    assert "po_reference 'PO-9999' not found" in g2.failed[0]
