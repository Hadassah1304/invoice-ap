from __future__ import annotations

import json
from types import SimpleNamespace
from invoice_pipeline.models import ExtractedInvoice
from render.extracted_json import build_extracted_invoice, save_extracted_json
from tests.render.test_layouts import make_dummy_document


def test_extracted_json_validates_against_pipeline_model(tmp_path):
    doc_data = make_dummy_document(line_count=2, grand_total=420.0)
    ext = build_extracted_invoice(
        document=doc_data,
        file_name="test_01.pdf",
        file_hash="deadbeef1234",
        page_count=1,
    )

    assert isinstance(ext, ExtractedInvoice)
    assert ext.source.file_name == "test_01.pdf"
    assert ext.source.file_hash == "deadbeef1234"
    assert ext.source.extraction_method == "synthetic"
    assert ext.source.ocr_confidence == 1.0

    assert ext.vendor.name == "Alpha Supplies Ltd"
    assert ext.vendor.gstin == "27ABCDE1234F1Z5"
    assert ext.invoice_number.value == "INV/2026/001"
    assert ext.invoice_number.confidence == 1.0
    assert ext.grand_total.value == 420.0
    assert len(ext.line_items) == 2
    assert ext.missing_fields == []

    out_file = tmp_path / "test.extracted.json"
    save_extracted_json(ext, str(out_file))
    assert out_file.exists()

    with open(out_file, "r") as f:
        reloaded = json.load(f)
    validated = ExtractedInvoice.model_validate(reloaded)
    assert validated.grand_total.value == 420.0


def test_extracted_json_omitted_fields():
    doc_data = make_dummy_document(line_count=1, grand_total=100.0, omit_fields=["invoice_number", "vendor"])
    ext = build_extracted_invoice(
        document=doc_data,
        file_name="test_omit.pdf",
        file_hash="hash000",
        page_count=1,
    )
    assert "invoice_number" in ext.missing_fields
    assert "vendor" in ext.missing_fields
    assert ext.invoice_number.value is None
    assert ext.invoice_number.confidence == 0.0
