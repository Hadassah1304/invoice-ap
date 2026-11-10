from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np


class VendorRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_by_id(self, vendor_id: str) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_gstin(self, gstin: str) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM vendors WHERE gstin = ?", (gstin.strip().upper(),))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_email_domain(self, domain: str) -> List[dict]:
        cur = self.conn.execute(
            "SELECT * FROM vendors WHERE LOWER(email_domain) = LOWER(?)", (domain.strip(),)
        )
        return [dict(r) for r in cur.fetchall()]

    def list_all(self) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM vendors")
        return [dict(r) for r in cur.fetchall()]

    def create(
        self,
        vendor_id: str,
        name: str,
        aliases: Optional[List[str]] = None,
        gstin: Optional[str] = None,
        email_domain: Optional[str] = None,
        approved: int = 1,
        bank_account: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO vendors
               (vendor_id, name, aliases, gstin, email_domain, approved, bank_account)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                vendor_id,
                name,
                json.dumps(aliases or []),
                gstin.strip().upper() if gstin else None,
                email_domain.strip().lower() if email_domain else None,
                approved,
                bank_account,
            ),
        )


class PORepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_by_id(self, po_id: str) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_by_vendor(self, vendor_id: str, statuses: Optional[List[str]] = None) -> List[dict]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            query = f"SELECT * FROM purchase_orders WHERE vendor_id = ? AND status IN ({placeholders})"
            cur = self.conn.execute(query, [vendor_id] + statuses)
        else:
            cur = self.conn.execute("SELECT * FROM purchase_orders WHERE vendor_id = ?", (vendor_id,))
        return [dict(r) for r in cur.fetchall()]

    def update_status(self, po_id: str, status: str) -> None:
        self.conn.execute("UPDATE purchase_orders SET status = ? WHERE po_id = ?", (status, po_id))

    def create(
        self,
        po_id: str,
        vendor_id: str,
        po_date: str,
        total: float,
        currency: str = "INR",
        status: str = "OPEN",
        payment_terms_days: Optional[int] = 30,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO purchase_orders
               (po_id, vendor_id, po_date, currency, total, status, payment_terms_days)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (po_id, vendor_id, po_date, currency, total, status, payment_terms_days),
        )


class ItemRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_by_po(self, po_id: str) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM po_items WHERE po_id = ?", (po_id,))
        return [dict(r) for r in cur.fetchall()]

    def list_all_open(self) -> List[dict]:
        # Filter for both OPEN/PARTIAL PO and lines with qty_remaining > 0
        cur = self.conn.execute(
            """SELECT i.*, p.vendor_id, p.status as po_status, p.currency
               FROM po_items i
               JOIN purchase_orders p ON i.po_id = p.po_id
               WHERE p.status IN ('OPEN', 'PARTIAL') AND i.qty_remaining > 0"""
        )
        return [dict(r) for r in cur.fetchall()]

    def create(
        self,
        po_id: str,
        item_name: str,
        description: str,
        qty_ordered: float,
        qty_remaining: float,
        unit_price: float,
        embedding: Optional[np.ndarray] = None,
        uom: Optional[str] = None,
        tax_rate: Optional[float] = None,
    ) -> int:
        blob = embedding.astype(np.float32).tobytes() if embedding is not None else None
        cur = self.conn.execute(
            """INSERT INTO po_items
               (po_id, item_name, description, embedding, qty_ordered, qty_remaining, unit_price, uom, tax_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                po_id,
                item_name,
                description,
                blob,
                qty_ordered,
                qty_remaining,
                unit_price,
                uom,
                tax_rate,
            ),
        )
        return cur.lastrowid

    def decrement_qty(self, row_id: int, qty: float) -> None:
        self.conn.execute(
            "UPDATE po_items SET qty_remaining = MAX(0, qty_remaining - ?) WHERE row_id = ?",
            (qty, row_id),
        )

    def restore_qty(self, row_id: int, qty: float) -> None:
        self.conn.execute(
            "UPDATE po_items SET qty_remaining = MIN(qty_ordered, qty_remaining + ?) WHERE row_id = ?",
            (qty, row_id),
        )


class InvoiceRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_by_file_hash(self, file_hash: str) -> Optional[dict]:
        if not file_hash:
            return None
        cur = self.conn.execute("SELECT * FROM invoices WHERE file_hash = ?", (file_hash,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_by_id(self, invoice_id: int) -> Optional[dict]:
        cur = self.conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def find_duplicate_exact(
        self, vendor_id: str, invoice_no_norm: str, exclude_invoice_id: Optional[int] = None
    ) -> Optional[dict]:
        if not invoice_no_norm or invoice_no_norm.strip() == "":
            return None
        query = """SELECT * FROM invoices
                   WHERE vendor_id = ? AND invoice_no_norm = ? AND status != 'REJECTED'"""
        params = [vendor_id, invoice_no_norm]
        if exclude_invoice_id:
            query += " AND invoice_id != ?"
            params.append(exclude_invoice_id)
        cur = self.conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def find_near_duplicates(
        self,
        vendor_id: str,
        total: float,
        invoice_date: str,
        window_days: int = 7,
        amount_tol_pct: float = 0.0,
        exclude_invoice_id: Optional[int] = None,
    ) -> List[dict]:
        query = """SELECT * FROM invoices
                   WHERE vendor_id = ? AND status != 'REJECTED'
                   AND abs(julianday(invoice_date) - julianday(?)) <= ?
                   AND abs(total - ?) <= (? * ? / 100.0)"""
        params = [vendor_id, invoice_date, window_days, total, total, amount_tol_pct]
        if exclude_invoice_id:
            query += " AND invoice_id != ?"
            params.append(exclude_invoice_id)
        cur = self.conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]

    def list_all(
        self,
        status: Optional[str] = None,
        vendor_id: Optional[str] = None,
        po_id: Optional[str] = None,
    ) -> List[dict]:
        query = "SELECT * FROM invoices WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if vendor_id:
            query += " AND vendor_id = ?"
            params.append(vendor_id)
        if po_id:
            query += " AND po_id = ?"
            params.append(po_id)
        query += " ORDER BY invoice_id DESC"
        cur = self.conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]

    def list_paged(
        self,
        status: Optional[str] = None,
        vendor_id: Optional[str] = None,
        po_id: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        base_where = " WHERE 1=1"
        params: List[Any] = []
        if status:
            if status in ("NEEDS_REVIEW", "PENDING_REVIEW"):
                base_where += " AND status IN ('NEEDS_REVIEW', 'PENDING_REVIEW')"
            else:
                base_where += " AND status = ?"
                params.append(status)
        if vendor_id:
            base_where += " AND vendor_id = ?"
            params.append(vendor_id)
        if po_id:
            base_where += " AND po_id = ?"
            params.append(po_id)
        if search and search.strip():
            s = f"%{search.strip()}%"
            base_where += " AND (invoice_no_raw LIKE ? OR invoice_no_norm LIKE ? OR vendor_id LIKE ?)"
            params.extend([s, s, s])

        # Get filtered total
        count_cur = self.conn.execute(f"SELECT COUNT(*) as cnt FROM invoices{base_where}", params)
        count_row = count_cur.fetchone()
        total_filtered = count_row["cnt"] if count_row else 0

        # Get global counts across all statuses for sidebar chips
        counts_cur = self.conn.execute(
            """SELECT 
                 COUNT(*) as all_cnt,
                 SUM(CASE WHEN status IN ('NEEDS_REVIEW', 'PENDING_REVIEW') THEN 1 ELSE 0 END) as review_cnt,
                 SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) as rejected_cnt,
                 SUM(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) as approved_cnt
               FROM invoices"""
        )
        counts_row = counts_cur.fetchone()
        counts = {
            "all": counts_row["all_cnt"] if counts_row else 0,
            "review": counts_row["review_cnt"] if counts_row else 0,
            "rejected": counts_row["rejected_cnt"] if counts_row else 0,
            "approved": counts_row["approved_cnt"] if counts_row else 0,
        }

        # Query paged items
        paged_params = list(params) + [limit, offset]
        query = f"SELECT * FROM invoices{base_where} ORDER BY invoice_id DESC LIMIT ? OFFSET ?"
        cur = self.conn.execute(query, paged_params)
        items = [dict(r) for r in cur.fetchall()]

        return {
            "items": items,
            "total": total_filtered,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(items)) < total_filtered,
            "counts": counts,
        }

    def create(
        self,
        vendor_id: Optional[str],
        invoice_no_raw: Optional[str],
        invoice_no_norm: Optional[str],
        invoice_date: Optional[str],
        total: Optional[float],
        currency: Optional[str],
        po_id: Optional[str],
        match_method: Optional[str],
        status: str,
        decision_json: str,
        file_hash: Optional[str] = None,
        file_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO invoices
               (vendor_id, invoice_no_raw, invoice_no_norm, invoice_date, total, currency,
                po_id, match_method, status, decision_json, file_hash, file_name, file_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vendor_id,
                invoice_no_raw,
                invoice_no_norm,
                invoice_date,
                total,
                currency,
                po_id,
                match_method,
                status,
                decision_json,
                file_hash,
                file_name,
                file_path,
            ),
        )
        return cur.lastrowid

    def update_invoice(
        self,
        invoice_id: int,
        status: str,
        decision_json: str,
        po_id: Optional[str] = None,
        match_method: Optional[str] = None,
        file_name: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """UPDATE invoices 
               SET status = ?, decision_json = ?, po_id = COALESCE(?, po_id), match_method = COALESCE(?, match_method),
                   file_name = COALESCE(?, file_name), file_path = COALESCE(?, file_path)
               WHERE invoice_id = ?""",
            (status, decision_json, po_id, match_method, file_name, file_path, invoice_id),
        )

    def add_line(
        self,
        invoice_id: int,
        po_item_row_id: Optional[int],
        description: str,
        quantity: Optional[float],
        unit_price: Optional[float],
        line_total: Optional[float],
    ) -> None:
        self.conn.execute(
            """INSERT INTO invoice_lines
               (invoice_id, po_item_row_id, description, quantity, unit_price, line_total)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (invoice_id, po_item_row_id, description, quantity, unit_price, line_total),
        )

    def get_lines(self, invoice_id: int) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
        return [dict(r) for r in cur.fetchall()]

    def delete_lines(self, invoice_id: int) -> None:
        self.conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))

    def get_po_consumed_amount(
        self, po_id: str, include_pending: bool = True, exclude_invoice_id: Optional[int] = None
    ) -> float:
        if include_pending:
            query = """SELECT COALESCE(SUM(total), 0.0) as billed
                       FROM invoices
                       WHERE po_id = ? AND status IN ('APPROVED', 'PENDING_REVIEW')"""
        else:
            query = """SELECT COALESCE(SUM(total), 0.0) as billed
                       FROM invoices
                       WHERE po_id = ? AND status = 'APPROVED'"""
        params = [po_id]
        if exclude_invoice_id:
            query += " AND invoice_id != ?"
            params.append(exclude_invoice_id)
        cur = self.conn.execute(query, params)
        row = cur.fetchone()
        return float(row["billed"]) if row else 0.0


class AuditRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def log(
        self,
        invoice_id: Optional[int],
        stage: str,
        status: str,
        detail_json: str,
        duration_ms: int,
    ) -> None:
        self.conn.execute(
            """INSERT INTO audit_log (invoice_id, stage, status, detail_json, duration_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (invoice_id, stage, status, detail_json, duration_ms),
        )
