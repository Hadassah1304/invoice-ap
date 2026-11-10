from __future__ import annotations

import json
from pathlib import Path
import pytest

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import DecisionEnum
from invoice_pipeline.pipeline import process_invoice, resolve_invoice
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import InvoiceRepo, ItemRepo, PORepo, VendorRepo


def setup_test_db(db_path: str):
    init_db(db_path)
    conn = get_connection(db_path)
    v_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)

    v_repo.create(
        vendor_id="V001",
        name="Apex Supplies Ltd",
        approved=1,
    )
    po_repo.create(
        po_id="PO-TEST-01",
        vendor_id="V001",
        po_date="2026-10-01",
        total=1000.0,
        currency="INR",
        status="OPEN",
    )
    item_repo.create(
        po_id="PO-TEST-01",
        item_name="A4 Paper 80gsm Ream",
        description="A4 paper 80gsm",
        qty_ordered=10.0,
        qty_remaining=10.0,
        unit_price=100.0,
    )
    conn.close()


def test_resolve_in_place_no_self_duplicate(tmp_path):
    db_file = str(tmp_path / "resolve_test.db")
    setup_test_db(db_file)
    cfg = PipelineConfig(app={"db_path": db_file})

    canned = {
        "vendor": {"name": "Apex Supplies Ltd"},
        "invoice_number": {"value": "INV-RES-01"},
        "invoice_date": {"value": "2026-10-15"},
        "po_reference": {"value": "PO-TEST-01"},
        "currency": {"value": "INR"},
        "grand_total": {"value": 500.0},
        "line_items": [
            {"line_no": 1, "description": "A4 Paper 80gsm Ream", "quantity": 5.0, "unit_price": 100.0, "line_total": 500.0}
        ],
        "document_type": "invoice",
    }

    # Initial run: force review by setting ambiguous date or similar, or override
    # If it is approved or pending review:
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    res = process_invoice(pdf_path, config=cfg, pre_extracted_json=canned)
    assert res.decision in (DecisionEnum.APPROVED, DecisionEnum.NEEDS_REVIEW)

    conn = get_connection(db_file)
    inv_repo = InvoiceRepo(conn)
    invoices = inv_repo.list_all()
    assert len(invoices) == 1
    inv_id = invoices[0]["invoice_id"]
    conn.close()

    # Now resolve invoice with manual override on the SAME invoice_id
    resolved_res = resolve_invoice(
        invoice_id=inv_id,
        action="override",
        overrides={"vendor_id": "V001", "po_id": "PO-TEST-01"},
        config=cfg,
    )

    # Must NOT fail with DUPLICATE_EXACT self-collision
    assert resolved_res.reason_code.value != "DUPLICATE_EXACT"

    # Verify ledger only has 1 invoice row (updated in-place)
    conn = get_connection(db_file)
    inv_repo = InvoiceRepo(conn)
    invoices_after = inv_repo.list_all()
    assert len(invoices_after) == 1
    assert invoices_after[0]["invoice_id"] == inv_id
    conn.close()


def test_resolve_reject_restores_quantities(tmp_path):
    db_file = str(tmp_path / "reject_restore_test.db")
    setup_test_db(db_file)
    cfg = PipelineConfig(app={"db_path": db_file})
    cfg.validation.reserve_pending_invoices = True

    # Invoice that needs review (e.g. price drift or missing date)
    canned = {
        "vendor": {"name": "Apex Supplies Ltd"},
        "invoice_number": {"value": "INV-RES-02"},
        "invoice_date": {"value": "2026-10-15"},
        "po_reference": {"value": "PO-TEST-01"},
        "currency": {"value": "INR"},
        "grand_total": {"value": 500.0},
        "line_items": [
            # Price drifted: unit price 125, qty 4
            {"line_no": 1, "description": "A4 Paper 80gsm Ream", "quantity": 4.0, "unit_price": 125.0, "line_total": 500.0}
        ],
        "document_type": "invoice",
    }

    pdf_path = tmp_path / "dummy2.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    res = process_invoice(pdf_path, config=cfg, pre_extracted_json=canned)
    assert res.decision == DecisionEnum.NEEDS_REVIEW

    # Check that remaining qty was decremented to 6.0 (10.0 - 4.0)
    conn = get_connection(db_file)
    item_repo = ItemRepo(conn)
    items = item_repo.list_by_po("PO-TEST-01")
    assert items[0]["qty_remaining"] == 6.0

    invoices = InvoiceRepo(conn).list_all()
    inv_id = invoices[0]["invoice_id"]
    conn.close()

    # Reject this pending invoice
    resolve_invoice(
        invoice_id=inv_id,
        action="reject",
        config=cfg,
        note="Rejected by AP manager",
    )

    # Check that qty was restored back to 10.0
    conn = get_connection(db_file)
    items_after = ItemRepo(conn).list_by_po("PO-TEST-01")
    assert items_after[0]["qty_remaining"] == 10.0

    inv_row = InvoiceRepo(conn).get_by_id(inv_id)
    assert inv_row["status"] == "REJECTED"
    assert inv_row["is_manual_override"] == 1
    assert inv_row["override_note"] == "Rejected by AP manager"
    conn.close()


def test_resolve_approve_and_undo(tmp_path):
    db_file = str(tmp_path / "approve_undo_test.db")
    setup_test_db(db_file)
    cfg = PipelineConfig(app={"db_path": db_file})
    cfg.validation.reserve_pending_invoices = True

    canned = {
        "vendor": {"name": "Apex Supplies Ltd"},
        "invoice_number": {"value": "INV-RES-03"},
        "invoice_date": {"value": "2026-10-15"},
        "po_reference": {"value": "PO-TEST-01"},
        "currency": {"value": "INR"},
        "grand_total": {"value": 500.0},
        "line_items": [
            {"line_no": 1, "description": "A4 Paper 80gsm Ream", "quantity": 4.0, "unit_price": 125.0, "line_total": 500.0}
        ],
        "document_type": "invoice",
    }

    pdf_path = tmp_path / "dummy3.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    res = process_invoice(pdf_path, config=cfg, pre_extracted_json=canned)
    assert res.decision == DecisionEnum.NEEDS_REVIEW

    conn = get_connection(db_file)
    invoices = InvoiceRepo(conn).list_all()
    inv_id = invoices[0]["invoice_id"]
    conn.close()

    # 1. Force approve
    app_res = resolve_invoice(
        invoice_id=inv_id,
        action="approve",
        config=cfg,
        note="Approved by supervisor exception",
    )
    assert app_res.decision == DecisionEnum.APPROVED
    assert app_res.is_manual_override is True
    assert app_res.override_note == "Approved by supervisor exception"
    assert app_res.override_action == "approve"
    assert app_res.review.required is False

    conn = get_connection(db_file)
    inv_row = InvoiceRepo(conn).get_by_id(inv_id)
    assert inv_row["status"] == "APPROVED"
    assert inv_row["is_manual_override"] == 1
    assert inv_row["override_note"] == "Approved by supervisor exception"
    conn.close()

    # 2. Undo override back to PENDING_REVIEW
    undo_res = resolve_invoice(
        invoice_id=inv_id,
        action="undo",
        config=cfg,
    )
    assert undo_res.decision == DecisionEnum.NEEDS_REVIEW
    assert undo_res.is_manual_override is False
    assert undo_res.override_note is None
    assert undo_res.override_action is None
    assert undo_res.review.required is True

    conn = get_connection(db_file)
    inv_row_after = InvoiceRepo(conn).get_by_id(inv_id)
    assert inv_row_after["status"] == "PENDING_REVIEW"
    assert inv_row_after["is_manual_override"] == 0
    assert inv_row_after["override_note"] is None
    conn.close()


def test_resolve_reject_and_undo(tmp_path):
    db_file = str(tmp_path / "reject_undo_test.db")
    setup_test_db(db_file)
    cfg = PipelineConfig(app={"db_path": db_file})
    cfg.validation.reserve_pending_invoices = True

    canned = {
        "vendor": {"name": "Apex Supplies Ltd"},
        "invoice_number": {"value": "INV-RES-04"},
        "invoice_date": {"value": "2026-10-15"},
        "po_reference": {"value": "PO-TEST-01"},
        "currency": {"value": "INR"},
        "grand_total": {"value": 500.0},
        "line_items": [
            {"line_no": 1, "description": "A4 Paper 80gsm Ream", "quantity": 4.0, "unit_price": 125.0, "line_total": 500.0}
        ],
        "document_type": "invoice",
    }

    pdf_path = tmp_path / "dummy4.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")

    res = process_invoice(pdf_path, config=cfg, pre_extracted_json=canned)
    assert res.decision == DecisionEnum.NEEDS_REVIEW

    conn = get_connection(db_file)
    invoices = InvoiceRepo(conn).list_all()
    inv_id = invoices[0]["invoice_id"]
    conn.close()

    # 1. Reject
    rej_res = resolve_invoice(
        invoice_id=inv_id,
        action="reject",
        config=cfg,
        note="Rejected due to mismatch",
    )
    assert rej_res.decision == DecisionEnum.REJECTED
    assert rej_res.is_manual_override is True
    assert rej_res.override_note == "Rejected due to mismatch"

    conn = get_connection(db_file)
    inv_row = InvoiceRepo(conn).get_by_id(inv_id)
    assert inv_row["status"] == "REJECTED"
    assert inv_row["is_manual_override"] == 1
    # Check qty was restored
    items = ItemRepo(conn).list_by_po("PO-TEST-01")
    assert items[0]["qty_remaining"] == 10.0
    conn.close()

    # 2. Undo reject
    undo_res = resolve_invoice(
        invoice_id=inv_id,
        action="undo",
        config=cfg,
    )
    assert undo_res.decision == DecisionEnum.NEEDS_REVIEW
    assert undo_res.is_manual_override is False
    assert undo_res.review.required is True

    conn = get_connection(db_file)
    inv_row_after = InvoiceRepo(conn).get_by_id(inv_id)
    assert inv_row_after["status"] == "PENDING_REVIEW"
    assert inv_row_after["is_manual_override"] == 0
    # Check qty was decremented again upon returning to PENDING_REVIEW
    items_after = ItemRepo(conn).list_by_po("PO-TEST-01")
    assert items_after[0]["qty_remaining"] == 6.0
    conn.close()
