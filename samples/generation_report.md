# AP Synthetic Data Generation Report

- **Reference Date**: `2026-11-06`
- **Random Seed**: `42`
- **Total Vendors**: 17
- **Total POs**: 60
- **Total Invoices**: 61
- **Degraded Invoices**: 4
- **Embeddings Backend**: `tfidf`

## Invoices by Edge-Case Tag

| Edge Case Tag | Count | Expected Outcome |
|---|---|---|
| `arith_mismatch` | 1 | NEEDS_REVIEW / ARITHMETIC_MISMATCH |
| `bank_changed` | 1 | NEEDS_REVIEW / VENDOR_UNCLEAR |
| `burger_clear_winner` | 1 | NEEDS_REVIEW / INFERRED_MATCH |
| `burger_tie` | 1 | NEEDS_REVIEW / AMBIGUOUS_PO |
| `credit_note` | 1 | NEEDS_REVIEW / UNSUPPORTED_DOCUMENT_TYPE |
| `currency_mismatch` | 1 | REJECTED / CURRENCY_MISMATCH |
| `dup_exact` | 2 | APPROVED / OK |
| `dup_near_format` | 2 | APPROVED / OK |
| `dup_possible` | 2 | APPROVED / OK |
| `dup_rescan` | 1 | REJECTED / DUPLICATE_EXACT |
| `extra_freight_line` | 1 | APPROVED / APPROVED_WITH_NOTE |
| `future_dated` | 1 | NEEDS_REVIEW / DATE_INVALID |
| `happy_explicit` | 12 | APPROVED / OK |
| `happy_partial_delivery` | 2 | APPROVED / OK |
| `missing_date` | 1 | NEEDS_REVIEW / MISSING_FIELDS |
| `missing_invno` | 1 | NEEDS_REVIEW / MISSING_FIELDS |
| `missing_total` | 1 | NEEDS_REVIEW / MISSING_FIELDS |
| `no_po_no_vendor` | 2 | NEEDS_REVIEW / INFERRED_MATCH |
| `no_po_vendor_known` | 2 | NEEDS_REVIEW / INFERRED_MATCH |
| `number_formats` | 2 | APPROVED / OK |
| `po_cancelled` | 1 | REJECTED / PO_CLOSED |
| `po_closed` | 1 | REJECTED / PO_CLOSED |
| `po_other_vendor` | 1 | REJECTED / VENDOR_MISMATCH |
| `po_typo` | 1 | NEEDS_REVIEW / INVALID_PO_REF |
| `price_drift` | 2 | NEEDS_REVIEW / PRICE_DRIFT |
| `reworded_items` | 2 | APPROVED / OK |
| `same_invno_other_vendor` | 1 | APPROVED / OK |
| `scan_blur_stamp` | 2 | APPROVED / OK |
| `split_1` | 1 | APPROVED / OK |
| `split_2` | 1 | APPROVED / OK |
| `split_3` | 1 | APPROVED / OK |
| `split_4` | 1 | REJECTED / PO_CLOSED |
| `split_partial_qty` | 2 | APPROVED / OK |
| `stale` | 1 | NEEDS_REVIEW / DATE_INVALID |
| `tol_reject` | 1 | REJECTED / OVERBILLED |
| `tol_review` | 1 | NEEDS_REVIEW / OVERBILLED |
| `tol_warn` | 1 | APPROVED / APPROVED_WITH_NOTE |
| `vendor_lookalike` | 1 | NEEDS_REVIEW / VENDOR_UNCLEAR |
| `vendor_unapproved` | 1 | REJECTED / VENDOR_NOT_APPROVED |

## Invariant Self-Check Results

- All invariant self-checks passed with 0 violations.
