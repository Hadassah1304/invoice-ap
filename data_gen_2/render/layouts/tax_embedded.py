from __future__ import annotations

from typing import Any, Dict, Tuple
from reportlab.lib.colors import HexColor

from render.formatting import format_currency, format_date, format_number
from render.pdf import PDFBuilder


def render_tax_embedded_layout(
    document: Any,
    render_config: Any,
    output_path: str,
) -> Dict[str, Tuple[int, float, float, float, float]]:
    """Render the 'tax_embedded' layout:
    A table with tax-inclusive prices exactly as in document.lines.
    Footer says 'All prices inclusive of GST'.
    Totals block shows only the grand total (subtotal and tax lines omitted when null).
    """
    builder = PDFBuilder(output_path)
    omit_fields = document.omit.fields if hasattr(document, "omit") and document.omit else []
    omit_label = document.omit.omit_label if hasattr(document, "omit") and document.omit else False

    currency = getattr(document, "currency", "INR") or "INR"
    curr_style = getattr(render_config, "currency_style", "Rs.")
    num_fmt = getattr(render_config, "number_format", "plain")
    date_fmt = getattr(render_config, "date_style", "dmy_slash")

    margin_left = 40.0
    margin_right = 572.0
    content_width = margin_right - margin_left
    y = 40.0

    # 1. Header & Title (Clean minimalist style)
    title = getattr(document, "title", "TAX INVOICE") or "TAX INVOICE"
    builder.draw_text(margin_left, y, title, font_name="Courier-Bold", font_size=16, color="#000000")
    builder.draw_text(margin_right, y + 2, "[GST INCLUSIVE]", font_name="Courier", font_size=10, color="#475569", align="right")
    y += 20.0
    builder.draw_line(margin_left, y, margin_right, y, stroke_color="#000000", stroke_width=2)
    y += 16.0

    # 2. Vendor Block (Left) and Metadata (Right)
    vb_start_y = y
    vb_x0, vb_y0 = margin_left, y
    vb_x1 = margin_left + 260.0

    vendor_block = getattr(document, "vendor_block", None)
    if "vendor_block" in omit_fields or "vendor" in omit_fields:
        if not omit_label:
            builder.draw_text(vb_x0, y, "VENDOR: [OMITTED]", font_name="Courier", font_size=9, color="#64748B")
            y += 13.0
    elif vendor_block:
        v_name = getattr(vendor_block, "name", None)
        if v_name and "vendor_name" not in omit_fields:
            builder.draw_text(vb_x0, y, v_name, font_name="Courier-Bold", font_size=11, color="#000000")
            y += 15.0
        v_gstin = getattr(vendor_block, "gstin", None)
        if v_gstin and "gstin" not in omit_fields:
            builder.draw_text(vb_x0, y, f"GSTIN: {v_gstin}", font_name="Courier", font_size=9, color="#1E293B")
            y += 13.0
        v_addr = getattr(vendor_block, "address", None)
        if v_addr:
            builder.draw_text(vb_x0, y, f"ADDR : {v_addr[:35]}", font_name="Courier", font_size=8, color="#334155")
            y += 12.0
        v_email = getattr(vendor_block, "email", None)
        if v_email:
            builder.draw_text(vb_x0, y, f"EMAIL: {v_email}", font_name="Courier", font_size=8, color="#334155")
            y += 12.0
        v_phone = getattr(vendor_block, "phone", None)
        if v_phone:
            builder.draw_text(vb_x0, y, f"TEL  : {v_phone}", font_name="Courier", font_size=8, color="#334155")
            y += 12.0
        v_bank = getattr(vendor_block, "bank_account", None)
        if v_bank:
            builder.draw_text(vb_x0, y, f"BANK : {v_bank}", font_name="Courier", font_size=8, color="#334155")
            y += 12.0

    vb_y1 = max(y, vb_y0 + 13.0)
    builder.set_bounding_box("vendor_block", vb_x0, vb_y0, vb_x1, vb_y1)

    # Right side: Invoice Metadata
    meta_x = margin_right - 220.0
    meta_y = vb_start_y

    inv_num = getattr(document, "invoice_number", None)
    if "invoice_number" in omit_fields:
        if not omit_label:
            b = builder.draw_text(meta_x, meta_y, "INVOICE NO: ", font_name="Courier-Bold", font_size=9, color="#000000")
            builder.set_bounding_box("invoice_number", b[0], b[1], b[2] + 20, b[3])
            meta_y += 14.0
    else:
        text = f"INVOICE NO: {inv_num}" if inv_num else "INVOICE NO: "
        b = builder.draw_text(meta_x, meta_y, text, font_name="Courier-Bold", font_size=9, color="#000000")
        builder.set_bounding_box("invoice_number", b[0], b[1], b[2], b[3])
        meta_y += 14.0

    inv_date = getattr(document, "invoice_date", None)
    formatted_date = format_date(inv_date, date_style=date_fmt)
    if "invoice_date" in omit_fields:
        if not omit_label:
            b = builder.draw_text(meta_x, meta_y, "DATE      : ", font_name="Courier", font_size=9, color="#1E293B")
            builder.set_bounding_box("date", b[0], b[1], b[2] + 20, b[3])
            meta_y += 13.0
    else:
        text = f"DATE      : {formatted_date}" if inv_date else "DATE      : "
        b = builder.draw_text(meta_x, meta_y, text, font_name="Courier", font_size=9, color="#1E293B")
        builder.set_bounding_box("date", b[0], b[1], b[2], b[3])
        meta_y += 13.0

    due_date = getattr(document, "due_date", None)
    if due_date:
        builder.draw_text(meta_x, meta_y, f"DUE DATE  : {format_date(due_date, date_style=date_fmt)}", font_name="Courier", font_size=9, color="#1E293B")
        meta_y += 13.0

    po_ref = getattr(document, "po_reference", None)
    if po_ref and "po_reference" not in omit_fields:
        builder.draw_text(meta_x, meta_y, f"PO REF    : {po_ref}", font_name="Courier-Bold", font_size=9, color="#000000")
        meta_y += 13.0

    y = max(y, meta_y) + 20.0

    # 3. Table Header (Tax-inclusive columns)
    col_x = [margin_left, margin_left + 30, margin_left + 250, margin_left + 300, margin_left + 350, margin_left + 450, margin_right]
    builder.draw_line(margin_left, y, margin_right, y, stroke_color="#000000", stroke_width=1)
    y += 4.0
    builder.draw_text(col_x[0], y, "#", font_name="Courier-Bold", font_size=8, color="#000000")
    builder.draw_text(col_x[1], y, "DESCRIPTION", font_name="Courier-Bold", font_size=8, color="#000000")
    builder.draw_text(col_x[2], y, "QTY", font_name="Courier-Bold", font_size=8, color="#000000")
    builder.draw_text(col_x[3], y, "UOM", font_name="Courier-Bold", font_size=8, color="#000000")
    builder.draw_text(col_x[4], y, f"PRICE(INCL.GST)", font_name="Courier-Bold", font_size=8, color="#000000")
    builder.draw_text(col_x[6], y, f"TOTAL(INCL.GST)", font_name="Courier-Bold", font_size=8, color="#000000", align="right")
    y += 12.0
    builder.draw_line(margin_left, y, margin_right, y, stroke_color="#000000", stroke_width=1)
    y += 6.0

    # 4. Table Rows
    lines = getattr(document, "lines", []) or []
    for idx, line in enumerate(lines):
        line_no = getattr(line, "line_no", idx + 1)
        desc = getattr(line, "description", "") or ""
        qty = getattr(line, "qty", 0)
        uom = getattr(line, "uom", "pcs") or "pcs"
        unit_price = getattr(line, "unit_price", 0.0)
        line_total = getattr(line, "line_total", 0.0)

        builder.draw_text(col_x[0], y, str(line_no), font_name="Courier", font_size=8, color="#000000")
        builder.draw_text(col_x[1], y, desc[:32], font_name="Courier", font_size=8, color="#000000")
        builder.draw_text(col_x[2], y, str(qty), font_name="Courier", font_size=8, color="#000000")
        builder.draw_text(col_x[3], y, uom, font_name="Courier", font_size=8, color="#000000")
        builder.draw_text(col_x[4], y, format_number(unit_price, number_format=num_fmt), font_name="Courier", font_size=8, color="#000000")
        builder.draw_text(col_x[6], y, format_number(line_total, number_format=num_fmt), font_name="Courier", font_size=8, color="#000000", align="right")
        y += 14.0

    builder.draw_line(margin_left, y, margin_right, y, stroke_color="#000000", stroke_width=1)
    y += 12.0

    # 5. Totals Block: shows only the grand total (subtotal and tax lines omitted when null)
    tot_label_x = margin_right - 220.0
    tot_val_x = margin_right

    subtotal = getattr(document, "subtotal", None)
    if subtotal is not None and "subtotal" not in omit_fields:
        builder.draw_text(tot_label_x, y, "NET SUBTOTAL :", font_name="Courier", font_size=9, color="#000000")
        builder.draw_text(tot_val_x, y, format_currency(subtotal, curr_style, currency, num_fmt), font_name="Courier", font_size=9, color="#000000", align="right")
        y += 13.0

    tax_total = getattr(document, "tax_total", None)
    if tax_total is not None and "tax_total" not in omit_fields:
        builder.draw_text(tot_label_x, y, "GST AMOUNT   :", font_name="Courier", font_size=9, color="#000000")
        builder.draw_text(tot_val_x, y, format_currency(tax_total, curr_style, currency, num_fmt), font_name="Courier", font_size=9, color="#000000", align="right")
        y += 13.0

    grand_total = getattr(document, "grand_total", None)
    if "grand_total" in omit_fields:
        if not omit_label:
            b = builder.draw_text(tot_label_x, y, "TOTAL DUE    : ", font_name="Courier-Bold", font_size=11, color="#000000")
            builder.set_bounding_box("grand_total", tot_label_x, y, margin_right, y + 16.0)
            y += 18.0
    elif grand_total is not None:
        builder.draw_line(tot_label_x, y, margin_right, y, stroke_color="#000000", stroke_width=1)
        y += 4.0
        builder.draw_text(tot_label_x, y, "TOTAL DUE    :", font_name="Courier-Bold", font_size=11, color="#000000")
        val_str = format_currency(grand_total, curr_style, currency, num_fmt)
        builder.draw_text(tot_val_x, y, val_str, font_name="Courier-Bold", font_size=11, color="#000000", align="right")
        builder.set_bounding_box("grand_total", tot_label_x, y - 2, margin_right, y + 16.0)
        y += 20.0

    # 6. Mandatory Tax Embedded Notice & Footer
    y = max(y + 10, 680.0)
    builder.draw_rect(margin_left, y, content_width, 24, fill_color="#F8FAFC", stroke_color="#CBD5E1")
    builder.draw_text(margin_left + 12, y + 7, "Note: All prices inclusive of GST", font_name="Courier-Bold", font_size=9, color="#1E293B")

    builder.draw_line(margin_left, 740.0, margin_right, 740.0, stroke_color="#000000")
    builder.draw_text(margin_left, 748.0, "All prices inclusive of GST", font_name="Courier", font_size=8, color="#64748B")
    builder.draw_text(margin_right, 748.0, "Page 1 of 1", font_name="Courier", font_size=8, color="#64748B", align="right")

    return builder.save()
