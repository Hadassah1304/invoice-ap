from __future__ import annotations

from types import SimpleNamespace
import fitz
import pytest

from render.formatting import format_currency, format_number
from render.layouts import get_layout_renderer


def make_dummy_document(line_count: int = 1, grand_total: float = 2500.0, omit_fields: list = None, omit_label: bool = False):
    lines = []
    for i in range(1, line_count + 1):
        lines.append(
            SimpleNamespace(
                line_no=i,
                description=f"Item {i} Sample Widget",
                qty=2,
                uom="pcs",
                unit_price=100.0,
                line_total=200.0,
                tax_rate=5.0,
            )
        )

    return SimpleNamespace(
        title="TAX INVOICE",
        document_type="invoice",
        vendor_block=SimpleNamespace(
            name="Alpha Supplies Ltd",
            gstin="27ABCDE1234F1Z5",
            email="sales@alphasupplies.com",
            phone="+91-9876543210",
            address="123 Industrial Estate, Mumbai",
            bank_account="HDFC00012345678",
        ),
        invoice_number="INV/2026/001",
        invoice_date="2026-10-15",
        due_date="2026-11-15",
        po_reference="PO-TEST-100",
        currency="INR",
        lines=lines,
        subtotal=200.0 * line_count,
        tax_total=10.0 * line_count,
        grand_total=grand_total,
        omit=SimpleNamespace(fields=omit_fields or [], omit_label=omit_label),
        flags=SimpleNamespace(ambiguous_date=False),
    )


@pytest.mark.parametrize("layout_name", ["itemised", "bundled", "tax_embedded", "multi_page"])
def test_layout_single_line(tmp_path, layout_name):
    doc_data = make_dummy_document(line_count=1, grand_total=210.0)
    render_conf = SimpleNamespace(
        layout=layout_name,
        degrade="none",
        number_format="plain",
        currency_style="Rs.",
        date_style="dmy_slash",
    )
    pdf_path = tmp_path / f"test_{layout_name}_1line.pdf"
    renderer = get_layout_renderer(layout_name)
    bboxes = renderer(doc_data, render_conf, str(pdf_path))

    # Verify bounding boxes returned
    assert "invoice_number" in bboxes
    assert "date" in bboxes
    assert "grand_total" in bboxes
    assert "vendor_block" in bboxes

    # Verify digital PDF text layer
    doc = fitz.open(str(pdf_path))
    assert len(doc) == 1
    text = doc[0].get_text()
    doc.close()

    assert len(text) > 80
    assert "Alpha Supplies Ltd" in text
    assert "INV/2026/001" in text
    assert "210.00" in text


@pytest.mark.parametrize("layout_name", ["itemised", "bundled", "tax_embedded"])
def test_layout_six_lines(tmp_path, layout_name):
    doc_data = make_dummy_document(line_count=6, grand_total=1260.0)
    render_conf = SimpleNamespace(
        layout=layout_name,
        degrade="none",
        number_format="indian",
        currency_style="₹",
        date_style="dmy_mon",
    )
    pdf_path = tmp_path / f"test_{layout_name}_6lines.pdf"
    renderer = get_layout_renderer(layout_name)
    bboxes = renderer(doc_data, render_conf, str(pdf_path))

    doc = fitz.open(str(pdf_path))
    text = doc[0].get_text()
    doc.close()

    assert len(text) > 80
    assert "1,260.00" in text
    assert "15-Oct-2026" in text


def test_layout_multi_page_nine_lines(tmp_path):
    doc_data = make_dummy_document(line_count=9, grand_total=1890.0)
    render_conf = SimpleNamespace(
        layout="multi_page",
        degrade="none",
        number_format="plain",
        currency_style="Rs.",
        date_style="dmy_slash",
    )
    pdf_path = tmp_path / "test_multi_page_9lines.pdf"
    renderer = get_layout_renderer("multi_page")
    bboxes = renderer(doc_data, render_conf, str(pdf_path))

    doc = fitz.open(str(pdf_path))
    assert len(doc) == 2, "Multi-page with 9 lines must produce 2 pages"

    p1_text = doc[0].get_text()
    p2_text = doc[1].get_text()
    doc.close()

    assert "Continued on next page" in p1_text
    assert "Page 1 of 2" in p1_text

    # Totals block must be ONLY on the last page!
    assert "Grand Total" not in p1_text
    assert "Grand Total" in p2_text
    assert "1890.00" in p2_text
    assert "Page 2 of 2" in p2_text


def test_layout_null_totals_and_omitted_labels(tmp_path):
    # Null totals and omitted labels
    doc_data = make_dummy_document(line_count=2, grand_total=None, omit_fields=["grand_total", "invoice_number"], omit_label=True)
    doc_data.grand_total = None
    doc_data.subtotal = None
    doc_data.tax_total = None

    render_conf = SimpleNamespace(
        layout="itemised",
        degrade="none",
        number_format="plain",
        currency_style="Rs.",
        date_style="dmy_slash",
    )
    pdf_path = tmp_path / "test_omitted.pdf"
    renderer = get_layout_renderer("itemised")
    bboxes = renderer(doc_data, render_conf, str(pdf_path))

    doc = fitz.open(str(pdf_path))
    text = doc[0].get_text()
    doc.close()

    # Omitted labels must NOT be present
    assert "Invoice No:" not in text
    assert "Grand Total:" not in text
