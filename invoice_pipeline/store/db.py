from __future__ import annotations

import contextlib
import datetime
from pathlib import Path
import re
import sqlite3
from typing import Generator, Optional


def _safe_convert_date(val: bytes) -> datetime.date:
    """Resilient sqlite3 DATE converter that gracefully parses ISO, British, and text-month dates."""
    s = val.decode("utf-8").strip()
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        pass
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%b %d %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        parts = [int(p) for p in re.findall(r"\d+", s)]
        if len(parts) >= 3:
            if parts[0] > 1900:
                return datetime.date(parts[0], parts[1], parts[2])
            elif parts[2] > 1900:
                return datetime.date(parts[2], parts[1], parts[0])
    except Exception:
        pass
    return datetime.date.today()


sqlite3.register_converter("date", _safe_convert_date)
sqlite3.register_converter("DATE", _safe_convert_date)


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
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def checkpoint_db(db_path: str) -> None:
    """Safely flush WAL journal to the main database file."""
    path = Path(db_path)
    if not path.exists():
        return
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.execute("PRAGMA optimize;")
        finally:
            conn.close()
    except Exception:
        pass


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
