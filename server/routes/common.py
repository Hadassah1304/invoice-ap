from __future__ import annotations

from __future__ import annotations

import json
import os
import shutil
from typing import Optional
from fastapi import APIRouter, Depends, Response
from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.store.repositories import InvoiceRepo, ItemRepo, PORepo, VendorRepo
from server.deps import get_config, get_db

router = APIRouter(tags=["common"])


@router.get("/api/pos")
def list_pos(
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    paged: bool = False,
    db=Depends(get_db),
):
    where_clauses = ["1=1"]
    params = []
    if search and search.strip():
        s = f"%{search.strip()}%"
        where_clauses.append("(p.po_id LIKE ? OR v.name LIKE ? OR p.vendor_id LIKE ?)")
        params.extend([s, s, s])

    where_sql = " AND ".join(where_clauses)

    count_cur = db.execute(
        f"""SELECT COUNT(p.po_id) as cnt 
            FROM purchase_orders p
            LEFT JOIN vendors v ON p.vendor_id = v.vendor_id
            WHERE {where_sql}""",
        params,
    )
    count_row = count_cur.fetchone()
    total_count = count_row["cnt"] if count_row else 0

    query = f"""
        SELECT 
            p.*, 
            v.name as vendor_name,
            COALESCE(inv.cnt, 0) as linked_invoices_count,
            COALESCE(inv.billed_approved, 0.0) as billed_approved,
            COALESCE(inv.billed_total, 0.0) as billed_total
        FROM purchase_orders p
        LEFT JOIN vendors v ON p.vendor_id = v.vendor_id
        LEFT JOIN (
            SELECT 
                po_id,
                COUNT(*) as cnt,
                SUM(CASE WHEN status = 'APPROVED' THEN total ELSE 0 END) as billed_approved,
                SUM(CASE WHEN status IN ('APPROVED', 'PENDING_REVIEW', 'NEEDS_REVIEW') THEN total ELSE 0 END) as billed_total
            FROM invoices
            WHERE po_id IS NOT NULL AND po_id != ''
            GROUP BY po_id
        ) inv ON p.po_id = inv.po_id
        WHERE {where_sql}
        ORDER BY p.po_date DESC
    """

    if paged or limit is not None or search is not None:
        paged_params = list(params) + [min(limit or 25, 100), offset]
        query += " LIMIT ? OFFSET ?"
        cur = db.execute(query, paged_params)
    else:
        cur = db.execute(query, params)

    po_rows = [dict(r) for r in cur.fetchall()]
    results = []
    for po in po_rows:
        total_budget = float(po.get("total") or 0.0)
        billed_approved = float(po.get("billed_approved") or 0.0)
        billed_total = float(po.get("billed_total") or 0.0)
        billed_pending = max(0.0, billed_total - billed_approved)
        remaining = round(max(0.0, total_budget - billed_total), 2)
        util_pct = round((billed_total / total_budget) * 100, 1) if total_budget > 0 else 0.0

        po_dict = dict(po)
        po_dict["total_budget"] = total_budget
        po_dict["billed_approved"] = billed_approved
        po_dict["billed_pending"] = billed_pending
        po_dict["billed_total"] = billed_total
        po_dict["remaining_balance"] = remaining
        po_dict["utilization_pct"] = util_pct
        po_dict["linked_invoices_count"] = int(po.get("linked_invoices_count") or 0)
        results.append(po_dict)

    if paged or limit is not None or search is not None:
        return {
            "items": results,
            "total": total_count,
            "limit": limit or 25,
            "offset": offset,
            "has_more": (offset + len(results)) < total_count,
        }
    return results


@router.get("/api/pos/{po_id}")
def get_po_detail(
    po_id: str,
    response: Response,
    exclude_invoice_id: Optional[int] = None,
    db=Depends(get_db),
):
    po_repo = PORepo(db)
    item_repo = ItemRepo(db)
    vendor_repo = VendorRepo(db)
    inv_repo = InvoiceRepo(db)

    po = po_repo.get_by_id(po_id)
    if not po:
        return {"error": "PO not found"}

    response.headers["Cache-Control"] = "private, max-age=60, stale-while-revalidate=120"

    po_dict = dict(po)
    total_budget = float(po_dict.get("total") or 0.0)
    billed_approved = inv_repo.get_po_consumed_amount(po_id, include_pending=False, exclude_invoice_id=exclude_invoice_id)
    billed_total = inv_repo.get_po_consumed_amount(po_id, include_pending=True, exclude_invoice_id=exclude_invoice_id)
    billed_pending = max(0.0, billed_total - billed_approved)
    remaining = round(max(0.0, total_budget - billed_total), 2)
    util_pct = round((billed_total / total_budget) * 100, 1) if total_budget > 0 else 0.0

    items = item_repo.list_by_po(po_id, exclude_invoice_id=exclude_invoice_id)
    clean_items = []
    for it in items:
        d = dict(it)
        d.pop("embedding", None)
        clean_items.append(d)

    vendor = vendor_repo.get_by_id(po["vendor_id"]) if po.get("vendor_id") else None
    if vendor:
        po_dict["vendor_name"] = vendor.get("name")

    # Fetch linked invoices
    cur_invs = db.execute(
        """SELECT invoice_id, vendor_id, invoice_no_raw, invoice_no_norm, 
                  invoice_date, total, currency, status, match_method, 
                  decision_json, file_name, file_path, created_at 
           FROM invoices 
           WHERE po_id = ? 
           ORDER BY invoice_id DESC""",
        (po_id,),
    )
    linked_invoices = []
    for row in cur_invs.fetchall():
        inv = dict(row)
        confidence = None
        reason_code = None
        summary = None
        if inv.get("decision_json"):
            try:
                dec = json.loads(inv["decision_json"])
                confidence = dec.get("confidence")
                reason_code = dec.get("reason_code")
                summary = dec.get("summary")
            except Exception:
                pass
        inv["confidence"] = confidence
        inv["reason_code"] = reason_code
        inv["summary"] = summary
        linked_invoices.append(inv)

    balance = {
        "currency": po_dict.get("currency") or "INR",
        "total_budget": total_budget,
        "billed_approved": billed_approved,
        "billed_pending": billed_pending,
        "billed_total": billed_total,
        "remaining_balance": remaining,
        "utilization_pct": util_pct,
        "is_overbilled": billed_total > total_budget,
    }

    return {
        "po": po_dict,
        "items": clean_items,
        "vendor": vendor,
        "balance": balance,
        "invoices": linked_invoices,
    }


@router.get("/api/vendors")
def list_vendors(db=Depends(get_db)):
    repo = VendorRepo(db)
    return repo.list_all()


@router.get("/api/config")
def get_public_config(config: PipelineConfig = Depends(get_config)):
    cfg_dict = config.model_dump()
    # Redact sensitive fields
    if "llm" in cfg_dict:
        cfg_dict["llm"]["api_key"] = "[REDACTED]"
    return cfg_dict


@router.get("/api/health")
def health_check(config: PipelineConfig = Depends(get_config)):
    key_env = config.llm.api_key_env if config and config.llm else "EXPLABS_API_KEY"
    has_key = bool(
        os.environ.get(key_env)
        or os.environ.get("EXPLABS_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    )
    return {
        "status": "healthy",
        "ocr_engines": ["rapidocr", "tesseract"],
        "llm_key_present": has_key,
    }
