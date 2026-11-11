import pytest
from invoice_pipeline.config import MatchingConfig
from invoice_pipeline.matching.router import MatchingRouter
from invoice_pipeline.models import ExtractedLineItem, ReasonCodeEnum
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.embeddings import TFIDFCharEmbedder
from invoice_pipeline.store.index import InMemoryItemIndex
from invoice_pipeline.store.repositories import ItemRepo, PORepo, VendorRepo


@pytest.fixture
def db_with_three_burgers(tmp_path):
    db_file = str(tmp_path / "burgers.db")
    init_db(db_file)
    conn = get_connection(db_file)

    v_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)
    embedder = TFIDFCharEmbedder()

    # Vendor V1
    v_repo.create("V1", "Burger Town", aliases=["Burger Town Inc"], gstin="29AAAAA0000A1Z5")

    # 3 POs with burger items
    # PO-A: 5 burgers total, qty remaining 5, total 500
    po_repo.create("PO-A", "V1", "2026-10-01", 500.0, "INR", "OPEN")
    emb_a = embedder.embed_text("Veg Burger 150g")
    item_repo.create("PO-A", "Veg Burger", "150g", 5.0, 5.0, 100.0, embedding=emb_a)

    # PO-B: 2 burgers total, qty remaining 2, total 200
    po_repo.create("PO-B", "V1", "2026-10-01", 200.0, "INR", "OPEN")
    emb_b = embedder.embed_text("Veg Burger 150g")
    item_repo.create("PO-B", "Veg Burger", "150g", 2.0, 2.0, 100.0, embedding=emb_b)

    # PO-C: 10 burgers, total 1000, CLOSED
    po_repo.create("PO-C", "V1", "2026-09-01", 1000.0, "INR", "CLOSED")
    emb_c = embedder.embed_text("Veg Burger 150g")
    item_repo.create("PO-C", "Veg Burger", "150g", 10.0, 0.0, 100.0, embedding=emb_c)

    index = InMemoryItemIndex(embedder)
    index.build_from_db(conn)

    yield conn, embedder, index
    conn.close()


def test_tier1_explicit(db_with_three_burgers):
    conn, embedder, index = db_with_three_burgers
    cfg = MatchingConfig()
    cfg.tier2.min_margin = 0.10
    router = MatchingRouter(conn, cfg, embedder, index)

    lines = [ExtractedLineItem(line_no=1, description="Veg Burger", quantity=2, unit_price=100, line_total=200)]
    vendor = {"vendor_id": "V1", "name": "Burger Town"}

    res, reason, msg = router.route_match("PO-A", vendor, lines, 200.0, "2026-10-15")
    assert res.selected_po == "PO-A"
    assert res.method.value == "EXPLICIT"
    assert reason is None


def test_tier1_closed_po(db_with_three_burgers):
    conn, embedder, index = db_with_three_burgers
    cfg = MatchingConfig()
    cfg.tier2.min_margin = 0.10
    router = MatchingRouter(conn, cfg, embedder, index)

    lines = [ExtractedLineItem(line_no=1, description="Veg Burger", quantity=2, unit_price=100, line_total=200)]
    vendor = {"vendor_id": "V1", "name": "Burger Town"}

    res, reason, msg = router.route_match("PO-C", vendor, lines, 200.0, "2026-10-15")
    assert reason == ReasonCodeEnum.PO_CLOSED


def test_tier2_inferred_clear_winner(db_with_three_burgers):
    conn, embedder, index = db_with_three_burgers
    cfg = MatchingConfig()
    cfg.tier2.min_margin = 0.10
    router = MatchingRouter(conn, cfg, embedder, index)

    # Invoicing exactly 200 for 2 burgers -> PO-B remaining is 200, PO-A is 500
    # PO-B has exact total coverage 1.0, PO-A has 200/500 ratio
    lines = [ExtractedLineItem(line_no=1, description="Veg Burger", quantity=2, unit_price=100, line_total=200)]
    vendor = {"vendor_id": "V1", "name": "Burger Town"}

    res, reason, msg = router.route_match(None, vendor, lines, 200.0, "2026-10-15")
    assert res.selected_po == "PO-B"
    assert res.method.value == "INFERRED_VENDOR"


def test_tier1_typo_fuzzy_match_needs_review(db_with_three_burgers):
    conn, embedder, index = db_with_three_burgers
    cfg = MatchingConfig()
    cfg.tier1.fuzzy_threshold = 75.0
    router = MatchingRouter(conn, cfg, embedder, index)

    lines = [ExtractedLineItem(line_no=1, description="Veg Burger", quantity=2, unit_price=100, line_total=200)]
    vendor = {"vendor_id": "V1", "name": "Burger Town"}

    # Typo on PO-A: "PO-AA" (fuzz.ratio("PO-AA", "PO-A") is 80% >= 75%)
    res, reason, msg = router.route_match("PO-AA", vendor, lines, 200.0, "2026-10-15")
    assert reason == ReasonCodeEnum.INVALID_PO_REF
    assert len(res.candidates) > 0
    candidate_ids = [c.po_id for c in res.candidates]
    assert "PO-A" in candidate_ids
    # Line items should be scored
    po_a_cand = next(c for c in res.candidates if c.po_id == "PO-A")
    assert po_a_cand.score > 0.5
    assert len(po_a_cand.line_matches) == 1
    assert "PO-A" in msg


def test_tier1_nonexistent_po_directly_rejected(db_with_three_burgers):
    conn, embedder, index = db_with_three_burgers
    cfg = MatchingConfig()
    cfg.tier1.fuzzy_threshold = 75.0
    router = MatchingRouter(conn, cfg, embedder, index)

    lines = [ExtractedLineItem(line_no=1, description="Veg Burger", quantity=2, unit_price=100, line_total=200)]
    vendor = {"vendor_id": "V1", "name": "Burger Town"}

    # Completely non-existent PO
    res, reason, msg = router.route_match("PO-XYZ-99999", vendor, lines, 200.0, "2026-10-15")
    assert reason == ReasonCodeEnum.NO_MATCHING_PO
    assert len(res.candidates) == 0
    assert "not found" in msg.lower()
