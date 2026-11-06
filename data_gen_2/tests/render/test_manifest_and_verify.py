from __future__ import annotations

import csv
import json
from pathlib import Path
import pytest

from manifest import MANIFEST_COLUMNS, build_manifest_and_report
from render.render_all import render_all_cases
from seed.build_seed import build_seed_json
from verify import verify_dataset


def create_test_suite_fixture(tmp_path: Path):
    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    # State
    state_data = {
        "meta": {"reference_date": "2026-11-06", "seed": 42},
        "vendors": [
            {
                "vendor_id": "V-BALA",
                "name": "Sri Balaji Foods Pvt Ltd",
                "aliases": ["Balaji Foods"],
                "gstin": "36ABCDE1234F1Z5",
                "email_domain": "balajifoods.in",
                "phone": "+91 40 5550 1101",
                "address": "Plot 14, Industrial Area, Hyderabad",
                "approved": True,
                "bank_account": "HDFC00012345678",
                "owner_family": "R",
            }
        ],
        "catalog": [
            {
                "sku": "SKU-001",
                "name": "Veg Burger 150g",
                "description": "Crispy vegetable patty with lettuce",
                "uom": "pcs",
                "unit_price": 120.0,
                "tax_rate": 5.0,
                "category": "food",
                "twin_group": "burger",
                "distinguisher": "veg",
                "reworded": [],
                "unique_item": False,
            }
        ],
        "purchase_orders": [
            {
                "po_id": "PO-R-BURGER-A",
                "vendor_id": "V-BALA",
                "po_date": "2026-10-07",
                "currency": "INR",
                "status": "PARTIAL",
                "payment_terms_days": 30,
                "group": "burger",
                "subtotal": 2400.0,
                "tax_total": 120.0,
                "total": 2520.0,
                "lines": [
                    {
                        "line_no": 1,
                        "sku": "SKU-001",
                        "item_name": "Veg Burger 150g",
                        "description": "Crispy vegetable patty with lettuce",
                        "uom": "pcs",
                        "qty_ordered": 20,
                        "qty_remaining": 6,
                        "unit_price": 120.0,
                        "tax_rate": 5.0,
                        "line_total": 2400.0,
                    }
                ],
            }
        ],
        "ledger_preload": [
            {
                "preload_id": "LP-R-BURGER-A-1",
                "po_id": "PO-R-BURGER-A",
                "vendor_id": "V-BALA",
                "invoice_no": "BAL/26/3310",
                "invoice_no_norm": "BAL263310",
                "invoice_date": "2026-10-23",
                "currency": "INR",
                "subtotal": 1680.0,
                "tax_total": 84.0,
                "total": 1764.0,
                "lines": [
                    {
                        "po_line_no": 1,
                        "description": "Veg Burger 150g",
                        "qty": 14,
                        "unit_price": 120.0,
                        "line_total": 1680.0,
                    }
                ],
            }
        ],
    }
    with open(build_dir / "state.json", "w") as f:
        json.dump(state_data, f)

    # 4 Cases:
    # Case 1: Digital itemised (run_order 1)
    # Case 2: byte_copy_of Case 1 (run_order 2)
    # Case 3: Degraded light (run_order 3)
    # Case 4: Degraded heavy (run_order 4)
    # This satisfies >= 25% degraded (50% degraded)
    cases_data = {
        "meta": {"reference_date": "2026-11-06", "seed": 42, "case_count": 4},
        "cases": [
            {
                "case_id": "SC-R-BURGER-01",
                "run_order": 1,
                "file_stem": "r01_burger_clear",
                "tag": "burger_clear_winner",
                "family": "R",
                "series_id": None,
                "byte_copy_of": None,
                "document": {
                    "title": "TAX INVOICE",
                    "document_type": "invoice",
                    "vendor_block": {
                        "name": "Sri Balaji Foods Pvt Ltd",
                        "gstin": "36ABCDE1234F1Z5",
                        "email": "billing@balajifoods.in",
                        "phone": "+91 40 5550 1101",
                        "address": "Plot 14, Industrial Area, Hyderabad",
                        "bank_account": "HDFC00012345678",
                    },
                    "invoice_number": "BAL/26/5801",
                    "invoice_date": "2026-10-27",
                    "due_date": None,
                    "po_reference": "PO-R-BURGER-A",
                    "currency": "INR",
                    "tax_mode": "separate",
                    "lines": [
                        {
                            "line_no": 1,
                            "description": "Veg Burger 150g",
                            "uom": "pcs",
                            "qty": 6,
                            "unit_price": 120.0,
                            "line_total": 720.0,
                            "tax_rate": 5.0,
                        }
                    ],
                    "subtotal": 720.0,
                    "tax_total": 36.0,
                    "grand_total": 756.0,
                    "omit": {"fields": [], "omit_label": False},
                    "flags": {"ambiguous_date": False},
                },
                "render": {
                    "layout": "itemised",
                    "degrade": "none",
                    "number_format": "plain",
                    "currency_style": "Rs.",
                    "date_style": "dmy_slash",
                },
                "expected": {
                    "decision": "APPROVED",
                    "decision_accepted": ["APPROVED"],
                    "reason_codes_accepted": ["OK"],
                    "po_id": "PO-R-BURGER-A",
                    "confidence": "firm",
                    "expect_cached": False,
                    "config_dependency": [],
                    "notes": "Clear PO match",
                },
            },
            {
                "case_id": "SC-R-BURGER-02-DUP",
                "run_order": 2,
                "file_stem": "r02_burger_dup",
                "tag": "dup_exact",
                "family": "R",
                "series_id": None,
                "byte_copy_of": "SC-R-BURGER-01",
                "document": {
                    "title": "TAX INVOICE",
                    "document_type": "invoice",
                    "vendor_block": {
                        "name": "Sri Balaji Foods Pvt Ltd",
                        "gstin": "36ABCDE1234F1Z5",
                        "email": "billing@balajifoods.in",
                    },
                    "invoice_number": "BAL/26/5801",
                    "invoice_date": "2026-10-27",
                    "due_date": None,
                    "po_reference": "PO-R-BURGER-A",
                    "currency": "INR",
                    "lines": [],
                    "subtotal": 720.0,
                    "tax_total": 36.0,
                    "grand_total": 756.0,
                    "omit": {"fields": [], "omit_label": False},
                    "flags": {"ambiguous_date": False},
                },
                "render": {
                    "layout": "itemised",
                    "degrade": "none",
                    "number_format": "plain",
                    "currency_style": "Rs.",
                    "date_style": "dmy_slash",
                },
                "expected": {
                    "decision": "REJECTED",
                    "decision_accepted": ["REJECTED"],
                    "reason_codes_accepted": ["DUPLICATE_EXACT"],
                    "po_id": "PO-R-BURGER-A",
                    "confidence": "firm",
                    "expect_cached": False,
                    "config_dependency": [],
                    "notes": "Exact duplicate",
                },
            },
            {
                "case_id": "SC-R-BURGER-03-SCAN",
                "run_order": 3,
                "file_stem": "r03_burger_scan_light",
                "tag": "scan_blur_stamp",
                "family": "N",
                "series_id": None,
                "byte_copy_of": None,
                "document": {
                    "title": "TAX INVOICE",
                    "document_type": "invoice",
                    "vendor_block": {
                        "name": "Sri Balaji Foods Pvt Ltd",
                        "gstin": "36ABCDE1234F1Z5",
                    },
                    "invoice_number": "BAL/26/5802",
                    "invoice_date": "2026-10-28",
                    "due_date": None,
                    "po_reference": "PO-R-BURGER-A",
                    "currency": "INR",
                    "lines": [
                        {
                            "line_no": 1,
                            "description": "Veg Burger 150g",
                            "uom": "pcs",
                            "qty": 2,
                            "unit_price": 120.0,
                            "line_total": 240.0,
                            "tax_rate": 5.0,
                        }
                    ],
                    "subtotal": 240.0,
                    "tax_total": 12.0,
                    "grand_total": 252.0,
                    "omit": {"fields": [], "omit_label": False},
                    "flags": {"ambiguous_date": False},
                },
                "render": {
                    "layout": "itemised",
                    "degrade": "light",
                    "number_format": "plain",
                    "currency_style": "Rs.",
                    "date_style": "dmy_slash",
                },
                "expected": {
                    "decision": "APPROVED",
                    "decision_accepted": ["APPROVED"],
                    "reason_codes_accepted": ["OK"],
                    "po_id": "PO-R-BURGER-A",
                    "confidence": "firm",
                    "expect_cached": False,
                    "config_dependency": [],
                    "notes": "Scanned light",
                },
            },
            {
                "case_id": "SC-R-BURGER-04-HEAVY",
                "run_order": 4,
                "file_stem": "r04_burger_scan_heavy",
                "tag": "scan_blur_stamp",
                "family": "N",
                "series_id": None,
                "byte_copy_of": None,
                "document": {
                    "title": "TAX INVOICE",
                    "document_type": "invoice",
                    "vendor_block": {
                        "name": "Sri Balaji Foods Pvt Ltd",
                        "gstin": "36ABCDE1234F1Z5",
                    },
                    "invoice_number": "BAL/26/5803",
                    "invoice_date": "2026-10-29",
                    "due_date": None,
                    "po_reference": "PO-R-BURGER-A",
                    "currency": "INR",
                    "lines": [
                        {
                            "line_no": 1,
                            "description": "Veg Burger 150g",
                            "uom": "pcs",
                            "qty": 1,
                            "unit_price": 120.0,
                            "line_total": 120.0,
                            "tax_rate": 5.0,
                        }
                    ],
                    "subtotal": 120.0,
                    "tax_total": 6.0,
                    "grand_total": 126.0,
                    "omit": {"fields": [], "omit_label": False},
                    "flags": {"ambiguous_date": False},
                },
                "render": {
                    "layout": "bundled",
                    "degrade": "heavy",
                    "number_format": "plain",
                    "currency_style": "Rs.",
                    "date_style": "dmy_slash",
                },
                "expected": {
                    "decision": "APPROVED",
                    "decision_accepted": ["APPROVED"],
                    "reason_codes_accepted": ["OK"],
                    "po_id": "PO-R-BURGER-A",
                    "confidence": "firm",
                    "expect_cached": False,
                    "config_dependency": [],
                    "notes": "Scanned heavy",
                },
            },
        ],
    }
    with open(build_dir / "cases.json", "w") as f:
        json.dump(cases_data, f)

    return build_dir


def test_manifest_columns_and_verify(tmp_path):
    build_dir = create_test_suite_fixture(tmp_path)
    samples_dir = tmp_path / "samples"

    # 1. Render all files
    cases_json = build_dir / "cases.json"
    state_json = build_dir / "state.json"
    render_all_cases(str(cases_json), str(samples_dir), seed=42)

    # 2. Build seed
    build_seed_json(str(state_json), str(samples_dir / "seed.json"), embedder_backend="tfidf")

    # 3. Build manifest and report
    m_path, r_path = build_manifest_and_report(str(build_dir), str(samples_dir), embedder_backend="tfidf")

    assert m_path.exists()
    assert r_path.exists()

    with open(m_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == MANIFEST_COLUMNS, "Manifest columns must match contract section 8.3 exactly"
        rows = list(reader)
        assert len(rows) == 4
        # Verify ordering by run_order
        run_orders = [int(r[5]) for r in rows]
        assert run_orders == [1, 2, 3, 4]

    # Verify sha256 equality for byte_copy_of
    sha_orig = rows[0][-1]
    sha_dup = rows[1][-1]
    assert sha_orig == sha_dup, "byte_copy_of file must have identical sha256"

    # Verify rerender (Case 3 vs Case 4) has different sha256
    sha_case3 = rows[2][-1]
    sha_case4 = rows[3][-1]
    assert sha_case3 != sha_case4, "Different renders must have different sha256"

    # 4. Run end-to-end dataset verification
    verified = verify_dataset(str(samples_dir), build_dir=str(build_dir))
    assert verified is True, "verify_dataset must return True on valid generated dataset"
