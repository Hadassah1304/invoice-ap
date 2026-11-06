from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import DecisionResult
from invoice_pipeline.pipeline import resolve_invoice
from invoice_pipeline.store.repositories import InvoiceRepo
from server.deps import get_config, get_db

router = APIRouter(prefix="/api/invoices", tags=["review"])


class ResolveRequest(BaseModel):
    action: str  # approve | reject | select_po | edit_field | confirm_vendor
    po_id: Optional[str] = None
    vendor_id: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


@router.post("/{invoice_id}/resolve", response_model=DecisionResult)
async def resolve_invoice_endpoint(
    invoice_id: int,
    body: ResolveRequest,
    config: PipelineConfig = Depends(get_config),
    db=Depends(get_db),
):
    inv_repo = InvoiceRepo(db)
    row = inv_repo.get_by_id(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Invoice #{invoice_id} not found in ledger")

    overrides = {}
    if body.action == "select_po" and body.po_id:
        overrides["po_id"] = body.po_id
    if body.vendor_id:
        overrides["vendor_id"] = body.vendor_id
    if body.fields:
        overrides["fields"] = body.fields

    try:
        result = await run_in_threadpool(
            resolve_invoice,
            invoice_id=invoice_id,
            action=body.action,
            overrides=overrides,
            config=config,
            note=body.note,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
