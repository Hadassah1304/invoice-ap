"""Price drift algorithm.

02_PIPELINE_SCRIPTS.md Section 5:
Input: the PO lines billed (qty, price, tax rate, all lines the same tax rate, enforced by precondition),
       a target subtotal equal to the clean invoice subtotal.
Output: new (qty, unit_price) per line such that:
- sum(ROUND(qty*price,2)) == target_subtotal exactly (so subtotal, tax and grand total are unchanged),
- at least one line has abs(price - po_price)/po_price*100 >= min_drift_pct, preferably price up and quantity down,
- qty <= po qty, qty is a positive integer if the PO qty is an integer, prices have at most 2 decimals and stay positive,
- no line has qty == po qty AND price == po price for all lines (something must change).
"""

from decimal import Decimal
import random
from typing import List, Tuple, Dict, Any

from datagen.money import quantize_money, to_decimal


def compute_drifted_lines(
    lines: List[Dict[str, Any]],
    target_subtotal: Decimal,
    min_drift_pct: float = 5.0,
    rng: random.Random = None,
) -> List[Tuple[int, Decimal]]:
    """lines: list of dicts with 'qty' (int), 'unit_price' (Decimal), 'tax_rate' (Decimal).

    Returns list of (new_qty, new_price) for each line.
    """
    if rng is None:
        rng = random.Random(42)

    n = len(lines)
    if n < 1:
        raise ValueError("Cannot drift empty lines")

    min_drift_d = Decimal(str(min_drift_pct)) / Decimal("100")

    # If 1 line: we can't change price/qty while keeping sum(qty*price) == target_subtotal
    # unless factor pairs match target cents, but precondition requires >= 2 lines.
    if n == 1:
        raise ValueError("price_drift requires at least 2 lines to rebalance subtotal")

    # We will try deterministic candidate permutations
    line_indices = list(range(n))

    for attempt in range(500):
        # Pick which line to drift up (price up, qty down)
        drift_idx = line_indices[attempt % n]
        other_indices = [i for i in range(n) if i != drift_idx]

        orig_qty = lines[drift_idx]["qty"]
        orig_price = to_decimal(lines[drift_idx]["unit_price"])

        # Try reducing qty by 1 .. max(1, orig_qty - 1)
        max_red = max(1, orig_qty - 1)
        # deterministic choice from rng
        qty_reduction = rng.randint(1, max_red)
        new_drift_qty = orig_qty - qty_reduction

        # Pick price factor in [1 + min_drift, 1 + 3 * min_drift]
        # Generate random factor
        factor_steps = rng.randint(0, 100)
        factor = Decimal("1.0") + min_drift_d + (Decimal("2.0") * min_drift_d * Decimal(str(factor_steps)) / Decimal("100"))
        
        # Candidate drifted price
        candidate_price = quantize_money(orig_price * factor)
        if candidate_price <= orig_price:
            candidate_price = quantize_money(orig_price + Decimal("1.00"))

        drift_line_total = quantize_money(to_decimal(new_drift_qty) * candidate_price)
        remaining_subtotal = target_subtotal - drift_line_total

        if remaining_subtotal <= Decimal("0.00"):
            continue

        # Solve for other lines
        if len(other_indices) == 1:
            other_idx = other_indices[0]
            other_orig_qty = lines[other_idx]["qty"]
            other_orig_price = to_decimal(lines[other_idx]["unit_price"])

            # We need other_new_qty * other_new_price == remaining_subtotal
            # and other_new_qty <= other_orig_qty, and other_new_qty is positive int
            # Check integer quantities from other_orig_qty down to 1
            possible_qtys = list(range(other_orig_qty, 0, -1))
            rng.shuffle(possible_qtys)
            found_solution = False
            for cand_qty in possible_qtys:
                # price = remaining_subtotal / cand_qty
                # Check if it has at most 2 decimals
                cand_price = quantize_money(remaining_subtotal / to_decimal(cand_qty))
                if quantize_money(to_decimal(cand_qty) * cand_price) == remaining_subtotal and cand_price > Decimal("0.00"):
                    # Check requirements
                    result: List[Tuple[int, Decimal]] = [(0, Decimal("0.00"))] * n
                    result[drift_idx] = (new_drift_qty, candidate_price)
                    result[other_idx] = (cand_qty, cand_price)

                    # Validate drift condition
                    pct_drift_0 = abs(candidate_price - orig_price) / orig_price * Decimal("100")
                    pct_drift_1 = abs(cand_price - other_orig_price) / other_orig_price * Decimal("100")
                    if pct_drift_0 >= Decimal(str(min_drift_pct)) or pct_drift_1 >= Decimal(str(min_drift_pct)):
                        return result
        else:
            # For 2 or more other lines: fix all but the last other line, solve the last
            fixed_subtotal = Decimal("0.00")
            candidate_results: Dict[int, Tuple[int, Decimal]] = {}
            candidate_results[drift_idx] = (new_drift_qty, candidate_price)

            # Keep other lines close to original or slightly adjusted
            valid_inter = True
            for o_idx in other_indices[:-1]:
                o_orig_qty = lines[o_idx]["qty"]
                o_orig_price = to_decimal(lines[o_idx]["unit_price"])
                # keep original
                candidate_results[o_idx] = (o_orig_qty, o_orig_price)
                fixed_subtotal += quantize_money(to_decimal(o_orig_qty) * o_orig_price)

            last_idx = other_indices[-1]
            last_orig_qty = lines[last_idx]["qty"]
            last_orig_price = to_decimal(lines[last_idx]["unit_price"])

            needed_last = remaining_subtotal - fixed_subtotal
            if needed_last > Decimal("0.00"):
                for cand_qty in range(last_orig_qty, 0, -1):
                    cand_price = quantize_money(needed_last / to_decimal(cand_qty))
                    if quantize_money(to_decimal(cand_qty) * cand_price) == needed_last and cand_price > Decimal("0.00"):
                        candidate_results[last_idx] = (cand_qty, cand_price)
                        res = [candidate_results[i] for i in range(n)]
                        # Check drift
                        if abs(candidate_price - orig_price) / orig_price * Decimal("100") >= Decimal(str(min_drift_pct)):
                            return res

    raise RuntimeError(f"Could not find an exact integer-cent price_drift solution for target {target_subtotal} within 500 iterations")
