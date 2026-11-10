import os
import pytest
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.embeddings import TFIDFCharEmbedder
from invoice_pipeline.store.index import InMemoryItemIndex
from invoice_pipeline.store.repositories import (
    InvoiceRepo,
    ItemRepo,
    PORepo,
    VendorRepo,
)


@pytest.fixture
def test_db(tmp_path):
    db_file = str(tmp_path / "test.db")
    init_db(db_file)
    conn = get_connection(db_file)
    yield conn
    conn.close()


def test_db_balance_and_quantities(test_db):
    v_repo = VendorRepo(test_db)
    po_repo = PORepo(test_db)
    item_repo = ItemRepo(test_db)
    inv_repo = InvoiceRepo(test_db)

    # 1. Setup vendor and PO
    v_repo.create("V1", "Acme Corp", ["Acme"], "29ABCDE1234F1Z5", "acme.com", 1, "123456789")
    po_repo.create("PO-1", "V1", "2026-10-01", 1000.0, "INR", "OPEN")
    item_id = item_repo.create("PO-1", "Item A", "Desc A", 10.0, 10.0, 100.0)

    # 2. Add an approved invoice
    test_db.execute("BEGIN IMMEDIATE")
    inv_id = inv_repo.create(
        "V1", "INV-001", "INV001", "2026-10-05", 400.0, "INR", "PO-1", "EXPLICIT", "APPROVED", "{}"
    )
    item_repo.decrement_qty(item_id, 4.0)
    test_db.execute("COMMIT")

    consumed = inv_repo.get_po_consumed_amount("PO-1", include_pending=True)
    assert consumed == 400.0

    items = item_repo.list_by_po("PO-1")
    assert items[0]["qty_remaining"] == 6.0


def test_embedder_and_index(test_db):
    embedder = TFIDFCharEmbedder()
    v_repo = VendorRepo(test_db)
    po_repo = PORepo(test_db)
    item_repo = ItemRepo(test_db)

    v_repo.create("V1", "Balaji Foods", [], "36ABCDE1234F1Z5", "balaji.in", 1)
    po_repo.create("PO-1", "V1", "2026-10-01", 500.0, "INR", "OPEN")
    
    emb_veg = embedder.embed_text("Veg Burger 150g")
    item_repo.create("PO-1", "Veg Burger", "150g crispy patty", 5.0, 5.0, 100.0, embedding=emb_veg)
    
    emb_chicken = embedder.embed_text("Chicken Burger 200g")
    item_repo.create("PO-1", "Chicken Burger", "200g grilled", 5.0, 5.0, 120.0, embedding=emb_chicken)

    index = InMemoryItemIndex(embedder)
    index.build_from_db(test_db)

    results = index.search("Veg Burger", top_k=2)
    assert len(results) > 0
    assert results[0][0]["item_name"] == "Veg Burger"
    assert results[0][1] > 0.5


def test_chronological_prior_billed_quantities(test_db):
    v_repo = VendorRepo(test_db)
    po_repo = PORepo(test_db)
    item_repo = ItemRepo(test_db)
    inv_repo = InvoiceRepo(test_db)

    v_repo.create("V-QTY", "Zenith Micro Systems", approved=1)
    po_repo.create("PO-QTY", "V-QTY", "2026-09-01", 10000.0, "INR", "OPEN")
    row_id = item_repo.create("PO-QTY", "USB-C Cable 1m", "Cable", 100.0, 100.0, 100.0)

    # First invoice: 80 pcs
    inv_id_1 = inv_repo.create(
        "V-QTY", "ZNT-1", "ZNT1", "2026-09-27", 8000.0, "INR", "PO-QTY", "EXPLICIT", "APPROVED", "{}"
    )
    inv_repo.add_line(inv_id_1, row_id, "USB-C Cable 1m", 80.0, 100.0, 8000.0)

    # Second invoice: 30 pcs
    inv_id_2 = inv_repo.create(
        "V-QTY", "ZNT-2", "ZNT2", "2026-10-12", 3000.0, "INR", "PO-QTY", "EXPLICIT", "PENDING_REVIEW", "{}"
    )
    inv_repo.add_line(inv_id_2, row_id, "USB-C Cable 1m", 30.0, 100.0, 3000.0)

    # For Invoice 1: prior billed must be 0, available must be 100
    items_for_inv1 = item_repo.list_by_po("PO-QTY", exclude_invoice_id=inv_id_1)
    assert items_for_inv1[0]["prior_billed_qty"] == 0.0
    assert items_for_inv1[0]["qty_remaining"] == 100.0
    consumed_for_inv1 = inv_repo.get_po_consumed_amount("PO-QTY", exclude_invoice_id=inv_id_1)
    assert consumed_for_inv1 == 0.0

    # For Invoice 2: prior billed must be 80, available must be 20
    items_for_inv2 = item_repo.list_by_po("PO-QTY", exclude_invoice_id=inv_id_2)
    assert items_for_inv2[0]["prior_billed_qty"] == 80.0
    assert items_for_inv2[0]["qty_remaining"] == 20.0
    consumed_for_inv2 = inv_repo.get_po_consumed_amount("PO-QTY", exclude_invoice_id=inv_id_2)
    assert consumed_for_inv2 == 8000.0
