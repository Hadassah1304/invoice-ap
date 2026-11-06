from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from invoice_pipeline.config import load_config
from invoice_pipeline.store.db import init_db
from server.routes import common, invoices, review


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure DB and static directory exist
    cfg = load_config()
    init_db(cfg.app.db_path)
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Invoice-to-Decision AP Automation API", lifespan=lifespan)

cfg = load_config()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(invoices.router)
app.include_router(review.router)
app.include_router(common.router)

# Mount static frontend
static_path = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
