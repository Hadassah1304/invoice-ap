from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

from invoice_pipeline.store.embeddings import get_embedder

logger = logging.getLogger(__name__)


def build_seed_json(
    state_json_path: str,
    out_seed_path: str,
    embedder_backend: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert state.json into seed.json suitable for loading into the pipeline database.
    
    Computes float32 embeddings per po_item using the specified backend (minilm or tfidf).
    """
    with open(state_json_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    # Initialize embedder
    backend_chosen = embedder_backend or "minilm"
    try:
        embedder = get_embedder(backend_chosen)
        # Test availability
        if not embedder.is_available():
            raise RuntimeError(f"Backend {backend_chosen} is not available")
    except Exception as e:
        logger.warning(f"Could not initialize {backend_chosen} embedder: {e}. Falling back to tfidf.")
        backend_chosen = "tfidf"
        embedder = get_embedder("tfidf")

    meta = {
        "seed": state.get("meta", {}).get("seed", 42),
        "ref_date": state.get("meta", {}).get("reference_date", "2026-11-06"),
        "embeddings_backend": backend_chosen,
    }

    # 1. Vendors
    vendors: List[Dict[str, Any]] = []
    for v in state.get("vendors", []):
        vendors.append({
            "vendor_id": v["vendor_id"],
            "name": v["name"],
            "aliases": v.get("aliases", []),
            "gstin": v.get("gstin"),
            "email_domain": v.get("email_domain"),
            "phone": v.get("phone"),
            "address": v.get("address"),
            "approved": 1 if v.get("approved", True) else 0,
            "bank_account": v.get("bank_account"),
        })

    # 2. Purchase Orders
    purchase_orders: List[Dict[str, Any]] = []
    for po in state.get("purchase_orders", []):
        purchase_orders.append({
            "po_id": po["po_id"],
            "vendor_id": po["vendor_id"],
            "po_date": po["po_date"],
            "currency": po.get("currency", "INR"),
            "total": float(po["total"]),
            "status": po["status"],
            "payment_terms_days": po.get("payment_terms_days", 30),
        })

    # 3. PO Items (flattened lines from purchase orders)
    items: List[Dict[str, Any]] = []
    for po in state.get("purchase_orders", []):
        po_id = po["po_id"]
        for line in po.get("lines", []):
            item_name = line["item_name"]
            desc = line.get("description", "") or ""
            text_to_embed = f"{item_name} {desc}".strip()

            emb_vec = embedder.embed_text(text_to_embed)
            emb_float32 = emb_vec.astype(np.float32)
            emb_b64 = base64.b64encode(emb_float32.tobytes()).decode("ascii")

            items.append({
                "po_id": po_id,
                "line_no": line.get("line_no", 1),
                "sku": line.get("sku"),
                "item_name": item_name,
                "description": desc,
                "qty_ordered": float(line["qty_ordered"]),
                "qty_remaining": float(line["qty_remaining"]),
                "unit_price": float(line["unit_price"]),
                "uom": line.get("uom", "pcs"),
                "tax_rate": float(line.get("tax_rate", 0)),
                "embedding": emb_b64,
            })

    # 4. Ledger Preload
    ledger_preload = state.get("ledger_preload", [])

    seed_dict = {
        "metadata": meta,
        "vendors": vendors,
        "purchase_orders": purchase_orders,
        "items": items,
        "ledger_preload": ledger_preload,
    }

    out_path = Path(out_seed_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(seed_dict, f, indent=2)

    return seed_dict
