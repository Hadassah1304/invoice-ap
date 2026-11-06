"""Money rules and Decimal arithmetic helpers.

Contract Section 3:
- All money is Decimal. Input JSON numbers have at most 2 decimals; parse via Decimal(str(x)).
- line_total = ROUND_HALF_UP(qty * unit_price, 2)
- line_tax = ROUND_HALF_UP(line_total * tax_rate / 100, 2)
- subtotal = sum(line_total), tax_total = sum(line_tax), grand_total = subtotal + tax_total
- A PO total uses the same formula over its lines.
- Check: 10 x 100.00 + 8 x 93.75 with 5% tax = 1000.00 + 750.00 = 1750.00, tax 87.50, total 1837.50.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence, Tuple, Union

TWO_PLACES = Decimal("0.01")


def to_decimal(val: Union[int, float, str, Decimal]) -> Decimal:
    """Safely convert any numeric input into Decimal."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def quantize_money(val: Union[int, float, str, Decimal]) -> Decimal:
    """Quantize to two decimal places using ROUND_HALF_UP."""
    d = to_decimal(val)
    return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_line_total(qty: Union[int, float, str, Decimal], unit_price: Union[int, float, str, Decimal]) -> Decimal:
    """line_total = ROUND_HALF_UP(qty * unit_price, 2)"""
    q = to_decimal(qty)
    p = to_decimal(unit_price)
    return quantize_money(q * p)


def compute_line_tax(line_total: Union[int, float, str, Decimal], tax_rate: Union[int, float, str, Decimal]) -> Decimal:
    """line_tax = ROUND_HALF_UP(line_total * tax_rate / 100, 2)"""
    lt = to_decimal(line_total)
    tr = to_decimal(tax_rate)
    return quantize_money(lt * tr / Decimal("100"))


def compute_totals(lines: Sequence[Tuple[Decimal, Decimal]]) -> Tuple[Decimal, Decimal, Decimal]:
    """Given sequence of (line_total, line_tax), computes:

    (subtotal, tax_total, grand_total).
    """
    subtotal = quantize_money(sum((lt for lt, _ in lines), Decimal("0.00")))
    tax_total = quantize_money(sum((tx for _, tx in lines), Decimal("0.00")))
    grand_total = quantize_money(subtotal + tax_total)
    return subtotal, tax_total, grand_total
