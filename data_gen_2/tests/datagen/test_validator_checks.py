"""Unit tests for each validator check (V01 - V21).

Verifies that:
- Clean fixtures pass each check.
- Deliberately broken fixtures fire the exact validation code.
"""

from decimal import Decimal
from pathlib import Path
import pytest

from datagen.compile import compile_dataset
from datagen.loader import load_authored_base
from tests.datagen.test_integration import create_minimal_fixture


def test_validator_v02_derived_fields_rejected(tmp_path):
    create_minimal_fixture(tmp_path)
    # Inject derived field into core.json
    import json
    with open(tmp_path / "core.json", "r") as f:
        core_data = json.load(f)
    core_data["vendors"][0]["grand_total"] = 100.0  # Derived field violation
    with open(tmp_path / "core.json", "w") as f:
        json.dump(core_data, f)

    loaded = load_authored_base(tmp_path)
    result = compile_dataset(loaded, seed=42)
    assert any(f["code"] == "V02" and f["severity"] == "ERROR" for f in result.validation_report_json["findings"])


def test_validator_v03_v04_broken_ids_and_refs(tmp_path):
    create_minimal_fixture(tmp_path)
    import json
    with open(tmp_path / "family_R.json", "r") as f:
        fam = json.load(f)
    fam["scenarios"][0]["invoice"]["vendor_id"] = "V-NONEXISTENT"
    fam["scenarios"][0]["scenario_id"] = "INVALID-ID-01"
    with open(tmp_path / "family_R.json", "w") as f:
        json.dump(fam, f)

    loaded = load_authored_base(tmp_path)
    result = compile_dataset(loaded, seed=42)
    findings = result.validation_report_json["findings"]
    assert any(f["code"] == "V03" for f in findings)
    assert any(f["code"] == "V04" for f in findings)


def test_validator_v06_ownership_mismatch(tmp_path):
    create_minimal_fixture(tmp_path)
    import json
    with open(tmp_path / "family_R.json", "r") as f:
        fam = json.load(f)
    # Vendor V-BURGER belongs to family B, using it in R
    fam["scenarios"][0]["invoice"]["vendor_id"] = "V-BURGER"
    with open(tmp_path / "family_R.json", "w") as f:
        json.dump(fam, f)

    loaded = load_authored_base(tmp_path)
    result = compile_dataset(loaded, seed=42)
    findings = result.validation_report_json["findings"]
    assert any(f["code"] == "V06" for f in findings)


def test_validator_v10_closed_po_remaining_money(tmp_path):
    create_minimal_fixture(tmp_path)
    import json
    with open(tmp_path / "family_R.json", "r") as f:
        fam = json.load(f)
    # Set status CLOSED without preload
    fam["pos"][0]["status"] = "CLOSED"
    with open(tmp_path / "family_R.json", "w") as f:
        json.dump(fam, f)

    loaded = load_authored_base(tmp_path)
    result = compile_dataset(loaded, seed=42)
    findings = result.validation_report_json["findings"]
    assert any(f["code"] == "V10" for f in findings)


def test_validator_v12_invoice_date_before_po(tmp_path):
    create_minimal_fixture(tmp_path)
    import json
    with open(tmp_path / "family_R.json", "r") as f:
        fam = json.load(f)
    # PO is offset -45, set normal invoice to offset -50 (before PO)
    fam["scenarios"][0]["invoice"]["invoice_date"]["offset_days"] = -50
    with open(tmp_path / "family_R.json", "w") as f:
        json.dump(fam, f)

    loaded = load_authored_base(tmp_path)
    result = compile_dataset(loaded, seed=42)
    findings = result.validation_report_json["findings"]
    assert any(f["code"] == "V12" for f in findings)
