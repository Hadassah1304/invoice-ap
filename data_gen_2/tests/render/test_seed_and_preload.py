from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from invoice_pipeline.store.embeddings import get_embedder
from seed.build_seed import build_seed_json
from seed.load_dataset import load_dataset_into_db


def test_embeddings_properties():
    embedder = get_embedder("tfidf")
    vec1 = embedder.embed_text("Test Widget 10g")
    vec2 = embedder.embed_text("Test Widget 10g")

    assert isinstance(vec1, np.ndarray)
    assert vec1.shape == (256,)
    assert vec1.dtype == np.float32 or vec1.dtype == np.float64
    assert np.allclose(vec1, vec2), "TF-IDF embeddings must be deterministic"


def test_seed_and_preload_round_trip(tmp_path):
    # Minimal fixture matching contract section 10
    state_data = {
        "meta": {"reference_date": "2026-11-06", "seed": 42},
        "vendors": [
            {
                "vendor_id": "V-TEST",
                "name": "Test Vendor Pvt Ltd",
                "aliases": ["Test Vendor"],
                "gstin": "27AAAAA0000A1Z5",
                "email_domain": "testvendor.in",
                "phone": "+91 9876543210",
                "address": "123 Industrial Area, Mumbai",
                "approved": True,
                "bank_account": "HDFC00011112222",
                "owner_family": "R",
            }
        ],
        "catalog": [
            {
                "sku": "SKU-900",
                "name": "Test Widget 10g",
                "description": "Standard 10g testing widget",
                "uom": "pcs",
                "unit_price": 100.0,
                "tax_rate": 5.0,
                "category": "hardware",
                "twin_group": None,
                "distinguisher": None,
                "reworded": [],
                "unique_item": True,
            }
        ],
        "purchase_orders": [
            {
                "po_id": "PO-R-TEST",
                "vendor_id": "V-TEST",
                "po_date": "2026-09-22",
                "currency": "INR",
                "status": "PARTIAL",
                "payment_terms_days": 30,
                "group": "test",
                "subtotal": 1000.0,
                "tax_total": 50.0,
                "total": 1050.0,
                "lines": [
                    {
                        "line_no": 1,
                        "sku": "SKU-900",
                        "item_name": "Test Widget 10g",
                        "description": "Standard 10g testing widget",
                        "uom": "pcs",
                        "qty_ordered": 10,
                        "qty_remaining": 6,
                        "unit_price": 100.0,
                        "tax_rate": 5.0,
                        "line_total": 1000.0,
                    }
                ],
            }
        ],
        "ledger_preload": [
            {
                "preload_id": "LP-R-TEST-1",
                "po_id": "PO-R-TEST",
                "vendor_id": "V-TEST",
                "invoice_no": "TST/26/101",
                "invoice_no_norm": "TST26101",
                "invoice_date": "2026-10-10",
                "currency": "INR",
                "subtotal": 400.0,
                "tax_total": 20.0,
                "total": 420.0,
                "lines": [
                    {
                        "po_line_no": 1,
                        "description": "Test Widget 10g",
                        "qty": 4,
                        "unit_price": 100.0,
                        "line_total": 400.0,
                    }
                ],
            }
        ],
    }

    state_path = tmp_path / "state.json"
    with open(state_path, "w") as f:
        json.dump(state_data, f)

    seed_path = tmp_path / "seed.json"
    build_seed_json(str(state_path), str(seed_path), embedder_backend="tfidf")
    assert seed_path.exists()

    # Load seed into temporary SQLite DB
    db_path = tmp_path / "test_pipeline.db"
    counts = load_dataset_into_db(str(seed_path), str(db_path), reset=True)

    assert counts["vendors"] == 1
    assert counts["pos"] == 1
    assert counts["items"] == 1
    assert counts["preloaded_invoices"] == 1
