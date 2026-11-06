"""Unit and integration tests for datagen.money."""

from decimal import Decimal
import pytest

from datagen.money import (
    compute_line_tax,
    compute_line_total,
    compute_totals,
    quantize_money,
    to_decimal,
)


def test_quantize_and_to_decimal():
    assert to_decimal(10) == Decimal("10")
    assert to_decimal("12.34") == Decimal("12.34")
    assert quantize_money("10.005") == Decimal("10.01")  # ROUND_HALF_UP
    assert quantize_money("10.004") == Decimal("10.00")
    assert quantize_money("10.0050") == Decimal("10.01")


def test_contract_worked_example():
    """Check contract section 3:

    10 x 100.00 + 8 x 93.75 with 5% tax = 1000.00 + 750.00 = 1750.00, tax 87.50, total 1837.50.
    """
    lt1 = compute_line_total(10, "100.00")
    tx1 = compute_line_tax(lt1, 5)
    assert lt1 == Decimal("1000.00")
    assert tx1 == Decimal("50.00")

    lt2 = compute_line_total(8, "93.75")
    tx2 = compute_line_tax(lt2, 5)
    assert lt2 == Decimal("750.00")
    assert tx2 == Decimal("37.50")

    subtotal, tax_total, grand_total = compute_totals([(lt1, tx1), (lt2, tx2)])
    assert subtotal == Decimal("1750.00")
    assert tax_total == Decimal("87.50")
    assert grand_total == Decimal("1837.50")


def test_rounding_half_up_edge_cases():
    # 2.5 cents -> 3 cents
    assert quantize_money("0.025") == Decimal("0.03")
    # 0.5 cents -> 1 cent
    assert quantize_money("0.005") == Decimal("0.01")
    # 0.4 cents -> 0 cents
    assert quantize_money("0.004") == Decimal("0.00")
