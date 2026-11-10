from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
import shutil
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse

from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.models import BatchProcessResult, DecisionResult
from invoice_pipeline.pipeline import process_invoice, process_invoice_batch
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


@router.post("/batch", response_model=BatchProcessResult)
async def process_batch_endpoint(
    files: List[UploadFile] = File(...),
    dry_run: bool = Query(False),
    ocr_engine: Optional[str] = Query(None),
    config: PipelineConfig = Depends(get_config),
):
    upload_dir = Path(config.app.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_paths = []
    for f in files:
        dest_file = upload_dir / f"{uuid.uuid4()}_{f.filename}"
        try:
            with open(dest_file, "wb") as buffer:
                shutil.copyfileobj(f.file, buffer)
            dest_paths.append(dest_file)
        finally:
            f.file.close()

    result = await run_in_threadpool(
        process_invoice_batch,
        dest_paths,
        config=config,
        dry_run=dry_run,
        force_ocr_engine=ocr_engine,
    )
    return result


@router.post("/process/stream")
async def process_invoice_stream_endpoint(
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

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def progress_cb(stage: str, msg: str, pct: float):
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "progress", "stage": stage, "message": msg, "pct": pct},
        )

    def worker():
        try:
            res = process_invoice(
                dest_file,
                config=config,
                dry_run=dry_run,
                force_ocr_engine=ocr_engine,
                progress_callback=progress_cb,
            )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "complete", "result": res.model_dump(mode="json")},
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "error": str(e)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def event_generator():
        fut = loop.run_in_executor(None, worker)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
        await fut

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/batch/stream")
async def process_batch_stream_endpoint(
    files: List[UploadFile] = File(...),
    dry_run: bool = Query(False),
    ocr_engine: Optional[str] = Query(None),
    config: PipelineConfig = Depends(get_config),
):
    upload_dir = Path(config.app.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_paths = []
    for f in files:
        dest_file = upload_dir / f"{uuid.uuid4()}_{f.filename}"
        try:
            with open(dest_file, "wb") as buffer:
                shutil.copyfileobj(f.file, buffer)
            dest_paths.append(dest_file)
        finally:
            f.file.close()

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue()

    def batch_cb(event: dict):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker():
        try:
            process_invoice_batch(
                dest_paths,
                config=config,
                dry_run=dry_run,
                force_ocr_engine=ocr_engine,
                batch_callback=batch_cb,
            )
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "error": str(e)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def event_generator():
        fut = loop.run_in_executor(None, worker)
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
        await fut

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("")
def list_invoices(
    status: Optional[str] = None,
    vendor_id: Optional[str] = None,
    po_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    paged: bool = False,
    db=Depends(get_db),
):
    repo = InvoiceRepo(db)
    if paged or limit is not None or search is not None:
        return repo.list_paged(
            status=status,
            vendor_id=vendor_id,
            po_id=po_id,
            search=search,
            limit=min(limit or 30, 100),
            offset=offset,
        )
    return repo.list_all(status=status, vendor_id=vendor_id, po_id=po_id)


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, response: Response, db=Depends(get_db)):
    repo = InvoiceRepo(db)
    row = repo.get_by_id(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    response.headers["Cache-Control"] = "private, max-age=60, stale-while-revalidate=120"
    if row.get("decision_json"):
        data = json.loads(row["decision_json"])
        if row.get("file_name"):
            data["file_name"] = row["file_name"]
        if row.get("file_path"):
            data["file_path"] = row["file_path"]
        return data
    return dict(row)


@router.api_route("/{invoice_id}/file", methods=["GET", "HEAD"])
def get_invoice_file(
    invoice_id: int,
    db=Depends(get_db),
    config: PipelineConfig = Depends(get_config),
):
    repo = InvoiceRepo(db)
    row = repo.get_by_id(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice record not found")

    file_path = row.get("file_path")
    file_name = row.get("file_name")

    resolved_path: Optional[Path] = None

    # 1. Direct path from DB
    if file_path:
        p = Path(file_path)
        if p.exists() and p.is_file():
            resolved_path = p

    # 2. Check upload directory
    upload_dir = Path(config.app.upload_dir)
    if not resolved_path and file_name and upload_dir.exists():
        direct_in_upload = upload_dir / file_name
        if direct_in_upload.exists() and direct_in_upload.is_file():
            resolved_path = direct_in_upload
        else:
            matches = list(upload_dir.glob(f"*_{file_name}"))
            if matches:
                resolved_path = matches[0]

    # 3. Check decision_json source file_name
    if not resolved_path and row.get("decision_json"):
        try:
            d = json.loads(row["decision_json"])
            fn = d.get("extracted", {}).get("source", {}).get("file_name")
            if fn:
                if (upload_dir / fn).exists():
                    resolved_path = upload_dir / fn
                else:
                    matches = list(upload_dir.glob(f"*_{fn}"))
                    if matches:
                        resolved_path = matches[0]
                    elif (Path("samples") / fn).exists():
                        resolved_path = Path("samples") / fn
        except Exception:
            pass

    # 4. Check samples folder fallback
    if not resolved_path and file_name:
        sample_path = Path("samples") / file_name
        if sample_path.exists() and sample_path.is_file():
            resolved_path = sample_path

    if not resolved_path or not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="No physical document file found on disk for this invoice record (preloaded synthetic record)."
        )

    mime_type, _ = mimetypes.guess_type(str(resolved_path))
    if not mime_type:
        suffix = resolved_path.suffix.lower()
        if suffix == ".pdf":
            mime_type = "application/pdf"
        elif suffix in (".png", ".jpg", ".jpeg"):
            mime_type = f"image/{suffix.replace('.', '')}"
        else:
            mime_type = "application/octet-stream"

    clean_name = file_name or resolved_path.name
    if "_" in clean_name and len(clean_name.split("_")[0]) == 36:
        clean_name = "_".join(clean_name.split("_")[1:])

    return FileResponse(
        path=str(resolved_path),
        media_type=mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{clean_name}"',
            "Cache-Control": "public, max-age=3600",
        },
    )
