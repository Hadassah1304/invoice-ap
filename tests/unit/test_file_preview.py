import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import InvoiceRepo, PORepo, VendorRepo
from server.main import app


@pytest.fixture
def preview_setup(tmp_path):
    db_path = str(tmp_path / "test_preview.db")
    upload_dir = str(tmp_path / "uploads")
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    conn = get_connection(db_path)
    VendorRepo(conn).create("V001", "Acme Corporation", approved=1)
    PORepo(conn).create("PO-100", "V001", "2026-10-01", 1000.0, status="OPEN")
    conn.close()

    cfg = PipelineConfig(app={"db_path": db_path, "upload_dir": upload_dir})
    from server.deps import get_config, get_db

    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_db] = lambda: get_connection(db_path)

    tc = TestClient(app)
    yield tc, cfg, tmp_path
    app.dependency_overrides.clear()


def test_file_preview_endpoint(preview_setup):
    client, cfg, tmp_path = preview_setup
    upload_dir = Path(cfg.app.upload_dir)

    # 1. Create a physical PDF file
    pdf_file = upload_dir / "sample_invoice.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock content for preview test")

    # 2. Insert invoice with file_name and file_path
    conn = get_connection(cfg.app.db_path)
    inv_repo = InvoiceRepo(conn)
    inv_id = inv_repo.create(
        vendor_id="V001",
        invoice_no_raw="INV-999",
        invoice_no_norm="INV999",
        invoice_date="2026-10-20",
        total=500.0,
        currency="INR",
        po_id="PO-100",
        match_method="EXPLICIT",
        status="APPROVED",
        decision_json="{}",
        file_name="sample_invoice.pdf",
        file_path=str(pdf_file.resolve()),
    )
    conn.close()

    # 3. Test GET /api/invoices/{invoice_id}/file
    res = client.get(f"/api/invoices/{inv_id}/file")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert "inline" in res.headers["content-disposition"]
    assert "sample_invoice.pdf" in res.headers["content-disposition"]
    assert res.content == b"%PDF-1.4 mock content for preview test"


def test_file_preview_synthetic_fallback(preview_setup):
    client, cfg, tmp_path = preview_setup

    # Insert invoice without any physical file
    conn = get_connection(cfg.app.db_path)
    inv_repo = InvoiceRepo(conn)
    inv_id = inv_repo.create(
        vendor_id="V001",
        invoice_no_raw="INV-SYNTHETIC",
        invoice_no_norm="INVSYNTHETIC",
        invoice_date="2026-10-20",
        total=300.0,
        currency="INR",
        po_id="PO-100",
        match_method="EXPLICIT",
        status="APPROVED",
        decision_json="{}",
        file_name=None,
        file_path=None,
    )
    conn.close()

    res = client.get(f"/api/invoices/{inv_id}/file")
    assert res.status_code == 404
    assert "No physical document file found" in res.json()["detail"]


def test_upload_persists_file_path(preview_setup, monkeypatch):
    client, cfg, tmp_path = preview_setup

    sample_pdf = Path("samples/inv_01_happy.pdf")
    if not sample_pdf.exists():
        pytest.skip("Sample PDF not found")

    from invoice_pipeline.extract.extractor import Extractor
    from invoice_pipeline.models import ExtractedInvoice, ExtractedVendor, ExtractionSource, FieldValue

    canned = ExtractedInvoice(
        source=ExtractionSource(file_name="test_inv.pdf", file_hash="dummyhash", extraction_method="pdf_text"),
        vendor=ExtractedVendor(name="Acme Corporation"),
        invoice_number=FieldValue(value="INV-UPLOAD-1"),
        invoice_date=FieldValue(value="2026-10-25"),
        grand_total=FieldValue(value=500.0),
        currency=FieldValue(value="INR"),
        document_type="invoice",
    )
    monkeypatch.setattr(Extractor, "extract", lambda *args, **kwargs: (canned, 10, 10))

    file_bytes = sample_pdf.read_bytes()
    files = {"file": ("test_inv.pdf", file_bytes, "application/pdf")}
    res = client.post("/api/invoices/process?dry_run=false", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data.get("invoice_id") is not None
    inv_id = data["invoice_id"]

    # Verify database has file_path and file_name populated
    conn = get_connection(cfg.app.db_path)
    cur = conn.execute("SELECT file_name, file_path FROM invoices WHERE invoice_id = ?", (inv_id,))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row["file_name"] is not None
    assert row["file_path"] is not None
    assert Path(row["file_path"]).exists()

    # Verify preview endpoint returns the uploaded file
    file_res = client.get(f"/api/invoices/{inv_id}/file")
    assert file_res.status_code == 200
    assert file_res.content == file_bytes
