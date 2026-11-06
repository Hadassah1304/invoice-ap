from __future__ import annotations

import fitz
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from render.formatting import format_currency, format_date, format_number
from render.pdf import get_font_for_text


def test_format_number_plain():
    assert format_number(1837.5) == "1837.50"
    assert format_number(100000.0) == "100000.00"
    assert format_number(0) == "0.00"
    assert format_number(None) == ""


def test_format_number_indian():
    # 3 digits
    assert format_number(500.0, "indian") == "500.00"
    # 4 digits
    assert format_number(1837.5, "indian") == "1,837.50"
    # 5 digits
    assert format_number(10000.0, "indian") == "10,000.00"
    # 6 digits (1 Lakh)
    assert format_number(100000.0, "indian") == "1,00,000.00"
    # 7 digits (10 Lakhs)
    assert format_number(1000000.0, "indian") == "10,00,000.00"
    # 8 digits (1 Crore)
    assert format_number(10000000.0, "indian") == "1,00,00,000.00"


def test_format_number_eu():
    assert format_number(1837.5, "eu") == "1.837,50"
    assert format_number(100000.0, "eu") == "100.000,00"
    assert format_number(1000000.0, "eu") == "1.000.000,00"


def test_format_number_negatives():
    assert format_number(-1837.5, "plain") == "-1837.50"
    assert format_number(-1837.5, "indian") == "-1,837.50"
    assert format_number(-100000.0, "indian") == "-1,00,000.00"
    assert format_number(-1837.5, "eu") == "-1.837,50"


def test_format_currency():
    assert format_currency(1837.5, "Rs.", "INR", "indian") == "Rs. 1,837.50"
    assert format_currency(1837.5, "₹", "INR", "indian") == "₹1,837.50"
    assert format_currency(1837.5, "INR", "INR", "plain") == "INR 1837.50"
    assert format_currency(1837.5, "$", "USD", "plain") == "$1837.50"
    assert format_currency(1837.5, "USD", "USD", "plain") == "USD 1837.50"

    # Negatives
    assert format_currency(-1837.5, "Rs.", "INR", "indian") == "Rs. -1,837.50"
    assert format_currency(-1837.5, "₹", "INR", "indian") == "₹-1,837.50"


def test_format_date():
    assert format_date("2026-11-06", "dmy_slash") == "06/11/2026"
    assert format_date("2026-11-06", "dmy_mon") == "06-Nov-2026"
    assert format_date("2026-11-06", "iso") == "2026-11-06"
    assert format_date(None) == ""


def test_rupee_glyph_rendering(tmp_path):
    pdf_path = tmp_path / "rupee_test.pdf"
    font = get_font_for_text("₹1,837.50")
    assert font == "NotoSans"

    c = canvas.Canvas(str(pdf_path), pagesize=letter, invariant=1)
    c.setFont(font, 14)
    c.drawString(100, 700, "Grand Total: ₹1,837.50")
    c.save()

    doc = fitz.open(str(pdf_path))
    extracted = doc[0].get_text()
    doc.close()
    assert "₹1,837.50" in extracted
