from __future__ import annotations

import concurrent.futures
from pathlib import Path
import pytest
import sqlite3

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import DecisionEnum
from invoice_pipeline.pipeline import process_invoice
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import ItemRepo, PORepo, VendorRepo


def setup_concurrency_db(db_path: str):
    init_db(db_path)
    conn = get_connection(db_path)
    v_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)

    v_repo.create(vendor_id="V-CONC", name="Concurrent Vendors Inc", approved=1)
    po_repo.create(
        po_id="PO-CONC-01",
        vendor_id="V-CONC",
        po_date="2026-10-01",
        total=1000.0,
        currency="INR",
        status="OPEN",
    )
    item_repo.create(
        po_id="PO-CONC-01",
        item_name="Widget Pro",
        description="Concurrency test widget",
        qty_ordered=10.0,
        qty_remaining=10.0,
        unit_price=100.0,
    )
    conn.close()


def test_concurrent_invoices_atomic_po_balance(tmp_path):
    """
    Two concurrent invoices each bill 700.0 against a PO with total 1000.0.
    With BEGIN IMMEDIATE and atomic ledger locking:
    The first invoice succeeds (approved/pending).
    The second invoice must be rejected or review-flagged for exceeding remaining balance (cannot both approve 700 on a 1000 PO).
    """
    db_file = str(tmp_path / "conc_test.db")
    setup_concurrency_db(db_file)
    cfg = PipelineConfig(app={"db_path": db_file})

    pdf1 = tmp_path / "conc1.pdf"
    pdf1.write_bytes(b"%PDF-1.4 dummy1")
    pdf2 = tmp_path / "conc2.pdf"
    pdf2.write_bytes(b"%PDF-1.4 dummy2")

    canned1 = {
        "vendor": {"name": "Concurrent Vendors Inc", "confidence": 1.0},
        "invoice_number": {"value": "INV-CONC-01", "confidence": 1.0},
        "invoice_date": {"value": "2026-10-15", "confidence": 1.0},
        "po_reference": {"value": "PO-CONC-01", "confidence": 1.0},
        "currency": {"value": "INR", "confidence": 1.0},
        "grand_total": {"value": 700.0, "confidence": 1.0},
        "line_items": [{"line_no": 1, "description": "Widget Pro", "quantity": 7.0, "unit_price": 100.0, "line_total": 700.0, "confidence": 1.0}],
        "document_type": "invoice",
    }
    canned2 = {
        "vendor": {"name": "Concurrent Vendors Inc", "confidence": 1.0},
        "invoice_number": {"value": "INV-CONC-02", "confidence": 1.0},
        "invoice_date": {"value": "2026-10-16", "confidence": 1.0},
        "po_reference": {"value": "PO-CONC-01", "confidence": 1.0},
        "currency": {"value": "INR", "confidence": 1.0},
        "grand_total": {"value": 700.0, "confidence": 1.0},
        "line_items": [{"line_no": 1, "description": "Widget Pro", "quantity": 7.0, "unit_price": 100.0, "line_total": 700.0, "confidence": 1.0}],
        "document_type": "invoice",
    }

    def process_one(args):
        p, c = args
        return process_invoice(p, config=cfg, pre_extracted_json=c)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(process_one, (pdf1, canned1))
        f2 = executor.submit(process_one, (pdf2, canned2))
        res1 = f1.result()
        res2 = f2.result()

    decisions = [res1.decision, res2.decision]
    reason_codes = [res1.reason_code.value, res2.reason_code.value]

    # At most ONE invoice can be APPROVED. The other MUST NOT be approved (e.g. OVERBILLED / QTY_EXCEEDS_REMAINING / PO_CLOSED).
    approved_count = decisions.count(DecisionEnum.APPROVED)
    assert approved_count == 1, f"Expected exactly 1 APPROVED, got decisions: {decisions}, codes: {reason_codes}"

    non_approved_dec = [d for d in decisions if d != DecisionEnum.APPROVED][0]
    assert non_approved_dec in (DecisionEnum.NEEDS_REVIEW, DecisionEnum.REJECTED)
