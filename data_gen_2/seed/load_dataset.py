from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Optional
import numpy as np

from invoice_pipeline.store.db import get_connection, init_db
from invoice_pipeline.store.repositories import InvoiceRepo, ItemRepo, PORepo, VendorRepo


def load_dataset_into_db(
    seed_json_path: str,
    db_path: str,
    reset: bool = False,
) -> Dict[str, int]:
    """Load vendors, POs, items with embeddings, and ledger preload into the database.
    
    Uses the pipeline's own repositories inside a single transaction ('BEGIN IMMEDIATE').
    Asserts that remaining quantities and balances match state.
    """
    db_file = Path(db_path)
    if reset and db_file.exists():
        try:
            os.remove(db_file)
            shm = Path(f"{db_path}-shm")
            wal = Path(f"{db_path}-wal")
            if shm.exists():
                os.remove(shm)
            if wal.exists():
                os.remove(wal)
        except Exception:
            pass

    # Ensure DB tables exist
    db_file.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(db_file))

    with open(seed_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = get_connection(str(db_file))
    v_repo = VendorRepo(conn)
    po_repo = PORepo(conn)
    item_repo = ItemRepo(conn)
    inv_repo = InvoiceRepo(conn)

    counts = {"vendors": 0, "pos": 0, "items": 0, "preloaded_invoices": 0}

    try:
        conn.execute("BEGIN IMMEDIATE;")

        # 1. Vendors
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
            counts["vendors"] += 1

        # 2. Purchase Orders
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
            counts["pos"] += 1

        # 3. PO Items
        po_item_map: Dict[Tuple[str, int], int] = {}
        po_item_order_map: Dict[Tuple[str, int], int] = {}
        po_item_counts: Dict[str, int] = {}

        for it in data.get("items", []):
            po_id = it["po_id"]
            line_no = it.get("line_no", 1)
            order_idx = po_item_counts.get(po_id, 1)
            po_item_counts[po_id] = order_idx + 1

            emb = None
            if "embedding" in it and it["embedding"]:
                raw_bytes = base64.b64decode(it["embedding"])
                emb = np.frombuffer(raw_bytes, dtype=np.float32)

            row_id = item_repo.create(
                po_id=po_id,
                item_name=it["item_name"],
                description=it.get("description", ""),
                qty_ordered=it["qty_ordered"],
                qty_remaining=it.get("qty_remaining", it["qty_ordered"]),
                unit_price=it["unit_price"],
                embedding=emb,
                uom=it.get("uom", "pcs"),
                tax_rate=it.get("tax_rate", 0.0),
            )
            po_item_map[(po_id, line_no)] = row_id
            po_item_order_map[(po_id, order_idx)] = row_id
            counts["items"] += 1

        # 4. Ledger Preload
        for preload in data.get("ledger_preload", []):
            preload_id = preload["preload_id"]
            decision_dict = {
                "request_id": f"preload_{preload_id}",
                "decision": "APPROVED",
                "reason_code": "OK",
                "confidence": 1.0,
                "summary": f"Preloaded ledger entry {preload_id}",
                "reasoning": ["Preloaded historical transaction"],
                "source": "preload",
                "cached": False,
            }

            inv_id = inv_repo.create(
                vendor_id=preload["vendor_id"],
                invoice_no_raw=preload["invoice_no"],
                invoice_no_norm=preload["invoice_no_norm"],
                invoice_date=preload["invoice_date"],
                total=preload["total"],
                currency=preload.get("currency", "INR"),
                po_id=preload["po_id"],
                match_method="EXPLICIT",
                status="APPROVED",
                decision_json=json.dumps(decision_dict),
                file_hash=f"preload:{preload_id}",
            )

            for idx, line in enumerate(preload.get("lines", [])):
                po_line_no = line.get("po_line_no", idx + 1)
                po_item_row_id = po_item_map.get((preload["po_id"], po_line_no)) or po_item_order_map.get((preload["po_id"], po_line_no))

                inv_repo.add_line(
                    invoice_id=inv_id,
                    po_item_row_id=po_item_row_id,
                    description=line.get("description", ""),
                    quantity=line.get("qty"),
                    unit_price=line.get("unit_price"),
                    line_total=line.get("line_total", float(line.get("qty", 0)) * float(line.get("unit_price", 0))),
                )

            counts["preloaded_invoices"] += 1

        conn.execute("COMMIT;")

    except Exception:
        conn.execute("ROLLBACK;")
        conn.close()
        raise

    # 5. Assertions: check remaining quantities and balances
    try:
        # Check PO balances
        for po in data.get("purchase_orders", []):
            po_id = po["po_id"]
            expected_consumed = sum(
                p["total"] for p in data.get("ledger_preload", []) if p["po_id"] == po_id
            )
            actual_consumed = inv_repo.get_po_consumed_amount(po_id)
            if abs(expected_consumed - actual_consumed) > 0.01:
                raise AssertionError(
                    f"PO {po_id} consumed mismatch: expected {expected_consumed}, got {actual_consumed}"
                )

        # Check item remaining quantities
        for it in data.get("items", []):
            po_id = it["po_id"]
            db_items = item_repo.list_by_po(po_id)
            matching = [x for x in db_items if x["item_name"] == it["item_name"]]
            if matching:
                actual_rem = float(matching[0]["qty_remaining"])
                expected_rem = float(it["qty_remaining"])
                if abs(actual_rem - expected_rem) > 0.01:
                    raise AssertionError(
                        f"PO item {po_id} / {it['item_name']} qty_remaining mismatch: expected {expected_rem}, got {actual_rem}"
                    )
    finally:
        conn.close()

    print(
        f"Successfully loaded database at {db_path}: "
        f"{counts['vendors']} vendors, {counts['pos']} purchase orders, "
        f"{counts['items']} items, {counts['preloaded_invoices']} preloaded invoices."
    )
    return counts


def main():
    parser = argparse.ArgumentParser(description="Load seed.json dataset into pipeline database.")
    parser.add_argument("--seed", required=True, help="Path to seed.json")
    parser.add_argument("--db", required=True, help="Path to SQLite database file")
    parser.add_argument("--reset", action="store_true", help="Recreate database before loading")
    args = parser.parse_args()

    load_dataset_into_db(args.seed, args.db, reset=args.reset)


if __name__ == "__main__":
    main()
