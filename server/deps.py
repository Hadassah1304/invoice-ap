from __future__ import annotations

import os
from invoice_pipeline.config import PipelineConfig, load_config
from invoice_pipeline.store.db import get_connection

_CONFIG: PipelineConfig | None = None


def get_config() -> PipelineConfig:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG


def get_db():
    cfg = get_config()
    conn = get_connection(cfg.app.db_path)
    try:
        yield conn
    finally:
        conn.close()
