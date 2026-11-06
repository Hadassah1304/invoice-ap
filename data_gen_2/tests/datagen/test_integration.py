"""Integration tests and determinism tests for datagen.

Builds a hand-crafted fixture dataset (minimal fixture from contract section 10 + variants)
and verifies:
- End-to-end compile and schemas
- Exact byte determinism across runs
"""

import json
from pathlib import Path
import tempfile
import pytest

from datagen.compile import compile_dataset
from datagen.loader import load_authored_base


def create_minimal_fixture(base_dir: Path):
    # core.json
    core_data = {
        "schema_version": 1,
        "vendors": [
            {
                "vendor_id": "V-TEST",
                "name": "Test Vendor Pvt Ltd",
                "aliases": ["Test Vendor"],
                "gstin": "27AAAAA0000A1Z5",
                "email_domain": "testvendor.in",
                "phone": "+91 9876543210",
                "address": "123 Industrial Area, Mumbai",
                "approved": True,
                "bank_account": "HDFC00011112222",
                "owner_family": "R",
            },
            {
                "vendor_id": "V-BURGER",
                "name": "Burger Supplies Co",
                "aliases": [],
                "gstin": "36BBBBB0000B1Z6",
                "email_domain": "burgersupplies.in",
                "phone": "+91 9876543211",
                "address": "456 Food Park, Hyderabad",
                "approved": True,
                "bank_account": "SBIN00033334444",
                "owner_family": "B",
            },
        ],
        "catalog": [
            {
                "sku": "SKU-900",
                "name": "Test Widget 10g",
                "description": "Standard 10g testing widget",
                "uom": "pcs",
                "unit_price": 100.00,
                "tax_rate": 5,
                "category": "hardware",
                "twin_group": None,
                "distinguisher": None,
                "reworded": ["Testing Widget 10g (Sample)"],
                "unique_item": True,
            },
            {
                "sku": "SKU-901",
                "name": "Industrial Fastener M8",
                "description": "High tensile fastener",
                "uom": "pcs",
                "unit_price": 50.00,
                "tax_rate": 18,
                "category": "hardware",
                "twin_group": None,
                "distinguisher": None,
                "reworded": [],
                "unique_item": False,
            },
        ],
    }
    with open(base_dir / "core.json", "w") as f:
        json.dump(core_data, f)

    # family_R.json
    family_r_data = {
        "schema_version": 1,
        "family": "R",
        "pos": [
            {
                "po_id": "PO-R-TEST",
                "vendor_id": "V-TEST",
                "po_date": {"offset_days": -45},
                "currency": "INR",
                "status": "OPEN",
                "payment_terms_days": 30,
                "group": "test",
                "lines": [
                    {
                        "line_no": 1,
                        "sku": "SKU-900",
                        "item_name": "Test Widget 10g",
                        "description": "Standard 10g testing widget",
                        "uom": "pcs",
                        "qty_ordered": 10,
                        "unit_price": 100.00,
                        "tax_rate": 5,
                    }
                ],
            }
        ],
        "ledger_preload": [],
        "scenarios": [
            {
                "scenario_id": "SC-R-TEST-01",
                "tag": "happy_explicit",
                "description": "Minimal fixture scenario",
                "po_id": "PO-R-TEST",
                "series": None,
                "relation": {"type": "none", "scenario_id": None},
                "invoice": {
                    "invoice_no": "TST/26/1001",
                    "invoice_date": {"offset_days": -20},
                    "vendor_id": "V-TEST",
                    "po_reference": "PO-R-TEST",
                    "currency": "INR",
                    "lines": [
                        {
                            "po_line_no": 1,
                            "description": None,
                            "qty": 4,
                            "unit_price": 100.00,
                            "tax_rate": 5,
                        }
                    ],
                    "extra_lines": [],
                },
                "derive_from": None,
                "mutation": {"name": "none", "params": {}},
                "intent": {
                    "decision": "APPROVED",
                    "decision_accepted": ["APPROVED"],
                    "reason_codes_accepted": ["OK"],
                    "po_id": "PO-R-TEST",
                    "confidence": "firm",
                    "expect_cached": False,
                    "config_dependency": [],
                    "notes": "",
                },
                "render": {
                    "layout": "auto",
                    "degrade": "none",
                    "number_format": "auto",
                    "currency_style": "auto",
                    "date_style": "auto",
                },
            }
        ],
    }
    with open(base_dir / "family_R.json", "w") as f:
        json.dump(family_r_data, f)

    # Empty valid family_B, family_I, family_N
    for fam in ["B", "I", "N"]:
        data = {
            "schema_version": 1,
            "family": fam,
            "pos": [],
            "ledger_preload": [],
            "scenarios": [],
        }
        with open(base_dir / f"family_{fam}.json", "w") as f:
            json.dump(data, f)


def test_minimal_fixture_compiles_and_passes_validation(tmp_path):
    create_minimal_fixture(tmp_path)
    loaded = load_authored_base(tmp_path)
    result = compile_dataset(loaded, seed=42)

    # Errors should be 0 (only warnings for coverage targets)
    errors = [f for f in result.validation_report_json["findings"] if f["severity"] == "ERROR"]
    assert len(errors) == 0, f"Unexpected validation errors: {errors}"
    assert result.cases_output.meta.case_count == 1
    case = result.cases_output.cases[0]
    assert case.case_id == "SC-R-TEST-01"
    # Check calculated totals: 4 x 100.00 = 400.00, 5% tax = 20.00, grand total 420.00
    assert case.document.subtotal == 400.0
    assert case.document.tax_total == 20.0
    assert case.document.grand_total == 420.0


def test_determinism_byte_identical(tmp_path):
    create_minimal_fixture(tmp_path)
    loaded1 = load_authored_base(tmp_path)
    res1 = compile_dataset(loaded1, seed=42)

    loaded2 = load_authored_base(tmp_path)
    res2 = compile_dataset(loaded2, seed=42)

    json1 = json.dumps(res1.cases_output.model_dump(), sort_keys=True, indent=2, ensure_ascii=False)
    json2 = json.dumps(res2.cases_output.model_dump(), sort_keys=True, indent=2, ensure_ascii=False)
    assert json1 == json2

    state1 = json.dumps(res1.finalized_state.state_output.model_dump(), sort_keys=True, indent=2, ensure_ascii=False)
    state2 = json.dumps(res2.finalized_state.state_output.model_dump(), sort_keys=True, indent=2, ensure_ascii=False)
    assert state1 == state2
