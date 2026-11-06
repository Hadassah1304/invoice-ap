"""Tests for mutations."""

from decimal import Decimal
import random
import pytest

from datagen.models import (
    AuthoredIntent,
    AuthoredInvoice,
    AuthoredInvoiceLine,
    AuthoredPO,
    AuthoredPOLine,
    AuthoredScenario,
    AuthoredVendor,
    DateOffset,
    Document,
    DocumentLine,
    VendorBlock,
)
from datagen.mutate.ops import registry
from datagen.mutate.registry import MutationContext


def make_dummy_doc():
    return Document(
        title="TAX INVOICE",
        document_type="invoice",
        vendor_block=VendorBlock(name="Test Vendor", gstin="27AAAAA0000A1Z5"),
        invoice_number="INV/2026/01",
        invoice_date="2026-10-15",
        po_reference="PO-R-TEST-01",
        currency="INR",
        tax_mode="separate",
        lines=[
            DocumentLine(line_no=1, description="Widget A", uom="pcs", qty=10, unit_price=100.0, line_total=1000.0, tax_rate=5.0),
            DocumentLine(line_no=2, description="Widget B", uom="pcs", qty=5, unit_price=200.0, line_total=1000.0, tax_rate=5.0),
        ],
        subtotal=2000.0,
        tax_total=100.0,
        grand_total=2100.0,
    )


def make_dummy_ctx():
    sc = AuthoredScenario(
        scenario_id="SC-R-TEST-01",
        tag="happy_explicit",
        description="test",
        po_id="PO-R-TEST-01",
        intent=AuthoredIntent(decision="APPROVED", reason_codes_accepted=["OK"]),
    )
    po = AuthoredPO(
        po_id="PO-R-TEST-01",
        vendor_id="V-TEST",
        po_date=DateOffset(offset_days=-30),
        currency="INR",
        status="OPEN",
        lines=[
            AuthoredPOLine(line_no=1, sku="SKU-1", item_name="Widget A", description="", uom="pcs", qty_ordered=20, unit_price=100.0, tax_rate=5),
            AuthoredPOLine(line_no=2, sku="SKU-2", item_name="Widget B", description="", uom="pcs", qty_ordered=10, unit_price=200.0, tax_rate=5),
        ],
    )
    vendor = AuthoredVendor(
        vendor_id="V-TEST",
        name="Test Vendor",
        owner_family="R",
    )
    return MutationContext(
        scenario=sc,
        vendors_by_id={"V-TEST": vendor},
        pos_by_id={"PO-R-TEST-01": po},
        catalog_by_sku={},
        rng=random.Random(42),
    )


def test_po_typo():
    mut = registry.get("po_typo")
    doc = make_dummy_doc()
    ctx = make_dummy_ctx()

    assert mut.precondition(doc, ctx, {}) == []
    new_doc = mut.apply(doc, ctx, {})
    assert new_doc.po_reference == "PO-R-TEST-0I"  # rightmost eligible digit was '1' -> 'I'
    derived = mut.derive(new_doc, ctx, {})
    assert derived.decision == "NEEDS_REVIEW"
    assert derived.reason_code == "INVALID_PO_REF"


def test_arith_break():
    mut = registry.get("arith_break")
    doc = make_dummy_doc()
    ctx = make_dummy_ctx()

    # Precondition failure on delta <= 5
    assert len(mut.precondition(doc, ctx, {"delta": 2.0})) > 0

    assert mut.precondition(doc, ctx, {"delta": 50.0}) == []
    new_doc = mut.apply(doc, ctx, {"delta": 50.0})
    assert new_doc.grand_total == 2150.0
    derived = mut.derive(new_doc, ctx, {"delta": 50.0})
    assert derived.decision == "NEEDS_REVIEW"
    assert derived.reason_code == "ARITHMETIC_MISMATCH"


def test_missing_field():
    mut = registry.get("missing_field")
    doc = make_dummy_doc()
    ctx = make_dummy_ctx()

    new_doc = mut.apply(doc, ctx, {"field": "invoice_number"})
    assert new_doc.invoice_number is None
    assert "invoice_number" in new_doc.omit.fields
    derived = mut.derive(new_doc, ctx, {"field": "invoice_number"})
    assert derived.decision == "NEEDS_REVIEW"
    assert derived.reason_code == "MISSING_FIELDS"


def test_make_credit_note():
    mut = registry.get("make_credit_note")
    doc = make_dummy_doc()
    ctx = make_dummy_ctx()

    new_doc = mut.apply(doc, ctx, {})
    assert new_doc.document_type == "credit_note"
    assert new_doc.grand_total == -2100.0
    derived = mut.derive(new_doc, ctx, {})
    assert derived.decision == "NEEDS_REVIEW"
    assert derived.reason_code == "UNSUPPORTED_DOCUMENT_TYPE"


def test_embed_tax():
    mut = registry.get("embed_tax")
    doc = make_dummy_doc()
    ctx = make_dummy_ctx()

    new_doc = mut.apply(doc, ctx, {})
    assert new_doc.tax_mode == "embedded"
    assert new_doc.subtotal is None
    assert new_doc.tax_total is None
    # Check that sum of lines matches original grand total
    line_sum = sum(l.line_total for l in new_doc.lines)
    assert line_sum == 2100.0
