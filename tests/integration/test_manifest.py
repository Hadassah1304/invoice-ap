from __future__ import annotations

import csv
import json
from pathlib import Path
import pytest

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.pipeline import process_invoice
from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import ItemRepo, PORepo, VendorRepo


def seed_db_helper(db_path: str, seed_file: str):
    init_db(db_path)
    with open(seed_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = get_connection(db_path)
    v_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)

    for v in data.get("vendors", []):
        v_repo.create(
            vendor_id=v["vendor_id"],
            name=v["name"],
            aliases=v.get("aliases"),
            gstin=v.get("gstin"),
            email_domain=v.get("email_domain"),
            approved=v.get("approved", 1),
            bank_account=v.get("bank_account"),
        )

    for po in data.get("purchase_orders", []):
        po_repo.create(
            po_id=po["po_id"],
            vendor_id=po["vendor_id"],
            po_date=po["po_date"],
            total=po["total"],
            currency=po.get("currency", "INR"),
            status=po.get("status", "OPEN"),
            payment_terms_days=po.get("payment_terms_days", 30),
        )

    for it in data.get("items", []):
        item_repo.create(
            po_id=it["po_id"],
            item_name=it["item_name"],
            description=it.get("description", ""),
            qty_ordered=it["qty_ordered"],
            qty_remaining=it.get("qty_remaining", it["qty_ordered"]),
            unit_price=it["unit_price"],
            uom=it.get("uom", "pcs"),
            tax_rate=it.get("tax_rate", 5.0),
        )

    conn.close()


def test_manifest_e2e(tmp_path):
    seed_file = "samples/seed.json"
    manifest_file = "samples/manifest.csv"

    SERIES_TAGS = {
        "split_1",
        "split_2",
        "split_3",
        "split_4",
        "split_partial_qty",
        "dup_exact",
        "dup_near_format",
        "dup_possible",
        "dup_rescan",
    }

    series_db = str(tmp_path / "manifest_series.db")
    seed_db_helper(series_db, seed_file)
    cfg_series = PipelineConfig(app={"db_path": series_db})
    cfg_series.matching.tier2.min_margin = 0.10

    with open(manifest_file, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rows.sort(key=lambda x: int(x.get("run_order", 0) or 0))

    passed = 0
    total = len(rows)

    indep_counter = 0
    for r in rows:
        f_name = r["file"]
        tag = r.get("edge_case_tag", "")
        pdf_path = Path("samples") / f_name
        exp_dec = r["expected_decision"]
        exp_code = r.get("expected_reason_code")
        exp_po = r.get("expected_po")

        spec_path = Path("samples/specs") / f"{f_name}.extracted.json"
        canned = None
        if spec_path.exists():
            with open(spec_path, "r", encoding="utf-8") as sf:
                canned = json.load(sf)

        if tag in SERIES_TAGS:
            cfg = cfg_series
        else:
            indep_counter += 1
            indep_db = str(tmp_path / f"indep_{indep_counter}.db")
            seed_db_helper(indep_db, seed_file)
            cfg = PipelineConfig(app={"db_path": indep_db})
            cfg.matching.tier2.min_margin = 0.10

        res = process_invoice(pdf_path, config=cfg, pre_extracted_json=canned)

        assert res.decision.value == exp_dec, f"{f_name} failed decision: expected {exp_dec}, got {res.decision.value} ({res.reason_code.value})"
        if exp_code:
            assert res.reason_code.value == exp_code, f"{f_name} failed reason code: expected {exp_code}, got {res.reason_code.value}"
        if exp_po:
            assert res.match.selected_po == exp_po, f"{f_name} failed PO: expected {exp_po}, got {res.match.selected_po}"

        passed += 1

    assert passed == total
