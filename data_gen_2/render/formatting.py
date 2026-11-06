from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Optional, Union


def format_number(amount: Optional[Union[float, int, str, Decimal]], number_format: str = "plain") -> str:
    """Format a monetary amount according to number_format ('plain', 'indian', 'eu').
    
    Negative numbers print with a leading minus ('-1,837.50').
    Null amounts return empty string.
    """
    if amount is None or amount == "":
        return ""

    if isinstance(amount, (int, float, str)):
        d = Decimal(str(amount))
    elif isinstance(amount, Decimal):
        d = amount
    else:
        return ""

    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    is_negative = d < 0
    abs_d = abs(d)

    parts = f"{abs_d:.2f}".split(".")
    int_part = parts[0]
    dec_part = parts[1]

    sign_str = "-" if is_negative else ""

    if number_format == "plain":
        return f"{sign_str}{int_part}.{dec_part}"

    elif number_format == "indian":
        # Indian lakh grouping: last 3 digits, then every 2 digits
        if len(int_part) <= 3:
            grouped = int_part
        else:
            last3 = int_part[-3:]
            rem = int_part[:-3]
            chunks = []
            while len(rem) > 2:
                chunks.insert(0, rem[-2:])
                rem = rem[:-2]
            if rem:
                chunks.insert(0, rem)
            grouped = ",".join(chunks) + "," + last3
        return f"{sign_str}{grouped}.{dec_part}"

    elif number_format == "eu":
        # European format: period as thousands separator, comma as decimal separator
        # Standard 3-digit grouping
        grouped = f"{int(int_part):,}".replace(",", ".")
        return f"{sign_str}{grouped},{dec_part}"

    else:
        # Fallback to plain
        return f"{sign_str}{int_part}.{dec_part}"


def format_currency(
    amount: Optional[Union[float, int, str, Decimal]],
    currency_style: str = "Rs.",
    currency: str = "INR",
    number_format: str = "plain",
) -> str:
    """Format a monetary amount with currency prefix according to currency_style.
    
    currency_style:
      - 'Rs.' -> 'Rs. 1,837.50' (negative: 'Rs. -1,837.50')
      - '₹'   -> '₹1,837.50'   (negative: '₹-1,837.50')
      - 'INR' -> 'INR 1,837.50' (negative: 'INR -1,837.50')
    For non-INR (e.g. USD):
      - '$'   -> '$1,837.50'
      - 'USD' -> 'USD 1,837.50'
    """
    if amount is None or amount == "":
        return ""

    num_str = format_number(amount, number_format=number_format)

    if currency.upper() == "INR":
        if currency_style == "₹":
            prefix = "₹"
        elif currency_style == "INR":
            prefix = "INR "
        else:
            prefix = "Rs. "
    elif currency.upper() == "USD":
        if currency_style == "$" or currency_style == "₹":
            prefix = "$"
        elif currency_style == "USD":
            prefix = "USD "
        else:
            prefix = "$ "
    else:
        prefix = f"{currency} "

    return f"{prefix}{num_str}"


_MONTH_ABBR = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def format_date(date_str: Optional[str], date_style: str = "dmy_slash") -> str:
    """Format an ISO date YYYY-MM-DD into the requested date_style.
    
    - 'dmy_slash' -> '06/11/2026'
    - 'dmy_mon'   -> '06-Nov-2026'
    - 'iso'       -> '2026-11-06'
    """
    if not date_str:
        return ""

    # Expected ISO format YYYY-MM-DD
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(date_str).strip())
    if not match:
        return str(date_str)

    year = int(match.group(1))
    month = int(match.group(2))
    day = int(match.group(3))

    if date_style == "dmy_slash":
        return f"{day:02d}/{month:02d}/{year:04d}"
    elif date_style == "dmy_mon":
        month_abbr = _MONTH_ABBR[month] if 1 <= month <= 12 else f"{month:02d}"
        return f"{day:02d}-{month_abbr}-{year:04d}"
    elif date_style == "iso":
        return f"{year:04d}-{month:02d}-{day:02d}"
    else:
        return f"{day:02d}/{month:02d}/{year:04d}"
