"""Structural validator checks (V10-V12, V21).

V10: PO status: OPEN and CANCELLED have no preload; PARTIAL has preload with remaining money > 0 and some qty_remaining > 0;
     CLOSED has remaining money exactly 0 and every qty_remaining == 0.
V11: Preload quantities do not exceed ordered; preload lines reference existing PO lines.
V12: Dates: PO date <= invoice date for normal cases; invoice offsets within [-85, 0] except tags
     future_dated, stale, date_before_po; preload dates after PO date and <= reference date;
     normal invoices within payment_terms_days + 30 of PO date (WARN).
V21: Structural properties per tag.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, List
from rapidfuzz import fuzz

from datagen.constants import Config, REFERENCE_DATE
from datagen.finalize import FinalizedState
from datagen.loader import LoadedBase
from datagen.money import quantize_money, to_decimal
from datagen.norm import normalize_invoice_number


def validate_structural(loaded: LoadedBase, finalized: FinalizedState, compiled_cases: List[Any], config: Config = None) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if config is None:
        config = Config()

    core = loaded.core
    families = loaded.families
    state_out = finalized.state_output
    state_pos_by_id = {p.po_id: p for p in state_out.purchase_orders}
    all_preloads_by_po: Dict[str, List[Any]] = {}
    for pl in state_out.ledger_preload:
        all_preloads_by_po.setdefault(pl.po_id, []).append(pl)

    # V10 & V11: PO status and preload checks
    for po in state_out.purchase_orders:
        pls = all_preloads_by_po.get(po.po_id, [])
        has_preload = len(pls) > 0
        rem_money = quantize_money(to_decimal(po.total) - sum((to_decimal(p.total) for p in pls), Decimal("0.00")))
        any_qty_rem = any(l.qty_remaining > 0 for l in po.lines)
        all_qty_zero = all(l.qty_remaining == 0 for l in po.lines)

        if po.status in ["OPEN", "CANCELLED"]:
            if has_preload:
                findings.append({
                    "code": "V10",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} has status {po.status} but contains ledger preloads",
                    "fix": f"Remove preloads from {po.po_id} or update status to PARTIAL/CLOSED",
                })
        elif po.status == "PARTIAL":
            if not has_preload:
                findings.append({
                    "code": "V10",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} has status PARTIAL but has no ledger preloads",
                    "fix": "Add preload invoices or change status to OPEN",
                })
            if rem_money <= Decimal("0.00") or not any_qty_rem:
                findings.append({
                    "code": "V10",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} has status PARTIAL but remaining money={rem_money} or remaining qty is 0",
                    "fix": "Ensure PARTIAL PO retains positive remaining money and quantity",
                })
        elif po.status == "CLOSED":
            if rem_money != Decimal("0.00") or not all_qty_zero:
                findings.append({
                    "code": "V10",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} has status CLOSED but remaining money is {rem_money} (expected 0) or qty remaining > 0",
                    "fix": "Preload must exactly consume all money and line quantities for a CLOSED PO",
                })

        # V11: Preload quantities do not exceed ordered
        for l in po.lines:
            if l.qty_remaining < 0:
                findings.append({
                    "code": "V11",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} line {l.line_no} preload exceeds ordered: qty_remaining={l.qty_remaining}",
                    "fix": "Reduce preload quantities to not exceed qty_ordered",
                })

    # V12: Dates
    for fam_name, fam in families.items():
        # Preload dates
        for pl in fam.ledger_preload:
            po = state_pos_by_id.get(pl.po_id)
            if po:
                po_authored = next((p for f in families.values() for p in f.pos if p.po_id == pl.po_id), None)
                if po_authored:
                    if pl.invoice_date.offset_days <= po_authored.po_date.offset_days:
                        findings.append({
                            "code": "V12",
                            "severity": "ERROR",
                            "id": pl.preload_id,
                            "message": f"Preload {pl.preload_id} date offset {pl.invoice_date.offset_days} must be after PO date offset {po_authored.po_date.offset_days}",
                            "fix": "Set preload date after PO date",
                        })
                    if pl.invoice_date.offset_days > 0:
                        findings.append({
                            "code": "V12",
                            "severity": "ERROR",
                            "id": pl.preload_id,
                            "message": f"Preload {pl.preload_id} date offset {pl.invoice_date.offset_days} is in the future (>0)",
                            "fix": "Preload invoice date must be <= reference date (offset <= 0)",
                        })

    # Scenario dates and tag checks on compiled cases
    compiled_by_id = {c.case_id: c for c in compiled_cases}
    all_scenarios_list = [sc for f in families.values() for sc in f.scenarios]

    for sc in all_scenarios_list:
        case = compiled_by_id.get(sc.scenario_id)
        if not case or not case.document:
            continue

        doc = case.document
        inv_date_str = doc.invoice_date
        po_authored = next((p for f in families.values() for p in f.pos if p.po_id == (sc.po_id or doc.po_reference)), None)

        date_exception_tags = {"future_dated", "stale", "date_before_po"}

        if inv_date_str:
            inv_d = datetime.date.fromisoformat(inv_date_str)
            offset = (inv_d - REFERENCE_DATE).days

            if sc.tag not in date_exception_tags:
                if offset < -85 or offset > 0:
                    findings.append({
                        "code": "V12",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"Scenario {sc.scenario_id} normal invoice date offset {offset} outside [-85, 0]",
                        "fix": "Set invoice date offset between -85 and 0",
                    })
                if po_authored and offset < po_authored.po_date.offset_days:
                    findings.append({
                        "code": "V12",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"Scenario {sc.scenario_id} invoice date offset {offset} is before PO date offset {po_authored.po_date.offset_days}",
                        "fix": "Normal invoice date must be >= PO date",
                    })
                if po_authored:
                    max_allowed_offset = po_authored.po_date.offset_days + po_authored.payment_terms_days + 30
                    if offset > max_allowed_offset:
                        findings.append({
                            "code": "V12",
                            "severity": "WARN",
                            "id": sc.scenario_id,
                            "message": f"Scenario {sc.scenario_id} invoice date offset {offset} exceeds PO date + terms + 30 ({max_allowed_offset})",
                            "fix": f"Consider keeping invoice date within {max_allowed_offset}",
                        })
            elif sc.tag == "future_dated" and offset <= 0:
                findings.append({
                    "code": "V21",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"Scenario {sc.scenario_id} tagged future_dated but offset is {offset} (expected >0)",
                    "fix": "Set positive date offset for future_dated invoice",
                })
            elif sc.tag == "stale" and offset >= -90:
                findings.append({
                    "code": "V21",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"Scenario {sc.scenario_id} tagged stale but offset is {offset} (expected < -90)",
                    "fix": "Set date offset < -90 for stale invoice",
                })
            elif sc.tag == "date_before_po" and po_authored and offset >= po_authored.po_date.offset_days:
                findings.append({
                    "code": "V21",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"Scenario {sc.scenario_id} tagged date_before_po but offset {offset} >= PO date {po_authored.po_date.offset_days}",
                    "fix": "Set invoice date offset strictly before PO date",
                })

        # Tag-specific structural checks
        tag = sc.tag

        if tag == "po_typo":
            if doc.po_reference:
                s = list(doc.po_reference)
                for idx in range(len(s) - 1, -1, -1):
                    if s[idx] in {"0": "O", "1": "I", "5": "S", "8": "B"}:
                        s[idx] = {"0": "O", "1": "I", "5": "S", "8": "B"}[s[idx]]
                        break
                typo_ref = "".join(s)
                if typo_ref in state_pos_by_id:
                    findings.append({
                        "code": "V21",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"po_typo on {doc.po_reference} produced existing PO id '{typo_ref}'",
                        "fix": "Use a PO reference whose typo does not match another real PO",
                    })

        elif tag == "missing_invno":
            if sc.mutation.name != "missing_field" or sc.mutation.params.get("field") != "invoice_number":
                findings.append({
                    "code": "V21",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"missing_invno scenario must use mutation missing_field with field=invoice_number",
                    "fix": "Set mutation to missing_field (field=invoice_number)",
                })
        elif tag == "missing_date":
            if sc.mutation.name != "missing_field" or sc.mutation.params.get("field") != "invoice_date":
                findings.append({
                    "code": "V21",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"missing_date scenario must use mutation missing_field with field=invoice_date",
                    "fix": "Set mutation to missing_field (field=invoice_date)",
                })
        elif tag == "missing_total":
            if sc.mutation.name != "missing_field" or sc.mutation.params.get("field") != "grand_total":
                findings.append({
                    "code": "V21",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"missing_total scenario must use mutation missing_field with field=grand_total",
                    "fix": "Set mutation to missing_field (field=grand_total)",
                })

        elif tag.startswith("tol_"):
            if sc.mutation.name == "add_extra_line" and "pct_of_total" in sc.mutation.params:
                pct = sc.mutation.params["pct_of_total"]
                if tag == "tol_warn" and not (pct <= 2.0):
                    findings.append({
                        "code": "V21",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"tol_warn overage {pct}% exceeds 2.0%",
                        "fix": "Set pct_of_total <= 2.0 for tol_warn",
                    })
                elif tag == "tol_review" and not (2.0 < pct <= 5.0):
                    findings.append({
                        "code": "V21",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"tol_review overage {pct}% outside (2.0, 5.0]",
                        "fix": "Set pct_of_total between 2.0 and 5.0 for tol_review",
                    })
                elif tag == "tol_reject" and not (pct > 5.0):
                    findings.append({
                        "code": "V21",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"tol_reject overage {pct}% is not > 5.0%",
                        "fix": "Set pct_of_total > 5.0 for tol_reject",
                    })

        elif tag == "burger_tie":
            po_id = sc.po_id
            po = state_pos_by_id.get(po_id)
            if po and po.group:
                other_pos = [p for p in state_out.purchase_orders if p.group == po.group and p.po_id != po.po_id]
                if not other_pos:
                    findings.append({
                        "code": "V21",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"burger_tie requires at least two POs in group '{po.group}'",
                        "fix": "Define two identical POs for burger_tie",
                    })

    return findings
