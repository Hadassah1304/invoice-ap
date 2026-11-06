from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import random
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors

from data_gen.catalog import CATALOG_ITEMS
from invoice_pipeline.store.embeddings import TFIDFCharEmbedder


def generate_synthetic_data(seed: int = 42, out_dir: str = "samples"):
    random.seed(seed)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    embedder = TFIDFCharEmbedder()

    # 1. Generate Vendors
    vendors = [
        {
            "vendor_id": "V-BALA",
            "name": "Sri Balaji Foods Pvt Ltd",
            "aliases": ["Balaji Foods", "Sri Balaji Foods"],
            "gstin": "36ABCDE1234F1Z5",
            "email_domain": "balajifoods.in",
            "approved": 1,
            "bank_account": "HDFC00012345678",
        },
        {
            "vendor_id": "V-STAT",
            "name": "Apex Stationery & Print Solutions",
            "aliases": ["Apex Stationery Ltd", "Apex Print"],
            "gstin": "29XYZAB5678C1Z2",
            "email_domain": "apexstationery.com",
            "approved": 1,
            "bank_account": "SBIN00098765432",
        },
        {
            "vendor_id": "V-TECH",
            "name": "CyberTech Hardware Systems LLP",
            "aliases": ["CyberTech LLP", "CyberTech Systems"],
            "gstin": "27AABBC3344D1Z8",
            "email_domain": "cybertech.io",
            "approved": 1,
            "bank_account": "ICIC00055443322",
        },
        {
            "vendor_id": "V-UNAPP",
            "name": "Unapproved Rogue Traders",
            "aliases": ["Rogue Traders"],
            "gstin": "07QQQQQ9999Q1Z1",
            "email_domain": "roguetraders.org",
            "approved": 0,
            "bank_account": "UNAP00011122233",
        },
    ]

    # 2. Purchase Orders
    pos = [
        # Normal Happy Explicit PO
        {
            "po_id": "PO-2026-0042",
            "vendor_id": "V-BALA",
            "po_date": "2026-10-01",
            "total": 1837.5,
            "currency": "INR",
            "status": "OPEN",
            "payment_terms_days": 30,
        },
        # PO for price drift testing
        {
            "po_id": "PO-2026-DRIFT",
            "vendor_id": "V-BALA",
            "po_date": "2026-10-01",
            "total": 1837.5,
            "currency": "INR",
            "status": "OPEN",
            "payment_terms_days": 30,
        },
        # Split invoicing series PO (Total 100,000)
        {
            "po_id": "PO-2026-SPLIT",
            "vendor_id": "V-TECH",
            "po_date": "2026-10-01",
            "total": 100000.0,
            "currency": "INR",
            "status": "OPEN",
            "payment_terms_days": 30,
        },
        # Three burgers test POs
        {
            "po_id": "PO-BURGER-A",
            "vendor_id": "V-BALA",
            "po_date": "2026-10-05",
            "total": 600.0,
            "currency": "INR",
            "status": "OPEN",
            "payment_terms_days": 30,
        },
        {
            "po_id": "PO-BURGER-B",
            "vendor_id": "V-BALA",
            "po_date": "2026-10-05",
            "total": 240.0,
            "currency": "INR",
            "status": "OPEN",
            "payment_terms_days": 30,
        },
        # Open PO for Apex Stationery
        {
            "po_id": "PO-2026-STAT",
            "vendor_id": "V-STAT",
            "po_date": "2026-10-01",
            "total": 3200.0,
            "currency": "INR",
            "status": "OPEN",
            "payment_terms_days": 30,
        },
        # Closed PO
        {
            "po_id": "PO-2026-CLOSED",
            "vendor_id": "V-STAT",
            "po_date": "2026-08-01",
            "total": 5000.0,
            "currency": "INR",
            "status": "CLOSED",
            "payment_terms_days": 30,
        },
    ]

    # 3. PO Items
    po_items = [
        # Items for PO-2026-0042
        {"po_id": "PO-2026-0042", "item_name": "Veg Burger 150g", "description": "Crispy vegetable patty with lettuce", "qty_ordered": 10.0, "qty_remaining": 10.0, "unit_price": 100.0, "uom": "pcs", "tax_rate": 5.0},
        {"po_id": "PO-2026-0042", "item_name": "Cold Coffee 300ml", "description": "Blended milk cold brew", "qty_ordered": 8.0, "qty_remaining": 8.0, "unit_price": 93.75, "uom": "cup", "tax_rate": 5.0},

        # Items for PO-2026-DRIFT
        {"po_id": "PO-2026-DRIFT", "item_name": "Veg Burger 150g", "description": "Crispy vegetable patty with lettuce", "qty_ordered": 10.0, "qty_remaining": 10.0, "unit_price": 100.0, "uom": "pcs", "tax_rate": 5.0},
        {"po_id": "PO-2026-DRIFT", "item_name": "Cold Coffee 300ml", "description": "Blended milk cold brew", "qty_ordered": 8.0, "qty_remaining": 8.0, "unit_price": 93.75, "uom": "cup", "tax_rate": 5.0},

        # Items for PO-2026-SPLIT
        {"po_id": "PO-2026-SPLIT", "item_name": "Wireless Optical Mouse", "description": "2.4GHz USB ergonomic mouse", "qty_ordered": 100.0, "qty_remaining": 100.0, "unit_price": 1000.0, "uom": "pcs", "tax_rate": 0.0},

        # Items for PO-BURGER-A (5 burgers)
        {"po_id": "PO-BURGER-A", "item_name": "Veg Burger 150g", "description": "Crispy vegetable patty", "qty_ordered": 5.0, "qty_remaining": 5.0, "unit_price": 120.0, "uom": "pcs", "tax_rate": 0.0},

        # Items for PO-BURGER-B (2 burgers)
        {"po_id": "PO-BURGER-B", "item_name": "Veg Burger 150g", "description": "Crispy vegetable patty", "qty_ordered": 2.0, "qty_remaining": 2.0, "unit_price": 120.0, "uom": "pcs", "tax_rate": 0.0},

        # Items for PO-2026-STAT
        {"po_id": "PO-2026-STAT", "item_name": "A4 Copier Paper 80gsm", "description": "High quality 500 sheets ream", "qty_ordered": 10.0, "qty_remaining": 10.0, "unit_price": 320.0, "uom": "ream", "tax_rate": 0.0},

        # Items for PO-2026-CLOSED
        {"po_id": "PO-2026-CLOSED", "item_name": "A4 Copier Paper 80gsm", "description": "High quality 500 sheets ream", "qty_ordered": 15.0, "qty_remaining": 0.0, "unit_price": 320.0, "uom": "ream", "tax_rate": 12.0},
    ]

    seed_data = {"vendors": vendors, "purchase_orders": pos, "items": po_items}
    with open(out_path / "seed.json", "w", encoding="utf-8") as f:
        json.dump(seed_data, f, indent=2)

    # 4. Generate Manifest and Invoices
    manifest_rows = []

    def make_pdf(filename: str, vendor: dict, inv_num: str, inv_date: str, po_ref: str | None, lines: list, total: float, subtotal: float = None, tax: float = 0.0):
        c = canvas.Canvas(str(out_path / filename), pagesize=letter)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 750, vendor["name"])
        c.setFont("Helvetica", 10)
        c.drawString(50, 735, f"GSTIN: {vendor.get('gstin', '')}")
        c.drawString(50, 720, f"Email: billing@{vendor.get('email_domain', 'example.com')}")
        c.drawString(50, 705, f"Bank Account: {vendor.get('bank_account', '')}")

        c.setFont("Helvetica-Bold", 12)
        c.drawString(380, 750, "TAX INVOICE")
        c.setFont("Helvetica", 10)
        c.drawString(380, 735, f"Invoice No: {inv_num}")
        c.drawString(380, 720, f"Invoice Date: {inv_date}")
        if po_ref:
            c.drawString(380, 705, f"PO Reference: {po_ref}")

        # Table header
        c.setStrokeColor(colors.gray)
        c.line(50, 680, 550, 680)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(55, 665, "Line")
        c.drawString(90, 665, "Description")
        c.drawString(320, 665, "Qty")
        c.drawString(380, 665, "Unit Price")
        c.drawString(470, 665, "Total")
        c.line(50, 655, 550, 655)

        y = 635
        c.setFont("Helvetica", 9)
        for idx, l in enumerate(lines):
            c.drawString(55, y, str(idx + 1))
            c.drawString(90, y, str(l["desc"]))
            c.drawString(320, y, str(l["qty"]))
            c.drawString(380, y, f"{l['price']:.2f}")
            c.drawString(470, y, f"{l['qty']*l['price']:.2f}")
            y -= 20

        c.line(50, y, 550, y)
        y -= 20
        c.drawString(380, y, "Subtotal:")
        c.drawString(470, y, f"{(subtotal if subtotal else total - tax):.2f}")
        y -= 15
        c.drawString(380, y, "Tax:")
        c.drawString(470, y, f"{tax:.2f}")
        y -= 15
        c.setFont("Helvetica-Bold", 10)
        c.drawString(380, y, "Grand Total:")
        c.drawString(470, y, f"Rs. {total:.2f}")

        c.save()

    # --- Scenario 1: Happy Path Explicit ---
    make_pdf(
        "inv_01_happy.pdf",
        vendors[0],
        "INV/2026/001",
        "2026-10-15",
        "PO-2026-0042",
        [
            {"desc": "Veg Burger 150g", "qty": 10, "price": 100.0},
            {"desc": "Cold Coffee 300ml", "qty": 8, "price": 93.75},
        ],
        total=1837.5,
        subtotal=1750.0,
        tax=87.5,
    )
    manifest_rows.append({
        "file": "inv_01_happy.pdf",
        "edge_case_tag": "happy_explicit",
        "expected_decision": "APPROVED",
        "expected_reason_code": "OK",
        "expected_po": "PO-2026-0042",
        "run_order": "1",
        "notes": "Standard happy path with full explicit match",
    })

    # --- Scenario 2: Split Invoicing Series (4 invoices) ---
    # Split 1: 40k
    make_pdf(
        "inv_02_split_1.pdf",
        vendors[2],
        "INV-SPLIT-01",
        "2026-10-10",
        "PO-2026-SPLIT",
        [{"desc": "Wireless Optical Mouse", "qty": 40, "price": 1000.0}],
        total=40000.0,
    )
    manifest_rows.append({
        "file": "inv_02_split_1.pdf",
        "edge_case_tag": "split_1",
        "expected_decision": "APPROVED",
        "expected_reason_code": "OK",
        "expected_po": "PO-2026-SPLIT",
        "run_order": "2",
        "notes": "First split of PO-2026-SPLIT",
    })

    # Split 2: 40k
    make_pdf(
        "inv_03_split_2.pdf",
        vendors[2],
        "INV-SPLIT-02",
        "2026-10-15",
        "PO-2026-SPLIT",
        [{"desc": "Wireless Optical Mouse", "qty": 40, "price": 1000.0}],
        total=40000.0,
    )
    manifest_rows.append({
        "file": "inv_03_split_2.pdf",
        "edge_case_tag": "split_2",
        "expected_decision": "APPROVED",
        "expected_reason_code": "OK",
        "expected_po": "PO-2026-SPLIT",
        "run_order": "3",
        "notes": "Second split of PO-2026-SPLIT",
    })

    # Split 3: 20k (closes the PO!)
    make_pdf(
        "inv_04_split_3.pdf",
        vendors[2],
        "INV-SPLIT-03",
        "2026-10-20",
        "PO-2026-SPLIT",
        [{"desc": "Wireless Optical Mouse", "qty": 20, "price": 1000.0}],
        total=20000.0,
    )
    manifest_rows.append({
        "file": "inv_04_split_3.pdf",
        "edge_case_tag": "split_3",
        "expected_decision": "APPROVED",
        "expected_reason_code": "OK",
        "expected_po": "PO-2026-SPLIT",
        "run_order": "4",
        "notes": "Third split - exactly closes PO balance to 0",
    })

    # Split 4: 10k (rejected because PO is now closed)
    make_pdf(
        "inv_05_split_4.pdf",
        vendors[2],
        "INV-SPLIT-04",
        "2026-10-25",
        "PO-2026-SPLIT",
        [{"desc": "Wireless Optical Mouse", "qty": 10, "price": 1000.0}],
        total=10000.0,
    )
    manifest_rows.append({
        "file": "inv_05_split_4.pdf",
        "edge_case_tag": "split_4",
        "expected_decision": "REJECTED",
        "expected_reason_code": "PO_CLOSED",
        "expected_po": "PO-2026-SPLIT",
        "run_order": "5",
        "notes": "Fourth split rejected because PO is CLOSED",
    })

    # --- Scenario 3: Near Duplicate Resubmission ---
    # First submission
    make_pdf(
        "inv_06_dup_orig.pdf",
        vendors[1],
        "INV-001",
        "2026-10-18",
        "PO-2026-STAT",
        [{"desc": "A4 Copier Paper 80gsm", "qty": 5, "price": 320.0}],
        total=1600.0,
    )
    manifest_rows.append({
        "file": "inv_06_dup_orig.pdf",
        "edge_case_tag": "dup_orig",
        "expected_decision": "APPROVED",
        "expected_reason_code": "OK",
        "expected_po": "PO-2026-STAT",
        "run_order": "6",
        "notes": "Original invoice",
    })

    # Near duplicate with format change: INV001
    make_pdf(
        "inv_07_dup_near.pdf",
        vendors[1],
        "INV001",
        "2026-10-19",
        "PO-2026-STAT",
        [{"desc": "A4 Copier Paper 80gsm", "qty": 5, "price": 320.0}],
        total=1600.0,
    )
    manifest_rows.append({
        "file": "inv_07_dup_near.pdf",
        "edge_case_tag": "dup_near",
        "expected_decision": "REJECTED",
        "expected_reason_code": "DUPLICATE_EXACT",
        "expected_po": "",
        "run_order": "7",
        "notes": "Normalized invoice key matches INV-001, caught as duplicate",
    })

    # --- Scenario 4: Burger Tie Scenario (Missing PO reference) ---
    make_pdf(
        "inv_08_burger_clear.pdf",
        vendors[0],
        "INV-BURGER-01",
        "2026-10-15",
        None,
        [{"desc": "Veg Burger 150g", "qty": 2, "price": 120.0}],
        total=240.0,
    )
    manifest_rows.append({
        "file": "inv_08_burger_clear.pdf",
        "edge_case_tag": "burger_clear_winner",
        "expected_decision": "NEEDS_REVIEW",
        "expected_reason_code": "INFERRED_MATCH",
        "expected_po": "PO-BURGER-B",
        "run_order": "8",
        "notes": "Inferred PO with exact total coverage match to PO-BURGER-B",
    })

    # --- Scenario 5: Hidden Price Drift under matching total ---
    make_pdf(
        "inv_09_price_drift.pdf",
        vendors[0],
        "INV-DRIFT-01",
        "2026-10-28",
        "PO-2026-DRIFT",
        [
            # Price up from 100 to 175, qty down from 10 to 5
            {"desc": "Veg Burger 150g", "qty": 5, "price": 175.0},
            {"desc": "Cold Coffee 300ml", "qty": 8, "price": 107.81},
        ],
        total=1837.5,
        subtotal=1750.0,
        tax=87.5,
    )
    manifest_rows.append({
        "file": "inv_09_price_drift.pdf",
        "edge_case_tag": "price_drift",
        "expected_decision": "NEEDS_REVIEW",
        "expected_reason_code": "PRICE_DRIFT",
        "expected_po": "PO-2026-DRIFT",
        "run_order": "9",
        "notes": "Total matches PO perfectly but line unit prices drifted up",
    })

    # --- Scenario 6: Unapproved Vendor ---
    make_pdf(
        "inv_10_unapproved.pdf",
        vendors[3],
        "INV-ROGUE-99",
        "2026-10-15",
        None,
        [{"desc": "Wireless Optical Mouse", "qty": 2, "price": 500.0}],
        total=1000.0,
    )
    manifest_rows.append({
        "file": "inv_10_unapproved.pdf",
        "edge_case_tag": "vendor_unapproved",
        "expected_decision": "REJECTED",
        "expected_reason_code": "VENDOR_NOT_APPROVED",
        "expected_po": "",
        "run_order": "10",
        "notes": "Blocked unapproved vendor",
    })

    # Write Manifest CSV
    with open(out_path / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        fieldnames = ["file", "edge_case_tag", "expected_decision", "expected_reason_code", "expected_po", "run_order", "notes"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"Generated {len(manifest_rows)} synthetic invoice scenarios in {out_dir}")
