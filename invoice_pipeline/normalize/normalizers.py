from __future__ import annotations

from datetime import datetime
import re
from typing import Any, List, Optional, Tuple


def normalize_invoice_number(raw: Optional[str]) -> str:
    """Uppercase, strip spaces, dashes, slashes, and leading zeros from numeric chunks."""
    if not raw:
        return ""
    # Strip spaces, slashes, dashes, hash signs, underscores, dots
    clean = re.sub(r"[\s\-\/\#\_\:\.]+", "", str(raw)).upper()
    # Strip leading zeros from numeric prefix or body
    clean = re.sub(r"^0+", "", clean)
    return clean


def normalize_vendor_name(raw: Optional[str]) -> str:
    """Lowercase, strip legal entity suffixes (pvt, ltd, llp, inc, etc.) and punctuation."""
    if not raw:
        return ""
    s = raw.lower()
    # Remove punctuation
    s = re.sub(r"[^\w\s]", " ", s)
    # Remove common corporate suffixes
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


def normalize_currency(raw: Optional[str], default: str = "INR") -> str:
    if not raw:
        return default
    clean = str(raw).strip().upper()
    symbols = {
        "₹": "INR",
        "RS": "INR",
        "RS.": "INR",
        "INR": "INR",
        "$": "USD",
        "USD": "USD",
        "€": "EUR",
        "EUR": "EUR",
        "£": "GBP",
        "GBP": "GBP",
    }
    return symbols.get(clean, clean)


def parse_number(val: Any) -> Optional[float]:
    """Parse number supporting Indian (1,00,000.00), European (1.000,00), parentheses negatives."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1].strip()
    elif s.startswith("-"):
        is_negative = True
        s = s[1:].strip()

    # Strip currency words and symbols
    s = re.sub(r"(?i)\b(rs|inr|usd|eur|gbp)\b", "", s)
    s = re.sub(r"[₹$€£]", "", s)
    s = re.sub(r"[^\d,\.\-]", "", s)
    s = re.sub(r"^[\,\.]+", "", s)
    if not s:
        return None

    # European format with multiple dots: 1.000.000,50
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) == 3:
            s = s.replace(",", "")
        elif len(parts) == 2 and len(parts[1]) in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        # E.g. 1.000.000 without comma
        if len(parts) > 2 and all(len(p) == 3 for p in parts[1:]):
            s = "".join(parts)

    try:
        res = float(s)
        return -res if is_negative else res
    except ValueError:
        return None


def parse_date(
    date_str: Optional[str],
    priority_formats: Optional[List[str]] = None,
    ambiguous_policy: str = "flag",
) -> Tuple[Optional[str], bool]:
    """
    Parses a date string into ISO YYYY-MM-DD.
    Returns (iso_date_or_none, is_ambiguous).
    Never returns an invalid string that would corrupt a SQLite DATE column.
    """
    if not date_str or not str(date_str).strip():
        return None, False

    clean = str(date_str).strip()
    formats = priority_formats or [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %B %Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%Y/%m/%d",
        "%m/%d/%Y",
    ]

    # Check for DD/MM vs MM/DD ambiguity (e.g. 03/04/2026)
    m = re.match(r"^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$", clean)
    is_ambiguous = False
    if m:
        p1, p2 = int(m.group(1)), int(m.group(2))
        if 1 <= p1 <= 12 and 1 <= p2 <= 12 and p1 != p2:
            is_ambiguous = True

    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.strftime("%Y-%m-%d"), is_ambiguous
        except ValueError:
            continue

    # Try ISO directly
    try:
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d"), False
    except ValueError:
        pass

    return None, False
