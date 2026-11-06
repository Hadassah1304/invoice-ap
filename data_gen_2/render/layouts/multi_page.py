from __future__ import annotations

import logging
from typing import Any, Dict, Tuple
from reportlab.lib.colors import HexColor

from render.formatting import format_currency, format_date, format_number
from render.layouts.itemised import render_itemised_layout
from render.pdf import PDFBuilder

logger = logging.getLogger(__name__)


def render_multi_page_layout(
    document: Any,
    render_config: Any,
    output_path: str,
) -> Dict[str, Tuple[int, float, float, float, float]]:
    """Render the 'multi_page' layout:
    Break after at most 8 rows per page (page 1 footer 'Continued on next page'),
    repeat the header row on page 2+, and print the totals ONLY on the last page.
    Works for any line count of 9 or more; for fewer, behaves like 'itemised' with a warning.
    """
    lines = getattr(document, "lines", []) or []
    if len(lines) <= 8:
        logger.warning(f"multi_page layout requested with {len(lines)} lines (<= 8); falling back to itemised.")
        return render_itemised_layout(document, render_config, output_path)

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

    # Total pages calculation (8 rows per page)
    rows_per_page = 8
    total_pages = (len(lines) + rows_per_page - 1) // rows_per_page

    col_x = [margin_left, margin_left + 30, margin_left + 230, margin_left + 280, margin_left + 330, margin_left + 420, margin_left + 470, margin_right]

    def draw_table_header(y_pos: float) -> float:
        builder.draw_rect(margin_left, y_pos, content_width, 20, fill_color="#F1F5F9", stroke_color="#CBD5E1")
        builder.draw_text(col_x[0] + 4, y_pos + 5, "#", font_name="Helvetica-Bold", font_size=8, color="#334155")
        builder.draw_text(col_x[1] + 4, y_pos + 5, "Description", font_name="Helvetica-Bold", font_size=8, color="#334155")
        builder.draw_text(col_x[2] + 4, y_pos + 5, "Qty", font_name="Helvetica-Bold", font_size=8, color="#334155")
        builder.draw_text(col_x[3] + 4, y_pos + 5, "UOM", font_name="Helvetica-Bold", font_size=8, color="#334155")
        builder.draw_text(col_x[4] + 4, y_pos + 5, f"Unit Price ({currency})", font_name="Helvetica-Bold", font_size=8, color="#334155")
        builder.draw_text(col_x[5] + 4, y_pos + 5, "Tax %", font_name="Helvetica-Bold", font_size=8, color="#334155")
        builder.draw_text(col_x[7] - 4, y_pos + 5, f"Total ({currency})", font_name="Helvetica-Bold", font_size=8, color="#334155", align="right")
        return y_pos + 20.0

    # === PAGE 1 ===
    y = 40.0
    title = getattr(document, "title", "TAX INVOICE") or "TAX INVOICE"
    builder.draw_rect(margin_left, y, content_width, 32, fill_color="#1E293B", stroke_color=None)
    builder.draw_text(margin_left + 12, y + 8, title, font_name="Helvetica-Bold", font_size=16, color="#FFFFFF")
    y += 42.0

    # Vendor Block & Metadata on Page 1
    vb_start_y = y
    vb_x0, vb_y0 = margin_left, y
    vb_x1 = margin_left + 260.0

    vendor_block = getattr(document, "vendor_block", None)
    if "vendor_block" in omit_fields or "vendor" in omit_fields:
        if not omit_label:
            builder.draw_text(vb_x0, y, "Vendor: [OMITTED]", font_name="Helvetica", font_size=10, color="#64748B")
            y += 14.0
    elif vendor_block:
        v_name = getattr(vendor_block, "name", None)
        if v_name and "vendor_name" not in omit_fields:
            builder.draw_text(vb_x0, y, v_name, font_name="Helvetica-Bold", font_size=12, color="#0F172A")
            y += 16.0
        v_gstin = getattr(vendor_block, "gstin", None)
        if v_gstin and "gstin" not in omit_fields:
            builder.draw_text(vb_x0, y, f"GSTIN: {v_gstin}", font_name="Helvetica", font_size=9, color="#334155")
            y += 13.0
        v_addr = getattr(vendor_block, "address", None)
        if v_addr:
            builder.draw_text(vb_x0, y, v_addr, font_name="Helvetica", font_size=8, color="#475569")
            y += 12.0
        v_email = getattr(vendor_block, "email", None)
        if v_email:
            builder.draw_text(vb_x0, y, f"Email: {v_email}", font_name="Helvetica", font_size=8, color="#475569")
            y += 12.0
        v_phone = getattr(vendor_block, "phone", None)
        if v_phone:
            builder.draw_text(vb_x0, y, f"Phone: {v_phone}", font_name="Helvetica", font_size=8, color="#475569")
            y += 12.0
        v_bank = getattr(vendor_block, "bank_account", None)
        if v_bank:
            builder.draw_text(vb_x0, y, f"Bank A/C: {v_bank}", font_name="Helvetica", font_size=8, color="#475569")
            y += 12.0

    vb_y1 = max(y, vb_y0 + 14.0)
    builder.set_bounding_box("vendor_block", vb_x0, vb_y0, vb_x1, vb_y1)

    meta_x = margin_right - 220.0
    meta_y = vb_start_y

    inv_num = getattr(document, "invoice_number", None)
    if "invoice_number" in omit_fields:
        if not omit_label:
            b = builder.draw_text(meta_x, meta_y, "Invoice No: ", font_name="Helvetica-Bold", font_size=9, color="#0F172A")
            builder.set_bounding_box("invoice_number", b[0], b[1], b[2] + 20, b[3])
            meta_y += 14.0
    else:
        text = f"Invoice No: {inv_num}" if inv_num else "Invoice No: "
        b = builder.draw_text(meta_x, meta_y, text, font_name="Helvetica-Bold", font_size=10, color="#0F172A")
        builder.set_bounding_box("invoice_number", b[0], b[1], b[2], b[3])
        meta_y += 14.0

    inv_date = getattr(document, "invoice_date", None)
    formatted_date = format_date(inv_date, date_style=date_fmt)
    if "invoice_date" in omit_fields:
        if not omit_label:
            b = builder.draw_text(meta_x, meta_y, "Date: ", font_name="Helvetica", font_size=9, color="#334155")
            builder.set_bounding_box("date", b[0], b[1], b[2] + 20, b[3])
            meta_y += 13.0
    else:
        text = f"Date: {formatted_date}" if inv_date else "Date: "
        b = builder.draw_text(meta_x, meta_y, text, font_name="Helvetica", font_size=9, color="#334155")
        builder.set_bounding_box("date", b[0], b[1], b[2], b[3])
        meta_y += 13.0

    due_date = getattr(document, "due_date", None)
    if due_date:
        builder.draw_text(meta_x, meta_y, f"Due Date: {format_date(due_date, date_style=date_fmt)}", font_name="Helvetica", font_size=9, color="#334155")
        meta_y += 13.0

    po_ref = getattr(document, "po_reference", None)
    if po_ref and "po_reference" not in omit_fields:
        builder.draw_text(meta_x, meta_y, f"PO Ref: {po_ref}", font_name="Helvetica-Bold", font_size=9, color="#2563EB")
        meta_y += 13.0

    y = max(y, meta_y) + 20.0
    y = draw_table_header(y)

    page_num = 1
    for idx, line in enumerate(lines):
        if idx > 0 and idx % rows_per_page == 0:
            # End of page, not the last page
            builder.draw_line(margin_left, 740.0, margin_right, 740.0, stroke_color="#E2E8F0")
            builder.draw_text(margin_left, 748.0, "Continued on next page", font_name="Helvetica-Bold", font_size=8, color="#2563EB")
            builder.draw_text(margin_right, 748.0, f"Page {page_num} of {total_pages}", font_name="Helvetica", font_size=8, color="#94A3B8", align="right")
            builder.show_page()
            page_num += 1

            # New page top
            y = 40.0
            builder.draw_text(margin_left, y, f"{title} (Continued)", font_name="Helvetica-Bold", font_size=12, color="#1E293B")
            if inv_num and "invoice_number" not in omit_fields:
                builder.draw_text(margin_right, y, f"Invoice: {inv_num}", font_name="Helvetica", font_size=9, color="#64748B", align="right")
            y += 24.0
            y = draw_table_header(y)

        row_bg = "#FFFFFF" if idx % 2 == 0 else "#F8FAFC"
        builder.draw_rect(margin_left, y, content_width, 18, fill_color=row_bg, stroke_color="#E2E8F0")

        line_no = getattr(line, "line_no", idx + 1)
        desc = getattr(line, "description", "") or ""
        qty = getattr(line, "qty", 0)
        uom = getattr(line, "uom", "pcs") or "pcs"
        unit_price = getattr(line, "unit_price", 0.0)
        tax_rate = getattr(line, "tax_rate", 0.0)
        line_total = getattr(line, "line_total", 0.0)

        builder.draw_text(col_x[0] + 4, y + 4, str(line_no), font_name="Helvetica", font_size=8, color="#475569")
        builder.draw_text(col_x[1] + 4, y + 4, desc[:36], font_name="Helvetica", font_size=8, color="#0F172A")
        builder.draw_text(col_x[2] + 4, y + 4, str(qty), font_name="Helvetica", font_size=8, color="#475569")
        builder.draw_text(col_x[3] + 4, y + 4, uom, font_name="Helvetica", font_size=8, color="#475569")
        builder.draw_text(col_x[4] + 4, y + 4, format_number(unit_price, number_format=num_fmt), font_name="Helvetica", font_size=8, color="#475569")
        builder.draw_text(col_x[5] + 4, y + 4, f"{tax_rate}%", font_name="Helvetica", font_size=8, color="#475569")
        builder.draw_text(col_x[7] - 4, y + 4, format_number(line_total, number_format=num_fmt), font_name="Helvetica", font_size=8, color="#0F172A", align="right")
        y += 18.0

    y += 15.0

    # Totals block ONLY on the last page!
    tot_label_x = margin_right - 200.0
    tot_val_x = margin_right - 4.0

    subtotal = getattr(document, "subtotal", None)
    if subtotal is not None and "subtotal" not in omit_fields:
        builder.draw_text(tot_label_x, y, "Subtotal:", font_name="Helvetica", font_size=9, color="#475569")
        builder.draw_text(tot_val_x, y, format_currency(subtotal, curr_style, currency, num_fmt), font_name="Helvetica", font_size=9, color="#0F172A", align="right")
        y += 14.0

    tax_total = getattr(document, "tax_total", None)
    if tax_total is not None and "tax_total" not in omit_fields:
        builder.draw_text(tot_label_x, y, "Tax Total:", font_name="Helvetica", font_size=9, color="#475569")
        builder.draw_text(tot_val_x, y, format_currency(tax_total, curr_style, currency, num_fmt), font_name="Helvetica", font_size=9, color="#0F172A", align="right")
        y += 14.0

    grand_total = getattr(document, "grand_total", None)
    if "grand_total" in omit_fields:
        if not omit_label:
            b = builder.draw_text(tot_label_x, y, "Grand Total: ", font_name="Helvetica-Bold", font_size=11, color="#0F172A")
            builder.set_bounding_box("grand_total", tot_label_x, y, margin_right, y + 16.0)
            y += 18.0
    elif grand_total is not None:
        builder.draw_line(tot_label_x, y, margin_right, y, stroke_color="#CBD5E1", stroke_width=1)
        y += 4.0
        builder.draw_text(tot_label_x, y, "Grand Total:", font_name="Helvetica-Bold", font_size=11, color="#0F172A")
        val_str = format_currency(grand_total, curr_style, currency, num_fmt)
        builder.draw_text(tot_val_x, y, val_str, font_name="Helvetica-Bold", font_size=11, color="#0F172A", align="right")
        builder.set_bounding_box("grand_total", tot_label_x, y - 2, margin_right, y + 16.0)
        y += 20.0

    # Final Page Footer
    builder.draw_line(margin_left, 740.0, margin_right, 740.0, stroke_color="#E2E8F0")
    builder.draw_text(margin_left, 748.0, "Thank you for your business.", font_name="Helvetica", font_size=8, color="#94A3B8")
    builder.draw_text(margin_right, 748.0, f"Page {page_num} of {total_pages}", font_name="Helvetica", font_size=8, color="#94A3B8", align="right")

    return builder.save()
