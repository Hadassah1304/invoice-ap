from __future__ import annotations

import pytest
from invoice_pipeline.config import MatchingConfig
from invoice_pipeline.matching.item_matcher import ItemMatcher
from invoice_pipeline.store.embeddings import TFIDFCharEmbedder


def test_near_twin_number_and_uom_guards():
    cfg = MatchingConfig()
    embedder = TFIDFCharEmbedder()
    matcher = ItemMatcher(config=cfg.line_match, embedder=embedder)

    po_items = [
        {"row_id": 1, "item_name": "Mineral Water 1L", "description": "Packaged mineral water 1L bottle", "unit_price": 30.0, "qty_remaining": 10.0, "uom": "bottle"},
        {"row_id": 2, "item_name": "A4 Paper 70gsm Ream", "description": "A4 Copier Paper 70gsm 500 sheets", "unit_price": 250.0, "qty_remaining": 10.0, "uom": "ream"},
        {"row_id": 3, "item_name": "Chicken Burger 150g", "description": "Grilled seasoned chicken burger 150g", "unit_price": 180.0, "qty_remaining": 10.0, "uom": "pcs"},
        {"row_id": 4, "item_name": "Veg Burger 150g", "description": "Crispy vegetable burger 150g", "unit_price": 120.0, "qty_remaining": 10.0, "uom": "pcs"},
    ]

    # Pre-embed po items
    for it in po_items:
        it["embedding"] = embedder.embed_text(it["item_name"])

    # 1. "Mineral Water 500ml" must NOT match "Mineral Water 1L"
    m1 = matcher.match_line_to_po_items(1, "Mineral Water 500ml", po_items)
    assert m1.po_item_row_id != 1, f"500ml incorrectly matched 1L with method {m1.method}"

    # 2. "A4 Paper 80gsm Ream" must NOT match "A4 Paper 70gsm Ream"
    m2 = matcher.match_line_to_po_items(2, "A4 Paper 80gsm Ream", po_items)
    assert m2.po_item_row_id != 2, f"80gsm incorrectly matched 70gsm with method {m2.method}"

    # 3. "Veg Burger 150g" must NOT match "Chicken Burger 150g"
    m3 = matcher.match_line_to_po_items(3, "Veg Burger 150g", [po_items[2]])
    assert m3.po_item_row_id is None, f"Veg Burger matched Chicken Burger with method {m3.method}"

    # 4. Genuine rewording: "Vegetable Burger 150g" SHOULD match "Veg Burger 150g"
    m4 = matcher.match_line_to_po_items(4, "Vegetable Burger 150g", [po_items[3]])
    assert m4.po_item_row_id == 4, "Vegetable Burger 150g failed to match Veg Burger 150g"
