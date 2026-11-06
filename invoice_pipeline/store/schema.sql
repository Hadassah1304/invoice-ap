CREATE TABLE IF NOT EXISTS vendors (
  vendor_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  aliases TEXT,                       -- JSON list
  gstin TEXT UNIQUE,
  email_domain TEXT,
  approved INTEGER NOT NULL DEFAULT 1,
  bank_account TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
  po_id TEXT PRIMARY KEY,
  vendor_id TEXT NOT NULL REFERENCES vendors(vendor_id),
  po_date DATE NOT NULL,
  currency TEXT NOT NULL DEFAULT 'INR',
  total NUMERIC NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN','PARTIAL','CLOSED','CANCELLED')),
  payment_terms_days INTEGER
);
CREATE INDEX IF NOT EXISTS idx_po_vendor ON purchase_orders(vendor_id, status);

CREATE TABLE IF NOT EXISTS po_items (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT,
  po_id TEXT NOT NULL REFERENCES purchase_orders(po_id),
  item_name TEXT NOT NULL,
  description TEXT,
  embedding BLOB,                     -- float32, computed once when the PO line is created
  qty_ordered NUMERIC NOT NULL,
  qty_remaining NUMERIC NOT NULL,
  unit_price NUMERIC NOT NULL,
  uom TEXT,
  tax_rate NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_items_po ON po_items(po_id);
CREATE INDEX IF NOT EXISTS idx_items_po_qty ON po_items(po_id, qty_remaining);

CREATE TABLE IF NOT EXISTS invoices (
  invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id TEXT,
  invoice_no_raw TEXT,
  invoice_no_norm TEXT,
  invoice_date DATE,
  total NUMERIC,
  currency TEXT,
  po_id TEXT,
  match_method TEXT,                  -- EXPLICIT | INFERRED_VENDOR | INFERRED_ITEMS | MANUAL
  status TEXT NOT NULL CHECK (status IN ('APPROVED','PENDING_REVIEW','REJECTED')),
  decision_json TEXT,                 -- full output stored for replay in the UI
  file_hash TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Partial unique index excluding rejected and null/empty invoice numbers
CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_invno
  ON invoices(vendor_id, invoice_no_norm) 
  WHERE status != 'REJECTED' AND invoice_no_norm IS NOT NULL AND invoice_no_norm != '';

CREATE INDEX IF NOT EXISTS idx_invoices_po ON invoices(po_id);
CREATE INDEX IF NOT EXISTS idx_invoices_vendor_date ON invoices(vendor_id, invoice_date);

CREATE TABLE IF NOT EXISTS invoice_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER REFERENCES invoices(invoice_id),
  po_item_row_id INTEGER REFERENCES po_items(row_id),
  description TEXT,
  quantity NUMERIC,
  unit_price NUMERIC,
  line_total NUMERIC
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER,
  stage TEXT,
  status TEXT,
  detail_json TEXT,
  duration_ms INTEGER,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
