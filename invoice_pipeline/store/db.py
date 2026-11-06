from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Generator, Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    """Connect to SQLite database with foreign keys and WAL enabled."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        timeout=30.0,
        check_same_thread=False,
        isolation_level=None,  # We manage transactions explicitly
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection, mode: str = "IMMEDIATE") -> Generator[sqlite3.Connection, None, None]:
    """Atomic transaction context manager."""
    conn.execute(f"BEGIN {mode};")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise


def init_db(db_path: str, schema_path: Optional[str] = None) -> None:
    """Initialize database tables using schema.sql."""
    if schema_path is None:
        schema_path = str(Path(__file__).parent / "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = get_connection(db_path)
    try:
        conn.executescript(sql)
    finally:
        conn.close()
