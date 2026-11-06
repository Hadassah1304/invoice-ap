"""Normalizer helpers, mirroring pipeline logic for deterministic usage."""

import re
from typing import Optional


def normalize_invoice_number(raw: Optional[str]) -> str:
    """Uppercase, strip spaces, dashes, slashes, and leading zeros from numeric chunks."""
    if not raw:
        return ""
    clean = re.sub(r"[\s\-\/\#\_\:\.]+", "", str(raw)).upper()
    clean = re.sub(r"^0+", "", clean)
    return clean


def normalize_vendor_name(raw: Optional[str]) -> str:
    """Lowercase, strip legal entity suffixes and punctuation."""
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
