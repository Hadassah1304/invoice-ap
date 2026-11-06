from __future__ import annotations

from typing import Any, Dict, Tuple
from reportlab.lib.colors import HexColor

from render.formatting import format_currency, format_date, format_number
from render.pdf import PDFBuilder


def render_bundled_layout(
    document: Any,
    render_config: Any,
    output_path: str,
) -> Dict[str, Tuple[int, float, float, float, float]]:
    """Render the 'bundled' layout:
    A single bundled line 'Supply of goods as per PO' carrying the grand total (or subtotal),
    with a 'Details' block listing the underlying items in smaller text, and totals beneath.
    Uses Times-Roman serif typography for styling variety.
    """
    builder = PDFBuilder(output_path)
    omit_fields = document.omit.fields if hasattr(document, "omit") and document.omit else []
    omit_label = document.omit.omit_label if hasattr(document, "omit") and document.omit else False

    currency = getattr(document, "currency", "INR") or "INR"
    curr_style = getattr(render_config, "currency_style", "Rs.")
    num_fmt = getattr(render_config, "number_format", "plain")
    date_fmt = getattr(render_config, "date_style", "dmy_slash")

    margin_left = 45.0
    margin_right = 567.0
    content_width = margin_right - margin_left
    y = 45.0

    # 1. Title
    title = getattr(document, "title", "TAX INVOICE") or "TAX INVOICE"
    builder.draw_text(margin_left, y, title, font_name="Times-Bold", font_size=18, color="#111827")
    y += 24.0
    builder.draw_line(margin_left, y, margin_right, y, stroke_color="#111827", stroke_width=1.5)
    y += 15.0

    # 2. Vendor Block (Left) & Metadata (Right)
    vb_start_y = y
    vb_x0, vb_y0 = margin_left, y
    vb_x1 = margin_left + 260.0

    vendor_block = getattr(document, "vendor_block", None)
    if "vendor_block" in omit_fields or "vendor" in omit_fields:
        if not omit_label:
            builder.draw_text(vb_x0, y, "Vendor: [OMITTED]", font_name="Times-Roman", font_size=10, color="#6B7280")
            y += 14.0
    elif vendor_block:
        v_name = getattr(vendor_block, "name", None)
        if v_name and "vendor_name" not in omit_fields:
            builder.draw_text(vb_x0, y, v_name, font_name="Times-Bold", font_size=12, color="#111827")
            y += 16.0
        v_gstin = getattr(vendor_block, "gstin", None)
        if v_gstin and "gstin" not in omit_fields:
            builder.draw_text(vb_x0, y, f"GSTIN: {v_gstin}", font_name="Times-Roman", font_size=9, color="#374151")
            y += 13.0
        v_addr = getattr(vendor_block, "address", None)
        if v_addr:
            builder.draw_text(vb_x0, y, v_addr, font_name="Times-Roman", font_size=8, color="#4B5563")
            y += 12.0
        v_email = getattr(vendor_block, "email", None)
        if v_email:
            builder.draw_text(vb_x0, y, f"Email: {v_email}", font_name="Times-Roman", font_size=8, color="#4B5563")
            y += 12.0
        v_phone = getattr(vendor_block, "phone", None)
        if v_phone:
            builder.draw_text(vb_x0, y, f"Phone: {v_phone}", font_name="Times-Roman", font_size=8, color="#4B5563")
            y += 12.0
        v_bank = getattr(vendor_block, "bank_account", None)
        if v_bank:
            builder.draw_text(vb_x0, y, f"Bank Account: {v_bank}", font_name="Times-Roman", font_size=8, color="#4B5563")
            y += 12.0

    vb_y1 = max(y, vb_y0 + 14.0)
    builder.set_bounding_box("vendor_block", vb_x0, vb_y0, vb_x1, vb_y1)

    # Right side: Invoice Details
    meta_x = margin_right - 220.0
    meta_y = vb_start_y

    inv_num = getattr(document, "invoice_number", None)
    if "invoice_number" in omit_fields:
        if not omit_label:
            b = builder.draw_text(meta_x, meta_y, "Invoice Number: ", font_name="Times-Bold", font_size=9, color="#111827")
            builder.set_bounding_box("invoice_number", b[0], b[1], b[2] + 20, b[3])
            meta_y += 14.0
    else:
        text = f"Invoice Number: {inv_num}" if inv_num else "Invoice Number: "
        b = builder.draw_text(meta_x, meta_y, text, font_name="Times-Bold", font_size=10, color="#111827")
        builder.set_bounding_box("invoice_number", b[0], b[1], b[2], b[3])
        meta_y += 14.0

    inv_date = getattr(document, "invoice_date", None)
    formatted_date = format_date(inv_date, date_style=date_fmt)
    if "invoice_date" in omit_fields:
        if not omit_label:
            b = builder.draw_text(meta_x, meta_y, "Invoice Date: ", font_name="Times-Roman", font_size=9, color="#374151")
            builder.set_bounding_box("date", b[0], b[1], b[2] + 20, b[3])
            meta_y += 13.0
    else:
        text = f"Invoice Date: {formatted_date}" if inv_date else "Invoice Date: "
        b = builder.draw_text(meta_x, meta_y, text, font_name="Times-Roman", font_size=9, color="#374151")
        builder.set_bounding_box("date", b[0], b[1], b[2], b[3])
        meta_y += 13.0

    due_date = getattr(document, "due_date", None)
    if due_date:
        builder.draw_text(meta_x, meta_y, f"Payment Due: {format_date(due_date, date_style=date_fmt)}", font_name="Times-Roman", font_size=9, color="#374151")
        meta_y += 13.0

    po_ref = getattr(document, "po_reference", None)
    if po_ref and "po_reference" not in omit_fields:
        builder.draw_text(meta_x, meta_y, f"Order Ref: {po_ref}", font_name="Times-Bold", font_size=9, color="#1D4ED8")
        meta_y += 13.0

    y = max(y, meta_y) + 20.0

    # 3. Main Bundled Table
    builder.draw_rect(margin_left, y, content_width, 22, fill_color="#E5E7EB", stroke_color="#9CA3AF")
    builder.draw_text(margin_left + 8, y + 6, "Item & Description", font_name="Times-Bold", font_size=9, color="#111827")
    builder.draw_text(margin_right - 8, y + 6, f"Amount ({currency})", font_name="Times-Bold", font_size=9, color="#111827", align="right")
    y += 22.0

    subtotal = getattr(document, "subtotal", None)
    grand_total = getattr(document, "grand_total", None)
    bundled_amount = subtotal if subtotal is not None else grand_total

    builder.draw_rect(margin_left, y, content_width, 24, fill_color="#FFFFFF", stroke_color="#D1D5DB")
    builder.draw_text(margin_left + 8, y + 6, "Supply of goods as per PO", font_name="Times-Bold", font_size=10, color="#111827")
    builder.draw_text(margin_right - 8, y + 6, format_currency(bundled_amount, curr_style, currency, num_fmt), font_name="Times-Bold", font_size=10, color="#111827", align="right")
    y += 28.0

    # 4. Details Block (underlying items in small text)
    lines = getattr(document, "lines", []) or []
    if lines:
        builder.draw_text(margin_left + 4, y, "Details / Item Breakdown:", font_name="Times-BoldItalic", font_size=8, color="#4B5563")
        y += 12.0
        det_bg_y = y
        det_height = len(lines) * 14.0 + 8.0
        builder.draw_rect(margin_left, det_bg_y, content_width, det_height, fill_color="#F9FAFB", stroke_color="#E5E7EB")
        y += 5.0
        for line in lines:
            desc = getattr(line, "description", "") or ""
            qty = getattr(line, "qty", 0)
            uom = getattr(line, "uom", "pcs") or "pcs"
            unit_price = getattr(line, "unit_price", 0.0)
            line_str = f"• {desc} (Qty: {qty} {uom} @ {format_number(unit_price, number_format=num_fmt)})"
            builder.draw_text(margin_left + 8, y, line_str[:60], font_name="Times-Roman", font_size=8, color="#374151")
            y += 14.0
        y = det_bg_y + det_height + 15.0
    else:
        y += 15.0

    # 5. Totals Block
    tot_label_x = margin_right - 210.0
    tot_val_x = margin_right - 8.0

    if subtotal is not None and "subtotal" not in omit_fields:
        builder.draw_text(tot_label_x, y, "Subtotal:", font_name="Times-Roman", font_size=9, color="#4B5563")
        builder.draw_text(tot_val_x, y, format_currency(subtotal, curr_style, currency, num_fmt), font_name="Times-Roman", font_size=9, color="#111827", align="right")
        y += 14.0

    tax_total = getattr(document, "tax_total", None)
    if tax_total is not None and "tax_total" not in omit_fields:
        builder.draw_text(tot_label_x, y, "Applicable Taxes:", font_name="Times-Roman", font_size=9, color="#4B5563")
        builder.draw_text(tot_val_x, y, format_currency(tax_total, curr_style, currency, num_fmt), font_name="Times-Roman", font_size=9, color="#111827", align="right")
        y += 14.0

    if "grand_total" in omit_fields:
        if not omit_label:
            b = builder.draw_text(tot_label_x, y, "Total Payable: ", font_name="Times-Bold", font_size=11, color="#111827")
            builder.set_bounding_box("grand_total", tot_label_x, y, margin_right, y + 16.0)
            y += 18.0
    elif grand_total is not None:
        builder.draw_line(tot_label_x, y, margin_right, y, stroke_color="#111827", stroke_width=1)
        y += 4.0
        b_lbl = builder.draw_text(tot_label_x, y, "Total Payable:", font_name="Times-Bold", font_size=11, color="#111827")
        val_str = format_currency(grand_total, curr_style, currency, num_fmt)
        b_val = builder.draw_text(tot_val_x, y, val_str, font_name="Times-Bold", font_size=11, color="#111827", align="right")
        builder.set_bounding_box("grand_total", tot_label_x, y - 2, margin_right, y + 16.0)
        y += 20.0

    # 6. Footer
    builder.draw_line(margin_left, 740.0, margin_right, 740.0, stroke_color="#D1D5DB")
    builder.draw_text(margin_left, 748.0, "This is a computer generated invoice.", font_name="Times-Italic", font_size=8, color="#6B7280")
    builder.draw_text(margin_right, 748.0, "Page 1 of 1", font_name="Times-Roman", font_size=8, color="#6B7280", align="right")

    return builder.save()
