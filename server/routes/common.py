from __future__ import annotations

import os
import shutil
from fastapi import APIRouter, Depends
from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.store.repositories import ItemRepo, PORepo, VendorRepo
from server.deps import get_config, get_db

router = APIRouter(tags=["common"])


@router.get("/api/pos")
def list_pos(db=Depends(get_db)):
    po_repo = PORepo(db)
    cur = db.execute("SELECT * FROM purchase_orders ORDER BY po_date DESC")
    return [dict(r) for r in cur.fetchall()]


@router.get("/api/pos/{po_id}")
def get_po_detail(po_id: str, db=Depends(get_db)):
    po_repo = PORepo(db)
    item_repo = ItemRepo(db)
    vendor_repo = VendorRepo(db)
    po = po_repo.get_by_id(po_id)
    if not po:
        return {"error": "PO not found"}
    items = item_repo.list_by_po(po_id)
    clean_items = []
    for it in items:
        d = dict(it)
        d.pop("embedding", None)
        clean_items.append(d)
    vendor = vendor_repo.get_by_id(po["vendor_id"]) if po.get("vendor_id") else None
    return {"po": po, "items": clean_items, "vendor": vendor}


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
