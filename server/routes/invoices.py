from __future__ import annotations

import json
from pathlib import Path
import shutil
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import DecisionResult
from invoice_pipeline.pipeline import process_invoice
from invoice_pipeline.store.repositories import InvoiceRepo
from server.deps import get_config, get_db

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.post("/process", response_model=DecisionResult)
async def process_invoice_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Query(False),
    ocr_engine: Optional[str] = Query(None),
    config: PipelineConfig = Depends(get_config),
):
    upload_dir = Path(config.app.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_file = upload_dir / f"{uuid.uuid4()}_{file.filename}"
    try:
        with open(dest_file, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    finally:
        file.file.close()

    result = await run_in_threadpool(
        process_invoice,
        dest_file,
        config=config,
        dry_run=dry_run,
        force_ocr_engine=ocr_engine,
    )
    return result


@router.get("")
def list_invoices(
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    po_id: Optional[str] = None,
    db=Depends(get_db),
):
    repo = InvoiceRepo(db)
    return repo.list_all(status=status, vendor_id=vendor_id, po_id=po_id)


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, db=Depends(get_db)):
    repo = InvoiceRepo(db)
    row = repo.get_by_id(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if row.get("decision_json"):
        return json.loads(row["decision_json"])
    return dict(row)
