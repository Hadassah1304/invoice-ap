# Build Prompt: Invoice-to-Decision Pipeline (AP Automation)

You are a senior Python engineer. Build a complete, modular, well-tested system that takes a vendor invoice (PDF or image) and produces a **clear, reasoned decision** (`APPROVED`, `REJECTED`, `NEEDS_REVIEW`) with **every intermediate step visible**.

Read this whole document before writing code. Build in the order given in section 17. After each phase, run the tests for that phase before moving on.

---

## 1. Problem statement (verbatim, this is the north star)

> A mid-size company receives hundreds of vendor invoices every month, all by email, all as PDFs. Someone on the AP team opens each one, finds the matching purchase order in a spreadsheet, checks whether the numbers line up, and decides what to do with it.
>
> The invoices are messy: different formats, scanned images, itemised or bundled lines, tax embedded or separate, PO references explicit or implied, and sometimes critical information is missing.
>
> On the other side is a procurement system with approved vendors, PO amounts, tolerance thresholds and duplicate detection rules. Matching an invoice to a PO isn't always obvious: a vendor might split one PO into multiple invoices, amounts might be close but not exact. The process has to make a decision and be able to explain it.
>
> Build a process that takes an invoice as input and produces a clear, reasoned decision as output, with everything that happened in between visible. You decide what to extract, how to validate, what rules matter, and what the output looks like.
>
> Design and build 2-4 edge cases of your own. They must be realistic, non-trivial scenarios where the process behaves differently from the happy path.

Glossary: **PO** = Purchase Order, the company's promise to buy specific items at specific prices, issued before the vendor delivers. An invoice must be checked against its PO before payment. A PO has one or more **lines** (item, quantity, unit price).

---

## 2. Hard requirements

1. **Pipeline and server are isolated.** The pipeline is a pure Python package with no FastAPI dependency. It runs three ways: as a CLI, as a Python import, and imported by the FastAPI server. The server only imports and calls the pipeline.
2. **Everything configurable from one `config.yaml`**: OCR engine, LLM model, thresholds, weights, tolerances, feature flags, paths. No magic numbers in code.
3. **Modular, swappable components** behind small interfaces (OCR engines, LLM client, embedder, matchers, rules).
4. **Deterministic decisions.** The LLM is used only for extraction (text to JSON) and optionally for phrasing the explanation. All approve/reject/review decisions come from deterministic, auditable rules.
5. **Full trace.** Every stage records name, status, inputs summary, outputs summary, duration, and warnings. The trace is part of the output and is rendered in the UI.
6. **Never guess.** Missing values are `null`. Ambiguity leads to `NEEDS_REVIEW` with ranked candidates, not a silent pick. Inferred PO matches never auto-approve unless config explicitly allows it.
7. **Runs on a small container** (assume 1-2 GB RAM, CPU only). Heavy models are lazy-loaded and optional.
8. Python 3.11+, type hints everywhere, Pydantic v2 models for all data contracts.

---

## 3. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| API | FastAPI + Uvicorn |
| Data models | Pydantic v2 |
| Config | `config.yaml` loaded into a Pydantic settings model (PyYAML). Environment variable overrides allowed, e.g. `INVOICE_LLM__API_KEY` |
| LLM | Google Gemini via the `google-genai` SDK. Default model name from config (target a Gemini 3 Flash class model, e.g. `gemini-3-flash-preview`; verify the exact current model id and keep it configurable). Use structured JSON output (`response_mime_type="application/json"` plus a response schema) |
| PDF text layer | PyMuPDF (`fitz`), fallback `pdfplumber` |
| OCR | **Two engines, switchable by config**: `tesseract` (pytesseract) and `rapidocr` (rapidocr-onnxruntime). Plus `vision_llm` fallback via Gemini with the image |
| Image preprocessing | OpenCV / Pillow (deskew, grayscale, denoise, upscale) |
| Fuzzy matching | rapidfuzz |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (configurable), with a TF-IDF char n-gram fallback that needs no model. Embedder is behind an interface |
| DB | SQLite (stdlib `sqlite3` or SQLAlchemy Core). Embeddings stored as float32 BLOBs, loaded to a numpy matrix in memory |
| CLI | Typer |
| Frontend | Plain HTML + CSS + vanilla JS (no build step), served by FastAPI as static files |
| Tests | pytest |
| Synthetic data | Faker (en_IN), reportlab or WeasyPrint for PDFs, Pillow/OpenCV for scan degradation |
| Packaging | `pyproject.toml`, Dockerfile (multi-stage, slim), `.env.example` |

---

## 4. Repository layout

```
invoice-ap/
├── config.yaml
├── .env.example
├── pyproject.toml
├── Dockerfile
├── README.md
├── invoice_pipeline/                 # ISOLATED PACKAGE, no FastAPI imports
│   ├── __init__.py                   # exports: process_invoice, load_config
│   ├── config.py                     # Pydantic settings + YAML loader
│   ├── models.py                     # all Pydantic models (Invoice, Decision, Trace, ...)
│   ├── pipeline.py                   # orchestrator: process_invoice(...)
│   ├── trace.py                      # TraceRecorder (stage timing, warnings)
│   ├── ingest/
│   │   ├── loader.py                 # read file, hash, detect type, page count
│   │   ├── text_layer.py             # PyMuPDF/pdfplumber text extraction + quality check
│   │   ├── preprocess.py             # image cleanup
│   │   └── ocr/
│   │       ├── base.py               # OCREngine interface
│   │       ├── tesseract_engine.py
│   │       ├── rapidocr_engine.py
│   │       └── router.py             # text layer -> OCR -> vision fallback logic
│   ├── extract/
│   │   ├── llm_client.py             # Gemini wrapper (retries, timeout, JSON schema)
│   │   ├── prompts.py                # extraction prompt + explanation prompt
│   │   ├── schema.py                 # extraction JSON schema
│   │   ├── extractor.py              # text (or image) -> ExtractedInvoice
│   │   └── grounding.py              # verify values appear in raw text
│   ├── normalize/
│   │   ├── normalizers.py            # invoice no, vendor name, amounts, dates, currency
│   │   └── numbers.py                # Indian/EU number formats, date ambiguity handling
│   ├── store/
│   │   ├── db.py                     # connection, migrations, transactions
│   │   ├── schema.sql
│   │   ├── repositories.py           # VendorRepo, PORepo, ItemRepo, InvoiceRepo, AuditRepo
│   │   └── embeddings.py             # Embedder interface, MiniLM, TF-IDF; in-memory index
│   ├── matching/
│   │   ├── vendor_resolver.py        # GSTIN -> fuzzy name -> email domain
│   │   ├── duplicates.py             # exact + near duplicate detection
│   │   ├── tier1_explicit.py
│   │   ├── tier2_vendor.py
│   │   ├── tier3_items.py            # per-line semantic search + set intersection
│   │   ├── item_matcher.py           # exact -> lexical -> embedding per line
│   │   ├── scoring.py                # candidate scoring (weights from config)
│   │   └── router.py                 # chooses tier, returns MatchResult
│   ├── validation/
│   │   ├── rules.py                  # each rule = small function returning RuleResult
│   │   ├── balance.py                # PO remaining balance and quantity
│   │   └── engine.py                 # runs rules, aggregates
│   ├── decision/
│   │   ├── aggregator.py             # RuleResults + match method -> final decision
│   │   └── explainer.py              # template-based reasoning, optional LLM polish
│   ├── cli.py                        # Typer app
│   └── utils/ (logging.py, hashing.py)
├── server/                           # THIN layer, imports invoice_pipeline
│   ├── main.py                       # FastAPI app factory
│   ├── routes/ (invoices.py, pos.py, vendors.py, review.py, health.py)
│   ├── deps.py                       # config + DB dependency injection
│   └── static/ (index.html, style.css, app.js)
├── data_gen/                         # synthetic data generator (own CLI)
│   ├── generate.py
│   ├── catalog.py                    # items incl. near-twins
│   ├── templates/                    # 3-4 invoice HTML layouts
│   ├── mutations.py                  # edge-case mutations
│   └── degrade.py                    # scan degradation
├── benchmarks/
│   ├── bench_ocr.py                  # text layer vs tesseract vs rapidocr vs vision LLM
│   ├── bench_matching.py             # index vs brute force at 1k/10k/100k lines
│   └── results/ (CSV + charts)
├── samples/                          # generated PDFs, manifest.csv
└── tests/
    ├── unit/
    ├── integration/                  # runs manifest end to end
    └── conftest.py
```

---

## 5. `config.yaml` (create this file with these keys and defaults)

```yaml
app:
  db_path: ./data/ap.db
  upload_dir: ./data/uploads
  log_level: INFO
  cache_by_file_hash: true

ocr:
  engine: rapidocr                # tesseract | rapidocr
  text_layer:
    enabled: true
    min_chars: 80                 # below this the text layer is considered absent
    min_alnum_ratio: 0.5          # garbage-text detection
  preprocess:
    enabled: true
    deskew: true
    denoise: true
    upscale_dpi: 300
  pdf_render_dpi: 200
  tesseract:
    lang: eng
    psm: 6
    cmd: tesseract
  rapidocr:
    use_angle_cls: true
  min_confidence: 0.70            # mean OCR confidence below this triggers fallback
  vision_fallback:
    enabled: true                 # send page image to Gemini when OCR is weak or key fields missing
    trigger_on_missing_fields: [invoice_number, invoice_date, grand_total]

llm:
  provider: gemini
  api_key_env: GEMINI_API_KEY
  model: gemini-3-flash-preview   # verify exact id; keep configurable
  temperature: 0.0
  timeout_s: 45
  max_retries: 2
  extraction:
    input_mode: text              # text | image | auto (auto = text unless OCR is weak)
    require_source_snippets: false
  explanation:
    use_llm_polish: false         # templates by default; LLM only rephrases, never decides

grounding:
  enabled: true
  numeric_tolerance: 0.01
  on_failure: flag                # flag | null_out | review

normalization:
  default_currency: INR
  date_formats_priority: ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"]   # DD/MM first (India)
  ambiguous_date_policy: flag     # flag | first_priority

vendor:
  match_threshold: 0.90
  reject_threshold: 0.75
  use_gstin_first: true
  use_email_domain: true

duplicates:
  near_dup_window_days: 7
  near_dup_amount_tolerance_pct: 0.0
  invoice_no_similarity_threshold: 0.92

matching:
  tier2:
    min_score: 0.80
    min_margin: 0.15
    top_k: 5
  tier3:
    item_similarity_threshold: 0.88    # calibrate; do NOT assume 0.95 works
    item_margin: 0.03
    top_k_per_line: 10
    price_tolerance_pct: 5
    use_lexical_check: true            # numbers/units/key tokens must agree
    min_line_coverage_for_partial: 0.6
    top_k_candidates_to_user: 5
  line_match:
    exact_first: true
    fuzzy_threshold: 90                # rapidfuzz token_set_ratio
    use_embeddings: true
  weights:                             # must sum to 1.0
    price: 0.30
    quantity: 0.25
    total_coverage: 0.20
    line_coverage: 0.15
    date: 0.10
  auto_approve_inferred: false         # inferred PO matches always go to review unless true

embeddings:
  backend: minilm                      # minilm | tfidf
  model_name: sentence-transformers/all-MiniLM-L6-v2
  cache_description_embeddings: true

validation:
  rounding_tolerance: 1.00             # absolute currency units for arithmetic
  tolerance_auto_pct: 2.0              # up to this overage: APPROVED with note
  tolerance_review_pct: 5.0            # up to this: NEEDS_REVIEW; above: REJECTED
  price_variance_line_pct: 2.0
  qty_over_remaining_policy: review    # review | reject
  reserve_pending_invoices: true       # pending invoices count against PO balance
  max_invoice_age_days: 90
  allow_future_dated: false
  tax_rates_plausible: [0, 5, 12, 18, 28]
  allow_extra_lines: [freight, handling, shipping]   # keyword list for non-PO lines
  block_negative_amounts: true         # credit notes are a different document type

decision:
  review_if_inferred: true
  review_on_low_confidence_below: 0.75 # any critical extracted field below this -> review

server:
  host: 0.0.0.0
  port: 8000
  max_upload_mb: 15
  cors_origins: ["*"]
```

Rules for config: load once, validate with Pydantic (fail fast with a clear message on invalid values, e.g. weights not summing to 1), pass the config object down explicitly (no globals), and allow `--config path` on the CLI and `INVOICE_CONFIG` env var on the server.

---

## 6. Database schema (SQLite, `store/schema.sql`)

```sql
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

-- One row per item per PO (qty, price and remaining qty are per PO)
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

-- Ledger: needed for duplicate detection and PO balance tracking
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
  status TEXT NOT NULL,               -- APPROVED | PENDING_REVIEW | REJECTED
  decision_json TEXT,                 -- full output stored for replay in the UI
  file_hash TEXT UNIQUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_invno
  ON invoices(vendor_id, invoice_no_norm) WHERE status != 'REJECTED';

-- Invoice lines billed against PO lines (needed for per-line remaining qty)
CREATE TABLE IF NOT EXISTS invoice_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER REFERENCES invoices(invoice_id),
  po_item_row_id INTEGER REFERENCES po_items(row_id),
  description TEXT, quantity NUMERIC, unit_price NUMERIC, line_total NUMERIC
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER,
  stage TEXT, status TEXT, detail_json TEXT, duration_ms INTEGER,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Balance formula: `remaining = po.total - SUM(invoices.total WHERE po_id = X AND status IN ('APPROVED','PENDING_REVIEW'))` (pending included only if `reserve_pending_invoices` is true). Line-level remaining quantity (`po_items.qty_remaining`) is decremented in the **same DB transaction** that records the invoice. If a reviewer rejects a pending invoice, release its reservation (restore quantities, status REJECTED). Use `BEGIN IMMEDIATE` transactions so two concurrent invoices cannot both consume the same remaining balance.

---

## 7. Data contracts

### 7.1 Extraction output (`ExtractedInvoice`, produced by the LLM step)

```json
{
  "source": {"file_name": "inv_001.pdf", "file_hash": "sha256...", "extraction_method": "text_layer|ocr_tesseract|ocr_rapidocr|vision_llm", "ocr_confidence": 0.91, "page_count": 1},
  "vendor": {"name": "Sri Balaji Foods Pvt Ltd", "gstin": "36ABCDE1234F1Z5", "email": "billing@balajifoods.in", "phone": null, "address": null, "bank_account": null, "confidence": 0.93},
  "invoice_number": {"value": "INV/2026/0381", "confidence": 0.98},
  "invoice_date": {"value": "2026-10-28", "confidence": 0.97, "ambiguous": false},
  "due_date": {"value": null, "confidence": 0.0},
  "po_reference": {"value": "PO-2026-0042", "confidence": 0.9},
  "currency": {"value": "INR", "confidence": 0.99},
  "line_items": [
    {"line_no": 1, "description": "Veg Burger 150g", "quantity": 10, "uom": "pcs", "unit_price": 100.0, "line_total": 1000.0, "tax_rate": 5.0, "confidence": 0.95}
  ],
  "subtotal": {"value": 1750.0, "confidence": 0.96},
  "tax_total": {"value": 87.5, "confidence": 0.90},
  "grand_total": {"value": 1837.5, "confidence": 0.97},
  "document_type": "invoice|credit_note|other",
  "raw_text": "...",
  "missing_fields": ["due_date"],
  "grounding": {"checked": 14, "failed": []}
}
```

Prompt rules for the extraction LLM (put in `prompts.py`):
- Return **only** JSON matching the schema; use `null` for anything not explicitly present. Never infer, never invent.
- `po_reference` must be a literal string from the document. Phrases like "as per our discussion" mean `null`.
- Give each field a confidence 0-1 reflecting how clearly it was present.
- Do not do arithmetic to fill missing totals. Report what is printed.
- Report `document_type` (detect credit notes / debit notes / proforma).
- Flag `ambiguous: true` on dates like `03/04/2026`.
- Preserve numbers as printed, then parse (handle `1,00,000.00`, `1.000,00`, `Rs.`, `₹`).

### 7.2 Pipeline output (`DecisionResult`)

```json
{
  "request_id": "uuid",
  "decision": "NEEDS_REVIEW",
  "reason_code": "AMBIGUOUS_PO",
  "confidence": 0.62,
  "summary": "Two open POs fit this invoice equally well...",
  "reasoning": ["Vendor resolved via GSTIN (exact).", "No PO reference on the invoice.", "..."],
  "extracted": { "...ExtractedInvoice without raw_text..." },
  "match": {
    "tier": 2,
    "method": "INFERRED_VENDOR",
    "selected_po": null,
    "candidates": [
      {"po_id": "PO-2026-0042", "score": 0.84, "signals": {"price": 1.0, "quantity": 0.9, "total_coverage": 0.6, "line_coverage": 1.0, "date": 0.8}, "notes": ["All unit prices match", "Invoice is 28% of PO total"]},
      {"po_id": "PO-2026-0051", "score": 0.82, "signals": {}, "notes": []}
    ],
    "unmatched_lines": []
  },
  "po_balance": {"po_id": "PO-2026-0042", "po_total": 6200.0, "previously_billed": 0.0, "reserved_pending": 0.0, "this_invoice": 1837.5, "remaining_after": 4362.5, "variance_pct": 0.0},
  "checks": [
    {"rule": "arithmetic", "status": "PASS|WARN|FLAG|FAIL|SKIPPED", "severity": "info|soft|hard", "message": "...", "data": {}}
  ],
  "review": {"required": true, "actions": [{"type": "select_po", "options": ["PO-2026-0042", "PO-2026-0051"]}, {"type": "edit_field", "field": "vendor"}]},
  "trace": [
    {"stage": "ingest", "status": "ok", "duration_ms": 12, "summary": "text layer, 1 page", "warnings": []}
  ],
  "timings_ms": {"total": 1840, "ocr": 0, "llm": 1420, "matching": 35, "validation": 8},
  "cost": {"llm_input_tokens": 1800, "llm_output_tokens": 600},
  "cached": false
}
```

Decision enum: `APPROVED`, `REJECTED`, `NEEDS_REVIEW`. `APPROVED` may carry `reason_code: APPROVED_WITH_NOTE`. Reason codes (enum, no free strings): `OK`, `APPROVED_WITH_NOTE`, `MISSING_FIELDS`, `LOW_CONFIDENCE_EXTRACTION`, `GROUNDING_FAILED`, `ARITHMETIC_MISMATCH`, `DUPLICATE_EXACT`, `DUPLICATE_POSSIBLE`, `VENDOR_NOT_APPROVED`, `VENDOR_UNCLEAR`, `VENDOR_MISMATCH`, `INVALID_PO_REF`, `PO_CLOSED`, `NO_MATCHING_PO`, `AMBIGUOUS_PO`, `INFERRED_MATCH`, `OVERBILLED`, `QTY_EXCEEDS_REMAINING`, `PRICE_DRIFT`, `CURRENCY_MISMATCH`, `DATE_INVALID`, `TAX_MISMATCH`, `UNSUPPORTED_DOCUMENT_TYPE`, `UNREADABLE_DOCUMENT`.

### 7.3 Override input (human review resolution)

`process_invoice(..., overrides={"po_id": "PO-2026-0042", "vendor_id": "V007", "fields": {"grand_total": 1837.5}})`. Overrides are applied at the correct stage, recorded in the trace as `manual_override`, and the match method becomes `MANUAL`.

---

## 8. Pipeline stages (implement in `pipeline.py`, each stage is its own module/function)

Every stage: takes typed input, returns typed output, records itself into `TraceRecorder`, never raises on bad documents (it returns a failure state that routes to `NEEDS_REVIEW` with a reason). Real exceptions (bugs, DB down) are logged and surfaced as a 500 from the API / non-zero exit from the CLI.

1. **Cache check**: sha256 of file bytes. If seen and `cache_by_file_hash`, return the stored decision with `cached: true`.
2. **Ingest and text extraction** (`ocr/router.py`):
   - PDF: try text layer (PyMuPDF). Accept if `len(text) >= min_chars` and alnum ratio ok.
   - Otherwise render pages at `pdf_render_dpi`, preprocess (grayscale, deskew, denoise), run the configured OCR engine (`tesseract` or `rapidocr`).
   - Image input: go directly to preprocess + OCR.
   - If mean OCR confidence < `min_confidence` and `vision_fallback.enabled`: mark `needs_vision` and send page images to Gemini in the extraction step.
   - Multi-page: concatenate pages with `--- PAGE n ---` markers; totals usually appear on the last page.
   - Record method, per-page confidence, duration.
3. **LLM extraction** (`extractor.py`): text mode, image mode or auto per config. Validate the response against the Pydantic schema; on parse failure retry (max `max_retries`) then return `UNREADABLE_DOCUMENT`.
4. **Vision fallback on missing key fields**: if after text-mode extraction any of `trigger_on_missing_fields` are null and vision fallback is enabled and not yet used, re-extract from the image and merge (vision fills only the nulls; where both have a value and they disagree, flag it).
5. **Grounding check** (`grounding.py`): every extracted number, invoice number, PO ref, GSTIN and date must be findable in `raw_text` (normalize separators/commas before comparing). Failures are recorded and handled per `grounding.on_failure`. This guards against LLM digit hallucination.
6. **Completeness gate**: required = invoice number, invoice date, grand total, at least one line item (vendor name OR GSTIN). If missing, `NEEDS_REVIEW / MISSING_FIELDS` listing exactly which fields. Also gate on `document_type != invoice` (`UNSUPPORTED_DOCUMENT_TYPE`) and negative totals.
7. **Normalize**: invoice number (uppercase, strip spaces/dashes/slashes/leading zeros for comparison key only; keep the raw value for display), vendor name (lowercase, strip `pvt|private|ltd|limited|llp|inc`, punctuation), amounts to Decimal, dates to ISO (ambiguous dates handled per config), currency symbols to ISO codes.
8. **Duplicate detection** (`duplicates.py`): (a) exact: same vendor + normalized invoice number in ledger, `REJECTED / DUPLICATE_EXACT`; (b) near: same vendor + same total within tolerance + date within window, or invoice number similarity above threshold, `NEEDS_REVIEW / DUPLICATE_POSSIBLE` with the matching ledger entry shown. Different vendor with the same invoice number is **not** a duplicate. Note: a legitimate split (same PO, different invoice number, different or same amount) must not be rejected, only flagged for review when amount and date both match.
9. **Vendor resolution** (`vendor_resolver.py`): GSTIN exact, then fuzzy name against name + aliases (rapidfuzz), then email domain. Output `vendor_id`, confidence and method. Unapproved vendor gives `REJECTED / VENDOR_NOT_APPROVED`. Score between reject and match thresholds gives `NEEDS_REVIEW / VENDOR_UNCLEAR` with closest matches. Also compare the extracted bank account to the vendor's stored one and add a soft `FLAG` on mismatch (fraud signal).
10. **PO matching** (`matching/router.py`), choose the tier by the strongest identifier:
    - **Tier 1: PO number present.** Normalize, look up directly. Not found: `NEEDS_REVIEW / INVALID_PO_REF`, include near-match suggestions by edit distance but **never silently pick one**. PO vendor differs from resolved invoice vendor: `REJECTED / VENDOR_MISMATCH`. PO CLOSED/CANCELLED or remaining balance <= 0: `REJECTED / PO_CLOSED`. Otherwise selected, `method=EXPLICIT`. If the invoice has no vendor info, take the vendor from the PO.
    - **Tier 2: no PO number, vendor resolved.** Candidate pool = this vendor's OPEN/PARTIAL POs. Hard filters (eliminate, don't score): PO date <= invoice date, same currency, at least one line with `qty_remaining > 0`. No candidates: `REJECTED / NO_MATCHING_PO`. Score each candidate (section 9). Select if `top >= min_score` and `top - second >= min_margin` (`method=INFERRED_VENDOR`), else `NEEDS_REVIEW / AMBIGUOUS_PO` with top-k and per-signal scores.
    - **Tier 3: no PO number, no vendor.** Per invoice line: embed the description, search `po_items` (in-memory matrix) for rows with similarity >= `item_similarity_threshold`, margin check vs the next-best distinct item, lexical agreement check (numbers, units, key tokens like chicken vs veg), and numeric pre-filters (`qty_remaining >= invoice qty`, price within `price_tolerance_pct`, PO open). Produce a **set of po_ids per line**. Intersect all sets. Size 1: select (`INFERRED_ITEMS`). Size > 1: rank by section 9 scoring, `NEEDS_REVIEW` with top-k. Size 0: coverage ranking (count of invoice lines matched per PO, require >= `min_line_coverage_for_partial`), `NEEDS_REVIEW / NO_MATCHING_PO` or `AMBIGUOUS_PO` with the unmatched lines highlighted. Tier 3 results are **always** `NEEDS_REVIEW` unless `auto_approve_inferred: true`.
    - Once Tier 3 resolves a PO, backfill the vendor from that PO and note it in the trace.
11. **Common validation** (`validation/engine.py`), run after a PO is selected (see section 10 for the rule list).
12. **Aggregate and decide** (`decision/aggregator.py`), section 11.
13. **Explain** (`decision/explainer.py`): build `summary` and `reasoning[]` from templates using the check results (each reasoning line cites the data behind it). If `use_llm_polish`, pass the already-decided structured result to Gemini only to rephrase; it cannot change the decision, and the output is discarded if it mentions facts not in the structure.
14. **Persist**: in one transaction write the invoice to the ledger (status `APPROVED` or `PENDING_REVIEW` or `REJECTED`), the invoice lines, decrement `qty_remaining` for approved and (if configured) pending, write audit rows. Rejected invoices do not consume balance. `dry_run=True` skips persistence.

---

## 9. Candidate scoring (`matching/scoring.py`)

Score in [0,1] per candidate PO as a weighted sum (weights from config). Each signal is returned separately for the UI.

- **price**: fraction of matched invoice lines whose unit price is within `price_variance_line_pct` of the PO line price (partial credit for near).
- **quantity**: fraction of matched lines where invoiced qty <= PO line `qty_remaining`.
- **total_coverage**: how well the invoice total fits the PO remaining balance. Exact equal to remaining = 1.0; invoice below remaining scores by ratio but never above 0.8 unless it is within tolerance of the remaining balance; invoice above remaining scores low.
- **line_coverage**: matched invoice lines / total invoice lines.
- **date**: 1.0 if invoice date is within `payment_terms_days + 30` of the PO date, decaying beyond; 0 if before the PO date.

Line matching inside a PO (`item_matcher.py`): exact normalized name, then rapidfuzz `token_set_ratio >= fuzzy_threshold`, then embedding cosine (only if enabled and still unmatched). Require lexical agreement on numbers/units (500ml must not match 1L). Each match records its method and score so the UI can show it. Embeddings are never trusted alone; "Veg Burger" vs "Chicken Burger" can score above 0.9.

Decision from scores uses **score and margin**, never score alone.

---

## 10. Validation rules (`validation/rules.py`)

Each rule is a small pure function `(context) -> RuleResult(rule, status, severity, message, data)`. Register rules in a list so they can be enabled/disabled in config. Rules:

1. `arithmetic`: sum of line totals ≈ subtotal; subtotal + tax ≈ grand total (within `rounding_tolerance`). Fail gives `FLAG / ARITHMETIC_MISMATCH` (could be extraction error, route to review).
2. `line_price_variance`: per line, unit price vs PO price. **Hidden price drift:** even when the grand total is within tolerance, if any line deviates beyond `price_variance_line_pct` (e.g. price up, quantity down, total unchanged) emit `FLAG / PRICE_DRIFT` with the offending lines.
3. `line_quantity`: invoiced qty vs `qty_remaining` per PO line. Over: `qty_over_remaining_policy`.
4. `extra_or_missing_lines`: invoice lines not on the PO (allowed if description matches `allow_extra_lines` such as freight, else FLAG); PO lines absent on the invoice are fine (partial delivery), recorded as info.
5. `balance_tolerance`: `remaining = PO total - approved - (reserved pending)`. `variance_pct = (invoice_total - remaining)/remaining*100`. <= 0: PASS; 0 to `tolerance_auto_pct`: WARN; up to `tolerance_review_pct`: FLAG; above: FAIL `OVERBILLED`. If the invoice exactly equals the remaining balance, note "closes the PO" and set PO status CLOSED on approval; partial sets PARTIAL.
6. `currency_match`: invoice currency equals PO currency, else FAIL.
7. `date_sanity`: not future-dated (unless allowed), not older than `max_invoice_age_days`, not before PO date.
8. `tax_check`: tax rate in `tax_rates_plausible`; effective rate vs PO line `tax_rate` mismatch gives FLAG; detect when tax appears embedded in unit prices (price*qty summed equals grand total with zero tax listed) and note it.
9. `uom_check`: unit-of-measure mismatch (box vs pcs) gives FLAG with the data.
10. `confidence_check`: any critical field (invoice number, date, total, PO ref) below `review_on_low_confidence_below` gives FLAG `LOW_CONFIDENCE_EXTRACTION`.
11. `vendor_bank_check`: bank account differs from stored gives FLAG (soft, fraud signal).

---

## 11. Decision aggregation (`decision/aggregator.py`)

Precedence (first match wins, document the order in the README):
1. Any early-gate terminal (duplicate exact, vendor not approved, vendor mismatch, PO closed, no PO, unsupported doc) gives `REJECTED` with that reason code.
2. Any rule with `FAIL` gives `REJECTED`.
3. Any early-gate review terminal (missing fields, possible duplicate, vendor unclear, invalid PO ref, ambiguous PO, unreadable, grounding failed) gives `NEEDS_REVIEW`.
4. Any `FLAG`, or `match.method != EXPLICIT` (and not `auto_approve_inferred`), gives `NEEDS_REVIEW`.
5. Any `WARN` gives `APPROVED` with `reason_code=APPROVED_WITH_NOTE`.
6. Otherwise `APPROVED / OK`.

`confidence` (0-1) is a transparent function: min of critical field confidences, times match confidence (1.0 for explicit, top score for inferred), minus small penalties for each WARN/FLAG. Show the formula in the explanation. It is a heuristic, not a probability; say so in the README.

Early exits still run steps 13-14 (explain + persist) so every outcome has a trace, explanation and ledger entry.

---

## 12. CLI (`invoice_pipeline/cli.py`, Typer; entry point `invoice-ap`)

```
invoice-ap init-db [--config config.yaml] [--seed samples/seed.json]
invoice-ap process <file> [--config ...] [--ocr tesseract|rapidocr] [--dry-run]
                          [--override po_id=PO-1] [--json] [--trace] [--out result.json]
invoice-ap batch <dir> [--manifest samples/manifest.csv] [--report report.csv]
invoice-ap ocr <file> [--engine tesseract|rapidocr|vision_llm|text_layer]   # OCR only
invoice-ap extract <file>                                                   # OCR + LLM only
invoice-ap resolve <invoice_id> --po PO-1                                   # apply reviewer decision
invoice-ap seed-demo                                                        # load demo vendors/POs
invoice-ap bench ocr|matching
invoice-ap serve                                                            # starts the FastAPI server
```

Default output is a human-readable report (decision banner, reasoning, check table, candidate table, timings); `--json` prints `DecisionResult` only. `batch` with a manifest prints a pass/fail table of expected vs actual decisions and PO (this is the evaluation harness).

Python usage must also work:

```python
from invoice_pipeline import process_invoice, load_config
cfg = load_config("config.yaml")
result = process_invoice("samples/inv_001.pdf", config=cfg, overrides=None, dry_run=False)
```

---

## 13. FastAPI server (`server/`)

The server **only** imports `invoice_pipeline`. No business logic in routes. Load config and DB once at startup (lifespan), inject via dependencies. CPU-bound work (`process_invoice`) runs in a thread pool (`run_in_threadpool`). Return Pydantic models.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/invoices/process` | multipart upload; query `dry_run`, `ocr_engine` (optional override); returns `DecisionResult` |
| GET | `/api/invoices` | list ledger (filters: status, vendor, po) |
| GET | `/api/invoices/{id}` | stored `DecisionResult` for replay |
| POST | `/api/invoices/{id}/resolve` | reviewer action: `{action: approve\|reject\|select_po\|edit_fields, po_id?, fields?, note}`; re-runs the pipeline from the right stage with overrides |
| GET | `/api/pos` / `/api/pos/{po_id}` | PO with lines and billed/remaining and linked invoices |
| GET | `/api/vendors` | vendors |
| POST | `/api/demo/seed` | load demo data (only if `demo_mode`) |
| POST | `/api/demo/reset` | wipe and reseed |
| GET | `/api/config` | effective config with secrets redacted (read-only) |
| GET | `/api/health` | liveness, DB ok, OCR engines available, LLM key present |

Enforce `max_upload_mb`, allowed types (pdf, png, jpg, jpeg, tiff), sanitize file names, store uploads under `upload_dir`. Return consistent error JSON `{error, detail}`. Mount `server/static` at `/`.

---

## 14. Frontend (plain HTML + CSS + JS, single page, no build step)

Goal: a clean, simple reviewer console that makes every decision and its reasoning obvious. Responsive, light theme, readable at a glance. No framework; use `fetch`, small helper functions, and template literals. Escape all rendered text (no `innerHTML` with raw data).

**Layout (three areas):**
1. **Upload panel** (top/left): drag-and-drop or file picker, OCR engine dropdown (Auto / Tesseract / RapidOCR), "dry run" toggle, **Process** button, spinner with stage-by-stage progress text.
2. **Result panel** (main):
   - **Decision banner**: large color-coded badge (green `APPROVED`, amber `NEEDS_REVIEW`, red `REJECTED`), reason code, one-line summary, and a **confidence meter** (bar + number, with a tooltip explaining it is heuristic).
   - **Reasoning**: numbered plain-language bullets (from `reasoning[]`).
   - **Extracted fields table**: field, value, confidence bar, grounded ✓/✗; low-confidence or ungrounded fields highlighted; line items table below.
   - **Checks table**: rule, status chip (PASS/WARN/FLAG/FAIL/SKIPPED), message; click to expand `data`.
   - **PO match card**: tier used, method chip (EXPLICIT / INFERRED_VENDOR / INFERRED_ITEMS / MANUAL), selected PO. **Candidates table** with total score and per-signal mini bars, and notes. Unmatched invoice lines highlighted.
   - **PO balance card**: stacked bar showing PO total, previously billed, reserved pending, this invoice, remaining after.
   - **Pipeline trace timeline**: each stage as a row (name, status dot, duration, summary, warnings), plus a small bar showing the latency share per stage and total time; shows `cached` and extraction method used.
   - **Raw JSON** collapsible with a copy button.
3. **Side panel / tabs**: **History** (ledger list with status chips, click to replay a stored result), **POs** (PO list with progress bar billed/total, expand to lines with qty remaining and linked invoices), **Vendors**.

**Review actions (shown only when `review.required`):**
- *Select PO*: radio list of candidates (with scores) plus a free-text PO field, **Apply**.
- *Edit extracted field*: inline-edit missing/low-confidence fields (invoice number, date, total, vendor), **Re-run with overrides**.
- *Confirm vendor*: choose from closest vendors.
- *Duplicate*: "Not a duplicate, continue" / "Reject as duplicate".
- Free-text note, final **Approve** / **Reject** buttons. Every action posts to `/api/invoices/{id}/resolve` and refreshes the result; the trace shows the `manual_override` stage.

**Extras:** a "Load demo scenarios" dropdown that lists the sample invoices from `/samples` (with expected outcome tags) so evaluators can run each edge case with one click; a dark/light toggle is optional; keyboard accessible; empty and error states handled (API down, LLM key missing, unsupported file).

---

## 15. Synthetic data generator (`data_gen/`) and samples

Own CLI: `python -m data_gen.generate --seed 42 --out samples/`. Fully deterministic (seeded). Steps:

1. 15-20 vendors (Faker en_IN) with GSTIN, email domain, aliases (`ACME Pvt Ltd`/`Acme Private Limited`), bank account; 1 unapproved vendor; 2 lookalike vendor names for fuzzy tests.
2. Item catalog (~60 items, food/stationery/IT) with realistic prices, including **near-twin items**: Veg Burger vs Chicken Burger, 500ml vs 1L bottle, A4 80gsm vs A4 70gsm.
3. ~50 POs, 1-6 lines each, varied dates and statuses (OPEN, PARTIAL, CLOSED, CANCELLED). Deliberately create overlapping POs: the **three-burger scenario** (PO-A 5 items, PO-B 2 items, PO-C 3 items, all containing the same two burger items, differing in qty/price/remaining).
4. Compute embeddings when loading POs into the DB.
5. Invoice generator: pick a PO, build a clean invoice, apply **one mutation**, render PDF from 3-4 HTML layouts (itemised, bundled, tax-embedded, tax-separate), optionally degrade into a scan (rotate 1-3°, blur, noise, JPEG, stamp over total).
6. Write `samples/manifest.csv`: `file, edge_case_tag, expected_decision, expected_reason_code, expected_po, notes, run_order`, plus `samples/seed.json` (vendors, POs, items). Split-invoice series have a `run_order` so the batch runner processes them sequentially against the shared ledger. Also provide 5-6 real public invoice scans (document where to download them in the README; do not commit unlicensed files) for the OCR benchmark.

**Mutations and expected outcomes:**

| Tag | Mutation | Expected |
|---|---|---|
| `happy_explicit` | valid PO number, everything matches | APPROVED / OK |
| `no_po_vendor_known` | PO number dropped, clear winner | NEEDS_REVIEW / INFERRED_MATCH (or APPROVED if flag on) |
| `no_po_no_vendor` | PO and vendor dropped, items unique | NEEDS_REVIEW / INFERRED_MATCH |
| `burger_tie` | identical burger lines on 3 POs, tie after filters | NEEDS_REVIEW / AMBIGUOUS_PO with ranked candidates |
| `burger_clear_winner` | same but qty/price/total picks one PO | NEEDS_REVIEW with PO selected, high score |
| `po_typo` | `PO-2026-0O42` | NEEDS_REVIEW / INVALID_PO_REF + suggestion |
| `po_other_vendor` | PO belongs to another vendor | REJECTED / VENDOR_MISMATCH |
| `po_closed` | invoice against closed PO | REJECTED / PO_CLOSED |
| `split_1..4` | one PO split into 3 invoices then a 4th | APPROVED, APPROVED, APPROVED (closes PO), REJECTED / PO_CLOSED |
| `split_partial_qty` | second invoice bills more than remaining qty | NEEDS_REVIEW / QTY_EXCEEDS_REMAINING |
| `dup_exact` | resend same invoice | REJECTED / DUPLICATE_EXACT |
| `dup_near` | resend with `INV-001` vs `INV001`, or re-scan | NEEDS_REVIEW or REJECTED / DUPLICATE_* |
| `same_invno_other_vendor` | same invoice number, different vendor | not a duplicate, proceeds |
| `tol_warn` / `tol_review` / `tol_reject` | total x1.01 / x1.04 / x1.10 | APPROVED_WITH_NOTE / NEEDS_REVIEW / REJECTED / OVERBILLED |
| `price_drift` | prices up, quantities down, same total | NEEDS_REVIEW / PRICE_DRIFT |
| `reworded_items` | descriptions reworded ("Vegetable Burger 150g") | still matches via fuzzy/embedding |
| `arith_mismatch` | totals do not add up | NEEDS_REVIEW / ARITHMETIC_MISMATCH |
| `missing_total` / `missing_date` / `missing_invno` | field removed | NEEDS_REVIEW / MISSING_FIELDS (names the field) |
| `scan_blur_stamp` | rotated, blurred, stamp over total | OCR fallback chain exercised, then review or approve |
| `vendor_lookalike` | `Acrne Foods` | NEEDS_REVIEW / VENDOR_UNCLEAR |
| `vendor_unapproved` | blocked vendor | REJECTED / VENDOR_NOT_APPROVED |
| `bank_changed` | bank account differs from master | flagged, NEEDS_REVIEW |
| `currency_mismatch` | USD vs INR PO | REJECTED / CURRENCY_MISMATCH |
| `credit_note` | negative amounts | NEEDS_REVIEW / UNSUPPORTED_DOCUMENT_TYPE |
| `future_dated` / `stale` | date issues | NEEDS_REVIEW / DATE_INVALID |
| `number_formats` | `1,00,000.00`, `Rs.`, DD/MM ambiguity | parsed correctly or flagged ambiguous |
| `extra_freight_line` | freight line not on PO | allowed with note |

Produce roughly 40-60 invoices: ~15 happy path, the rest spread across mutations.

---

## 16. The four highlighted edge cases (documented in the README, each with a worked example and screenshots/trace)

1. **Split invoicing with balance closure**: PO of ₹100,000 billed as ₹40k, ₹40k, ₹20k (closes the PO), then a 4th is rejected. Shows the ledger and remaining-balance logic, plus quantity-level tracking.
2. **Missing PO reference with an identical-items tie** (the burger case): shows Tier 2/3 narrowing, per-signal scores, the margin rule, and the human resolution path. Include both a clear-winner variant and a genuine-tie variant.
3. **Near-duplicate resubmission with a changed invoice number format** (`INV-001` vs `INV001`, re-scanned file with a different hash): exact matching misses it, normalized key plus (vendor, amount, date) catches it.
4. **Hidden price drift under a matching total, on a degraded scan**: total is within tolerance, but unit prices and quantities were altered; OCR fallback chain runs; line-level checks catch what the total check passes.

---

## 17. Build order (do these phases in sequence; run tests after each)

1. **Skeleton and config**: repo layout, `pyproject.toml`, `config.yaml`, Pydantic config loader with validation, `models.py`, trace recorder. Tests: config validation, weights sum.
2. **Store**: schema, repositories, transactions, embedder interface (MiniLM + TF-IDF), in-memory index, `seed-demo`. Tests: balance computation, transaction rollback, concurrent consume.
3. **Normalizers and rules** (pure functions first): number/date/invoice-no/vendor-name normalization, arithmetic and tolerance rules, duplicates. Tests with edge inputs (`1,00,000.00`, `03/04/2026`, `INV-001`).
4. **Matching**: vendor resolver, tiers 1-3, item matcher, scoring, router. Tests on the three-burger fixtures (clear winner, tie, empty intersection).
5. **Decision**: aggregator, explainer, confidence. Tests on the precedence order.
6. **Ingest and extraction**: text layer, preprocess, both OCR engines behind one interface, Gemini client with schema output, grounding, vision fallback. Mock the LLM in unit tests (record fixtures); live LLM tests only behind a marker `@pytest.mark.live`.
7. **Orchestrator and CLI**: `process_invoice`, Typer commands, human-readable report. Test CLI via `CliRunner`.
8. **Data generator and manifest**, then the integration test that runs the manifest end to end and compares expected vs actual decision, reason code and PO; target >= 90% agreement, list every miss in the report.
9. **Server**: routes, DI, upload limits, static mount. Tests with FastAPI `TestClient` (upload a sample, resolve a review).
10. **Frontend**: build against the real API, verify every decision type and review action renders.
11. **Benchmarks**: `bench ocr` (text layer vs Tesseract vs RapidOCR vs vision LLM) on sample digital PDFs, scans and phone photos: p50/p95 latency per stage, peak RAM, field-level accuracy against the manifest ground truth, cost per invoice. `bench matching`: item index vs brute force at 1k/10k/100k lines; embedding model vs TF-IDF accuracy and latency. Output CSV and a markdown table; include one chart.
12. **Docker and README**: multi-stage slim image (install Tesseract binary; RapidOCR via pip; MiniLM downloaded lazily or baked in, controlled by an env flag), `docker run` instructions, `.env.example` (`GEMINI_API_KEY`), healthcheck. README covers architecture diagram (mermaid), the flowchart, decision precedence, config reference, edge case walkthroughs, the benchmark table, honest limitations, and how to run via CLI, API and Python.

---

## 18. Quality bar and constraints

- No business logic in the server or frontend. The frontend only renders `DecisionResult` and posts reviewer actions.
- All thresholds, weights and keyword lists come from config. A grep for stray numeric literals in `matching/` and `validation/` should come back clean.
- Each rule and matcher has unit tests including a failing-input case. Keep functions small and pure where possible.
- Log with structured fields (`request_id`, `stage`, `duration_ms`). Never log the API key or full invoice text at INFO.
- Redact secrets in `/api/config`. Validate and size-limit uploads. Handle LLM timeouts, rate limits and malformed JSON with retries and a clean `UNREADABLE_DOCUMENT` fallback.
- Lazy-load heavy components (MiniLM, OCR engines) on first use, and expose whether each is loaded in `/api/health`. Cold-start time matters on small hosts.
- The pipeline must work with the LLM disabled for pre-extracted JSON input (`invoice-ap process --from-json extracted.json`) so matching and decisions are testable without any API calls or OCR.
- Be honest in the README about limits: confidence is a heuristic; embeddings can confuse near-twin items; inferred matches always need a human; real AP systems also use goods-receipt notes (3-way matching), which are out of scope but noted as the next step.

## 19. Acceptance criteria

- `invoice-ap process samples/<file>.pdf` prints a decision with reasoning, checks, candidates and a per-stage trace; `--json` matches the schema in 7.2.
- The same call via `POST /api/invoices/process` returns the identical `DecisionResult`.
- Switching `ocr.engine` between `tesseract` and `rapidocr` in `config.yaml` (or via CLI/API override) changes the engine used, visible in the trace.
- Changing thresholds in `config.yaml` changes behavior without code edits (e.g. setting `auto_approve_inferred: true` flips inferred matches to APPROVED).
- The batch run over `samples/manifest.csv` reports agreement per edge-case tag, and all four highlighted edge cases pass.
- The split-invoice series shows the PO remaining balance dropping after each approval and rejects the 4th.
- The frontend renders every decision type, supports every review action in section 14, and replays history.
- `docker build` and `docker run` start the app with a working UI at `/`, with a health endpoint reporting engine availability.
