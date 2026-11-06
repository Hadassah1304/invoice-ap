import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import InvoiceRepo, PORepo, VendorRepo
from server.main import app


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test_server.db")
    init_db(db_path)
    conn = get_connection(db_path)
    VendorRepo(conn).create("V001", "Acme Test Corp", approved=1)
    PORepo(conn).create("PO-TEST-01", "V001", "2026-10-01", 1000.0, status="OPEN")
    conn.close()

    from server.deps import get_config, get_db
    from invoice_pipeline.config import PipelineConfig

    cfg = PipelineConfig(app={"db_path": db_path})
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_db] = lambda: get_connection(db_path)

    tc = TestClient(app)
    yield tc
    app.dependency_overrides.clear()


def test_health_and_config(client):
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "healthy"

    r_cfg = client.get("/api/config")
    assert r_cfg.status_code == 200
    assert "ocr" in r_cfg.json()


def test_server_list_and_resolve(client, tmp_path):
    # Check empty list
    r_list = client.get("/api/invoices")
    assert r_list.status_code == 200
    assert isinstance(r_list.json(), list)

    # Insert a dummy pending invoice
    cfg = client.app.dependency_overrides[list(client.app.dependency_overrides.keys())[0]]()
    conn = get_connection(cfg.app.db_path)
    inv_repo = InvoiceRepo(conn)
    dummy_dec = {
        "request_id": "test-req-1",
        "decision": "NEEDS_REVIEW",
        "reason_code": "AMBIGUOUS_PO",
        "confidence": 0.5,
        "summary": "Ambiguous PO",
        "reasoning": ["Needs review"],
        "cost": {"llm_input_tokens": 0, "llm_output_tokens": 0},
        "extracted": {
            "source": {"file_name": "INV-SRV-01.pdf", "page_count": 1, "file_hash": "dummyhash", "extraction_method": "pdf_text"},
            "vendor": {"name": "Acme Test Corp"},
            "invoice_number": {"value": "INV-SRV-01"},
            "invoice_date": {"value": "2026-10-15"},
            "currency": {"value": "INR"},
            "grand_total": {"value": 500.0},
            "line_items": [{"line_no": 1, "description": "Item 1", "quantity": 5.0, "unit_price": 100.0, "line_total": 500.0}],
            "document_type": "invoice",
        },
    }
    inv_id = inv_repo.create(
        vendor_id="V001",
        invoice_no_raw="INV-SRV-01",
        invoice_no_norm="INVSRV01",
        invoice_date="2026-10-15",
        total=500.0,
        currency="INR",
        po_id="PO-TEST-01",
        match_method="EXPLICIT",
        status="PENDING_REVIEW",
        decision_json=json.dumps(dummy_dec),
    )
    conn.close()

    # Reject endpoint
    r_reject = client.post(f"/api/invoices/{inv_id}/resolve", json={"action": "reject", "note": "Rejected"})
    assert r_reject.status_code == 200, f"Error: {r_reject.json()}"
    assert r_reject.json()["decision"] == "REJECTED"
