import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import DecisionEnum, ReasonCodeEnum
from invoice_pipeline.pipeline import process_invoice_batch
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import InvoiceRepo, PORepo, VendorRepo
from server.main import app


@pytest.fixture
def test_setup(tmp_path):
    db_path = str(tmp_path / "test_batch.db")
    upload_dir = str(tmp_path / "uploads")
    init_db(db_path)
    conn = get_connection(db_path)
    VendorRepo(conn).create("V001", "Acme Test Corp", approved=1)
    PORepo(conn).create("PO-TEST-01", "V001", "2026-10-01", 1000.0, status="OPEN")
    conn.close()

    cfg = PipelineConfig(app={"db_path": db_path, "upload_dir": upload_dir})
    from server.deps import get_config, get_db

    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_db] = lambda: get_connection(db_path)

    tc = TestClient(app)
    yield tc, cfg, tmp_path
    app.dependency_overrides.clear()


def test_pos_endpoints_enriched(test_setup):
    client, cfg, tmp_path = test_setup
    conn = get_connection(cfg.app.db_path)
    inv_repo = InvoiceRepo(conn)

    dummy_dec = {
        "request_id": "test-req-1",
        "decision": "APPROVED",
        "reason_code": "OK",
        "confidence": 0.95,
        "summary": "Match OK",
        "reasoning": [],
        "cost": {"llm_input_tokens": 0, "llm_output_tokens": 0},
    }
    inv_id = inv_repo.create(
        vendor_id="V001",
        invoice_no_raw="INV-001",
        invoice_no_norm="INV001",
        invoice_date="2026-10-10",
        total=250.0,
        currency="INR",
        po_id="PO-TEST-01",
        match_method="EXPLICIT",
        status="APPROVED",
        decision_json=json.dumps(dummy_dec),
    )
    conn.close()

    # Test GET /api/pos
    r_pos = client.get("/api/pos")
    assert r_pos.status_code == 200
    pos_data = r_pos.json()
    assert len(pos_data) >= 1
    target = next((p for p in pos_data if p["po_id"] == "PO-TEST-01"), None)
    assert target is not None
    assert target["vendor_name"] == "Acme Test Corp"
    assert target["total_budget"] == 1000.0
    assert target["billed_approved"] == 250.0
    assert target["remaining_balance"] == 750.0
    assert target["linked_invoices_count"] == 1

    # Test GET /api/pos/{po_id}
    r_detail = client.get("/api/pos/PO-TEST-01")
    assert r_detail.status_code == 200
    detail_data = r_detail.json()
    assert detail_data["po"]["po_id"] == "PO-TEST-01"
    assert detail_data["balance"]["remaining_balance"] == 750.0
    assert len(detail_data["invoices"]) == 1
    assert detail_data["invoices"][0]["invoice_no_raw"] == "INV-001"
    assert detail_data["invoices"][0]["confidence"] == 0.95


def test_process_invoice_batch_fault_isolation(test_setup, monkeypatch):
    client, cfg, tmp_path = test_setup

    f1 = tmp_path / "invoice_1.pdf"
    f1.write_text("valid dummy")
    f_err = tmp_path / "invoice_err.pdf"
    f_err.write_text("err dummy")

    import invoice_pipeline.pipeline as pipe_mod
    orig_process = pipe_mod.process_invoice

    def mock_process(file_path, **kwargs):
        if "err" in str(file_path):
            raise RuntimeError("Corrupted PDF stream syntax")
        return orig_process(file_path, **kwargs)

    monkeypatch.setattr(pipe_mod, "process_invoice", mock_process)

    batch_res = process_invoice_batch(
        file_paths=[f1, f_err],
        config=cfg,
        dry_run=True,
    )
    assert batch_res.total_files == 2
    assert batch_res.processed_count == 2
    assert batch_res.failed_count == 1
    err_item = next(it for it in batch_res.items if it.file_name == "invoice_err.pdf")
    assert err_item.status == "FAILED"
    assert "Corrupted PDF stream syntax" in err_item.error_message


def test_api_batch_upload(test_setup):
    client, cfg, tmp_path = test_setup

    files = [
        ("files", ("inv1.pdf", b"%PDF-1.4 dummy 1", "application/pdf")),
        ("files", ("inv2.pdf", b"%PDF-1.4 dummy 2", "application/pdf")),
    ]

    res = client.post("/api/invoices/batch?dry_run=true", files=files)
    assert res.status_code == 200
    data = res.json()
    assert "batch_id" in data
    assert data["total_files"] == 2
    assert len(data["items"]) == 2


def test_process_invoice_stream_endpoint(test_setup):
    client, cfg, tmp_path = test_setup
    files = {"file": ("stream_inv.pdf", b"%PDF-1.4 dummy single stream", "application/pdf")}

    res = client.post("/api/invoices/process/stream?dry_run=true", files=files)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    events = []
    for line in res.iter_lines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
            events.append(payload)

    # Must contain progress events and complete event
    progress_stages = [e["stage"] for e in events if e.get("type") == "progress"]
    assert "ingest" in progress_stages
    complete_events = [e for e in events if e.get("type") == "complete"]
    assert len(complete_events) == 1
    assert "result" in complete_events[0]


def test_process_batch_stream_endpoint(test_setup):
    client, cfg, tmp_path = test_setup
    files = [
        ("files", ("stream_b1.pdf", b"%PDF-1.4 dummy batch 1", "application/pdf")),
        ("files", ("stream_b2.pdf", b"%PDF-1.4 dummy batch 2", "application/pdf")),
    ]

    res = client.post("/api/invoices/batch/stream?dry_run=true", files=files)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    events = []
    for line in res.iter_lines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
            events.append(payload)

    types = [e.get("type") for e in events]
    assert "file_start" in types
    assert "file_done" in types
    assert "batch_done" in types

    file_done_events = [e for e in events if e.get("type") == "file_done"]
    assert len(file_done_events) == 2
    assert file_done_events[0]["stats"]["total_files"] == 2
