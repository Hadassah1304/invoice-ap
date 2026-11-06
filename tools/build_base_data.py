"""
Builder and validator for base synthetic dataset files according to:
- 00_CONTRACT.md
- 01_BASE_DATA_AGENTS.md
"""
from __future__ import annotations
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
import rapidfuzz.fuzz as fuzz

REFERENCE_DATE_STR = "2026-11-06"
REFERENCE_DATE = datetime.strptime(REFERENCE_DATE_STR, "%Y-%m-%d").date()

def normalize_invoice_no(raw: str | None) -> str:
    if not raw:
        return ""
    clean = re.sub(r"[\s\-\/\#\_\:\.]+", "", str(raw)).upper()
    return re.sub(r"^0+", "", clean)

def normalize_vendor_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    suffixes = [
        r"\bprivate\s+limited\b",
        r"\bpvt\s+ltd\b",
        r"\blimited\b",
        r"\bpvt\b",
        r"\bltd\b",
        r"\bllp\b",
        r"\binc\b",
        r"\bcorp\b",
        r"\bcorporation\b",
        r"\bcompany\b",
        r"\bco\b",
    ]
    for suf in suffixes:
        s = re.sub(suf, "", s)
    return " ".join(s.split())

def calc_totals(lines):
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    for l in lines:
        qty = Decimal(str(l["qty"]))
        price = Decimal(str(l["unit_price"]))
        tax_rate = Decimal(str(l.get("tax_rate", 0)))
        lt = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lx = (lt * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        subtotal += lt
        tax_total += lx
    grand_total = subtotal + tax_total
    return subtotal, tax_total, grand_total

print("Normalizer and calc_totals defined.")
