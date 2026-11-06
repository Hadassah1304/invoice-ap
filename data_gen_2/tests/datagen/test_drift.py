"""Tests for price_drift exact-sum integer-cent solver."""

from decimal import Decimal
import random
import pytest

from datagen.money import compute_line_tax, compute_totals, quantize_money, to_decimal
from datagen.mutate.drift import compute_drifted_lines


def test_drift_2_lines():
    rng = random.Random(42)
    # 2 lines: 10 @ 100.00, 5 @ 200.00 -> target subtotal 2000.00
    lines = [
        {"qty": 10, "unit_price": Decimal("100.00"), "tax_rate": Decimal("5")},
        {"qty": 5, "unit_price": Decimal("200.00"), "tax_rate": Decimal("5")},
    ]
    target_subtotal = Decimal("2000.00")
    drifted = compute_drifted_lines(lines, target_subtotal, min_drift_pct=5.0, rng=rng)

    assert len(drifted) == 2
    sum_res = quantize_money(to_decimal(drifted[0][0]) * drifted[0][1] + to_decimal(drifted[1][0]) * drifted[1][1])
    assert sum_res == target_subtotal

    # verify at least one drifted >= 5%
    p0 = drifted[0][1]
    p1 = drifted[1][1]
    drift0 = abs(p0 - Decimal("100.00")) / Decimal("100.00") * 100
    drift1 = abs(p1 - Decimal("200.00")) / Decimal("200.00") * 100
    assert drift0 >= 5.0 or drift1 >= 5.0


def test_drift_3_lines_odd_tax():
    rng = random.Random(123)
    # 3 lines: 8 @ 12.50, 4 @ 50.00, 2 @ 150.00 -> 100.00 + 200.00 + 300.00 = 600.00
    lines = [
        {"qty": 8, "unit_price": Decimal("12.50"), "tax_rate": Decimal("18")},
        {"qty": 4, "unit_price": Decimal("50.00"), "tax_rate": Decimal("18")},
        {"qty": 2, "unit_price": Decimal("150.00"), "tax_rate": Decimal("18")},
    ]
    target_subtotal = Decimal("600.00")
    drifted = compute_drifted_lines(lines, target_subtotal, min_drift_pct=5.0, rng=rng)

    assert len(drifted) == 3
    sum_res = quantize_money(sum(to_decimal(q) * p for q, p in drifted))
    assert sum_res == target_subtotal


def test_drift_single_line_raises():
    lines = [{"qty": 1, "unit_price": Decimal("100.00"), "tax_rate": Decimal("0")}]
    with pytest.raises(ValueError):
        compute_drifted_lines(lines, Decimal("100.00"), min_drift_pct=5.0)
