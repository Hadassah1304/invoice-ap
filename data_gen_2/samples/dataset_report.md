# Synthetic Invoice Dataset Report

- **Total Cases**: 58
- **Embedder Backend**: `tfidf`
- **Total File Size**: 63688.2 KB (Min: 2228 B, Max: 8039.4 KB)

## 1. Counts by Family

| Family | Case Count |
|---|---|
| B | 12 |
| I | 11 |
| N | 23 |
| R | 12 |

## 2. Counts by Degradation Level

| Degradation Level | Count | Pct |
|---|---|---|
| `heavy` | 4 | 6.9% |
| `light` | 6 | 10.3% |
| `medium` | 5 | 8.6% |
| `none` | 43 | 74.1% |

## 3. Counts by Layout

| Layout | Count |
|---|---|
| `bundled` | 11 |
| `itemised` | 31 |
| `multi_page` | 7 |
| `tax_embedded` | 9 |

## 4. Confidence Breakdown

| Confidence | Count |
|---|---|
| `firm` | 47 |
| `soft` | 11 |

## 5. Series Sequences

| Series ID | Run Orders | Cases |
|---|---|---|
| `B-QTY` | 1, 2 | SC-B-QTY-01, SC-B-QTY-02 |
| `B-SPLIT` | 3, 4, 5, 6 | SC-B-SPLIT-01, SC-B-SPLIT-02, SC-B-SPLIT-03, SC-B-SPLIT-04 |
| `I-DUP` | 13, 14, 15, 16, 17, 18, 19 | SC-I-DUP-01, SC-I-DUP-02, SC-I-DUP-03, SC-I-DUP-04, SC-I-DUP-05, SC-I-CTRL-01, SC-I-DUP-06 |

## 6. Informational OCR Calibration

| Level | Sample File | OCR Status | Detected Snippets |
|---|---|---|---|
| `light` | `scans/b04_split_2.pdf` | OK | `TAX INVOICE CyberTech Hardware Systems LLP InvoiceNo:TCH/26/5803 GSTIN:27AABBC33` |
| `medium` | `scans/b06_split_4.png` | OK | `TAX INVOICE Invoice Number: TCH/26/9234 CyberTech Hardware Systems LLP Invoice D` |
| `heavy` | `scans/b10_tol_reject.jpg` | OK | `TAXINVOICE VardhamanBulk CommoditiesPvt Ltd GSTIN:27AABCV3344JIZ7 Invoice Number` |

## 7. Pipeline Execution Commands

To load this dataset into the pipeline database and run the batch evaluation:

```bash
# 1. Initialize DB and load seed data (including ledger preload):
invoice-ap init-db
python -m seed.load_dataset --seed samples/seed.json --db data/ap.db --reset

# 2. Execute batch pipeline against manifest:
invoice-ap batch samples/ --manifest samples/manifest.csv --report report.csv
```

> **Important**: Invoices must be processed strictly in `run_order` sequence. The database must be initialized with `seed.json` prior to execution.
