import pytest
from invoice_pipeline.config import ValidationConfig
from invoice_pipeline.models import ExtractedInvoice, ExtractionSource, ExtractedVendor, FieldValue, ExtractedLineItem
from invoice_pipeline.normalize.normalizers import (
    normalize_currency,
    normalize_invoice_number,
    normalize_vendor_name,
    parse_date,
    parse_number,
)
from invoice_pipeline.validation.rules import (
    ValidationContext,
    check_arithmetic,
    check_balance_tolerance,
    check_line_price_variance,
)
from invoice_pipeline.models import LineMatchDetail


def test_normalizers():
    assert normalize_invoice_number("INV/2026/0381") == "INV20260381"
    assert normalize_invoice_number("000123") == "123"
    assert normalize_invoice_number("INV-001") == "INV001"

    assert normalize_vendor_name("Acme Private Limited") == "acme"
    assert normalize_vendor_name("Balaji Foods Pvt. Ltd.") == "balaji foods"

    assert normalize_currency("₹") == "INR"
    assert normalize_currency("Rs.") == "INR"
    assert normalize_currency("$") == "USD"

    assert parse_number("1,00,000.50") == 100000.50
    assert parse_number("1.000,50") == 1000.50
    assert parse_number("Rs. 4,500") == 4500.0

    d, amb = parse_date("03/04/2026")
    assert d == "2026-04-03"
    assert amb is True

    d2, amb2 = parse_date("28/10/2026")
    assert d2 == "2026-10-28"
    assert amb2 is False


def test_arithmetic_rule():
    cfg = ValidationConfig()
    inv = ExtractedInvoice(
        source=ExtractionSource(file_name="test.pdf", file_hash="abc", extraction_method="text_layer"),
        vendor=ExtractedVendor(name="Acme"),
        invoice_number=FieldValue(value="INV-1"),
        invoice_date=FieldValue(value="2026-10-01"),
        currency=FieldValue(value="INR"),
        line_items=[
            ExtractedLineItem(line_no=1, description="Item 1", quantity=2, unit_price=50, line_total=100)
        ],
        subtotal=FieldValue(value=100.0),
        tax_total=FieldValue(value=18.0),
        grand_total=FieldValue(value=118.0),
    )
    ctx = ValidationContext(config=cfg, extracted_invoice=inv)
    res = check_arithmetic(ctx)
    assert res.status.value == "PASS"

    # Mismatch total
    inv.grand_total.value = 150.0
    res2 = check_arithmetic(ctx)
    assert res2.status.value == "FLAG"
