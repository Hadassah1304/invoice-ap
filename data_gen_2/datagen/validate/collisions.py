"""Collision validator checks (V13-V18).

V13: Same vendor, grand totals within 0.5% and dates within near_dup_window_days + 3 (10 days),
     unless relation.type == duplicate_of.
V14: Same vendor, normalized invoice-number similarity (rapidfuzz ratio/100) >= 0.85,
     unless intended duplicate or control.
V15: Same raw invoice number across different vendors only for control_of.
V16: No two final documents identical (hash of canonical document JSON), except resend_identical / rerender / rescan.
V17: Each PO is referenced (as po_id or po_reference) by one scenario, or by scenarios of one series,
     or by a swap_po_ref target, or none (noise).
V18: Series positions contiguous starting at 1, all members same family.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Dict, List
from rapidfuzz import fuzz

from datagen.constants import Config
from datagen.finalize import FinalizedState
from datagen.loader import LoadedBase
from datagen.money import to_decimal
from datagen.norm import normalize_invoice_number


def get_dup_cluster_origin(sc: Any, all_scenarios: Dict[str, Any]) -> str:
    """Returns the root scenario ID if sc is part of an intended duplicate/control relationship."""
    if not sc:
        return ""
    if sc.relation and sc.relation.type in ["duplicate_of", "control_of"] and sc.relation.scenario_id:
        return sc.relation.scenario_id
    if sc.derive_from:
        return sc.derive_from.scenario_id
    return sc.scenario_id


def validate_collisions(loaded: LoadedBase, finalized: FinalizedState, compiled_cases: List[Any], config: Config = None) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if config is None:
        config = Config()

    core = loaded.core
    families = loaded.families
    near_dup_window = config.get("near_dup_window_days", 7) + 3  # 10 days per C4 / V13

    # Map scenario_id to authored scenario
    all_authored_scenarios = {sc.scenario_id: sc for f in families.values() for sc in f.scenarios}

    case_list = compiled_cases

    # V13 & V14: Pairwise within the same vendor
    for i in range(len(case_list)):
        c1 = case_list[i]
        sc1 = all_authored_scenarios.get(c1.case_id)
        v1 = c1.document.vendor_block.name if c1.document.vendor_block else None
        amt1 = to_decimal(c1.document.grand_total) if c1.document.grand_total is not None else None
        date1_str = c1.document.invoice_date
        raw_no1 = c1.document.invoice_number
        norm_no1 = normalize_invoice_number(raw_no1)

        root1 = get_dup_cluster_origin(sc1, all_authored_scenarios)

        for j in range(i + 1, len(case_list)):
            c2 = case_list[j]
            sc2 = all_authored_scenarios.get(c2.case_id)
            v2 = c2.document.vendor_block.name if c2.document.vendor_block else None
            amt2 = to_decimal(c2.document.grand_total) if c2.document.grand_total is not None else None
            date2_str = c2.document.invoice_date
            raw_no2 = c2.document.invoice_number
            norm_no2 = normalize_invoice_number(raw_no2)

            root2 = get_dup_cluster_origin(sc2, all_authored_scenarios)

            # Check if both belong to the same duplicate cluster or direct relation
            is_intended_dup = (
                (sc1 and sc1.relation and sc1.relation.type == "duplicate_of" and sc1.relation.scenario_id == sc2.scenario_id) or
                (sc2 and sc2.relation and sc2.relation.type == "duplicate_of" and sc2.relation.scenario_id == sc1.scenario_id) or
                (root1 and root2 and root1 == root2)
            )
            is_control = (
                (sc1 and sc1.relation and sc1.relation.type == "control_of" and sc1.relation.scenario_id == sc2.scenario_id) or
                (sc2 and sc2.relation and sc2.relation.type == "control_of" and sc2.relation.scenario_id == sc1.scenario_id) or
                (root1 and root2 and root1 == root2 and (
                    (sc1 and sc1.relation and sc1.relation.type == "control_of") or
                    (sc2 and sc2.relation and sc2.relation.type == "control_of")
                ))
            )

            # Same vendor checks
            if v1 and v2 and v1 == v2:
                # V13: Near-duplicate trap
                if amt1 is not None and amt2 is not None and date1_str and date2_str and not is_intended_dup:
                    d1 = datetime.date.fromisoformat(date1_str)
                    d2 = datetime.date.fromisoformat(date2_str)
                    date_delta = abs((d1 - d2).days)

                    if amt1 > Decimal("0.00"):
                        amt_diff_pct = abs(amt1 - amt2) / amt1 * Decimal("100")
                        if amt_diff_pct <= Decimal("0.5") and date_delta <= near_dup_window:
                            findings.append({
                                "code": "V13",
                                "severity": "ERROR",
                                "id": f"{c1.case_id} vs {c2.case_id}",
                                "message": f"Accidental near-duplicate for vendor {v1}: amounts ({amt1}, {amt2}) within {amt_diff_pct:.2f}% and dates ({date1_str}, {date2_str}) within {date_delta} days",
                                "fix": "Separate dates by at least 12 days or vary amounts by >0.5%",
                            })

                # V14: Invoice-number similarity trap
                if norm_no1 and norm_no2 and not is_intended_dup and not is_control:
                    sim = fuzz.ratio(norm_no1, norm_no2) / 100.0
                    if sim >= 0.85:
                        findings.append({
                            "code": "V14",
                            "severity": "ERROR",
                            "id": f"{c1.case_id} vs {c2.case_id}",
                            "message": f"Accidental invoice number similarity for vendor {v1}: '{raw_no1}' vs '{raw_no2}' similarity is {sim:.2f} >= 0.85",
                            "fix": "Use visibly different, non-sequential invoice numbers",
                        })

            # Across different vendors: V15
            elif v1 and v2 and v1 != v2:
                if raw_no1 and raw_no2 and raw_no1 == raw_no2 and not is_control:
                    findings.append({
                        "code": "V15",
                        "severity": "ERROR",
                        "id": f"{c1.case_id} vs {c2.case_id}",
                        "message": f"Same raw invoice number '{raw_no1}' used across different vendors ({v1} vs {v2}) without control_of relation",
                        "fix": "Invoice numbers may only collide across vendors if relation.type == 'control_of'",
                    })

    # V16: Content uniqueness (hash of canonical document JSON)
    # Allowed duplicates in content: resend_identical, rerender, rescan
    doc_hashes: Dict[str, str] = {}
    for c in case_list:
        doc_json = json.dumps(c.document.model_dump(), sort_keys=True)
        h = hashlib.sha256(doc_json.encode("utf-8")).hexdigest()
        sc = all_authored_scenarios.get(c.case_id)
        is_allowed_same_doc = (
            (sc and sc.mutation.name in ["resend_identical", "rerender"]) or
            (sc and sc.tag in ["dup_resend_identical", "dup_rescan", "dup_exact"]) or
            (c.byte_copy_of is not None)
        )

        if h in doc_hashes:
            other_id = doc_hashes[h]
            if not is_allowed_same_doc:
                findings.append({
                    "code": "V16",
                    "severity": "ERROR",
                    "id": f"{c.case_id} vs {other_id}",
                    "message": f"Identical document content hash for {c.case_id} and {other_id} without resend_identical/rerender",
                    "fix": "Ensure distinct document contents unless resend_identical or rerender",
                })
        else:
            doc_hashes[h] = c.case_id

    # V17: PO usage exclusivity
    po_usage: Dict[str, set[str]] = {}
    for sc in all_authored_scenarios.values():
        target_po = sc.po_id or (sc.invoice.po_reference if sc.invoice else None)
        if target_po:
            unit_id = sc.series.id if sc.series else sc.scenario_id
            po_usage.setdefault(target_po, set()).add(unit_id)

    for po_id, units in po_usage.items():
        if len(units) > 1:
            is_allowed = False
            for u in units:
                sc = all_authored_scenarios.get(u)
                if sc and (sc.mutation.name == "swap_po_ref" or sc.tag.startswith("burger_") or sc.tag == "happy_partial_delivery"):
                    is_allowed = True
                    break
            if not is_allowed:
                findings.append({
                    "code": "V17",
                    "severity": "ERROR",
                    "id": po_id,
                    "message": f"PO {po_id} is referenced across multiple distinct scenarios/series: {units}",
                    "fix": "A PO should only be consumed by one scenario or one series",
                })

    # V18: Series contiguous positions starting at 1, same family
    series_map: Dict[str, List[Any]] = {}
    for fam_name, fam in families.items():
        for sc in fam.scenarios:
            if sc.series:
                series_map.setdefault(sc.series.id, []).append((fam_name, sc))

    for s_id, members in series_map.items():
        fams = {m[0] for m in members}
        if len(fams) > 1:
            findings.append({
                "code": "V18",
                "severity": "ERROR",
                "id": s_id,
                "message": f"Series {s_id} has members across multiple families: {fams}",
                "fix": "All members of a series must belong to the same family",
            })
        positions = sorted(m[1].series.position for m in members)
        expected_positions = list(range(1, len(members) + 1))
        if positions != expected_positions:
            findings.append({
                "code": "V18",
                "severity": "ERROR",
                "id": s_id,
                "message": f"Series {s_id} positions {positions} are not contiguous starting at 1 (expected {expected_positions})",
                "fix": "Number series positions 1, 2, ... consecutively",
            })

    return findings
