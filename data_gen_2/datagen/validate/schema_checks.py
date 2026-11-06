"""Schema and ID validator checks (V01-V05).

V01: JSON conforms to the model, no unknown fields.
V02: No authored derived field names.
V03: IDs unique and prefixed per the namespace (PO-<F>-, SC-<F>-, LP-<F>-).
V04: All references resolve (vendor, sku, po, po line, derive_from, relation).
V05: Money values have at most 2 decimals and are positive where required.
"""

from __future__ import annotations

from decimal import Decimal
import re
from typing import Any, Dict, List

from datagen.loader import LoadedBase
from datagen.money import to_decimal


def has_more_than_two_decimals(val: Any) -> bool:
    if val is None:
        return False
    d = to_decimal(val)
    # Check exponent
    parts = str(d).split(".")
    if len(parts) == 2 and len(parts[1]) > 2:
        return True
    return False


def validate_schemas_and_ids(loaded: LoadedBase) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    # Any errors during loading (V01, V02)
    findings.extend(loaded.load_errors)
    if not loaded.core:
        return findings

    core = loaded.core
    families = loaded.families

    # Sets for uniqueness and resolution
    vendor_ids = set()
    sku_ids = set()
    po_ids = set()
    scenario_ids = set()
    preload_ids = set()

    # V03: ID prefix patterns
    # vendor: V-<NAME>
    # catalog: SKU-<NNN>
    # PO: PO-<F>-<GROUP>[-<X>]
    # scenario: SC-<F>-<GROUP>-<NN>
    # preload: LP-<F>-<GROUP>-<N>
    po_regex = re.compile(r"^PO-([RBIN])-[A-Z0-9_\-]+$")
    sc_regex = re.compile(r"^SC-([RBIN])-[A-Z0-9_\-]+$")
    lp_regex = re.compile(r"^LP-([RBIN])-[A-Z0-9_\-]+$")

    # Catalog & Vendors
    for v in core.vendors:
        if v.vendor_id in vendor_ids:
            findings.append({
                "code": "V03",
                "severity": "ERROR",
                "id": v.vendor_id,
                "message": f"Duplicate vendor_id: {v.vendor_id}",
                "fix": "Ensure all vendor IDs are unique",
            })
        vendor_ids.add(v.vendor_id)
        if not v.vendor_id.startswith("V-"):
            findings.append({
                "code": "V03",
                "severity": "ERROR",
                "id": v.vendor_id,
                "message": f"Vendor ID '{v.vendor_id}' must start with 'V-'",
                "fix": f"Rename vendor ID {v.vendor_id} to V-...",
            })

    for c in core.catalog:
        if c.sku in sku_ids:
            findings.append({
                "code": "V03",
                "severity": "ERROR",
                "id": c.sku,
                "message": f"Duplicate SKU: {c.sku}",
                "fix": "Ensure all catalog SKUs are unique",
            })
        sku_ids.add(c.sku)
        if not c.sku.startswith("SKU-"):
            findings.append({
                "code": "V03",
                "severity": "ERROR",
                "id": c.sku,
                "message": f"SKU '{c.sku}' must start with 'SKU-'",
                "fix": f"Rename SKU {c.sku} to SKU-...",
            })
        # V05 money check on catalog
        if has_more_than_two_decimals(c.unit_price) or to_decimal(c.unit_price) < Decimal("0.00"):
            findings.append({
                "code": "V05",
                "severity": "ERROR",
                "id": c.sku,
                "message": f"Catalog {c.sku} unit_price {c.unit_price} invalid decimals or negative",
                "fix": "Format unit_price with at most 2 decimals and non-negative",
            })

    # POs
    po_lines_map: Dict[str, set[int]] = {}
    for fam_name, fam in families.items():
        for po in fam.pos:
            if po.po_id in po_ids:
                findings.append({
                    "code": "V03",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"Duplicate po_id: {po.po_id}",
                    "fix": "Ensure all PO IDs are unique",
                })
            po_ids.add(po.po_id)

            m = po_regex.match(po.po_id)
            if not m or m.group(1) != fam_name:
                findings.append({
                    "code": "V03",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO ID '{po.po_id}' does not match namespace PO-{fam_name}-*",
                    "fix": f"Rename PO to start with PO-{fam_name}-",
                })

            # V04 vendor check
            if po.vendor_id not in vendor_ids:
                findings.append({
                    "code": "V04",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} references unknown vendor {po.vendor_id}",
                    "fix": f"Add {po.vendor_id} to core.json or fix reference",
                })

            po_lines_map[po.po_id] = set()
            for l in po.lines:
                po_lines_map[po.po_id].add(l.line_no)
                # V04 SKU check
                if l.sku not in sku_ids:
                    findings.append({
                        "code": "V04",
                        "severity": "ERROR",
                        "id": f"{po.po_id} line {l.line_no}",
                        "message": f"PO {po.po_id} references unknown SKU {l.sku}",
                        "fix": f"Add {l.sku} to core.json or fix line SKU",
                    })
                # V05 check
                if has_more_than_two_decimals(l.unit_price) or to_decimal(l.unit_price) < Decimal("0.00"):
                    findings.append({
                        "code": "V05",
                        "severity": "ERROR",
                        "id": f"{po.po_id} line {l.line_no}",
                        "message": f"PO {po.po_id} line unit_price {l.unit_price} invalid decimals or negative",
                        "fix": "Format unit_price with at most 2 decimals and non-negative",
                    })

    # Preloads
    for fam_name, fam in families.items():
        for pl in fam.ledger_preload:
            if pl.preload_id in preload_ids:
                findings.append({
                    "code": "V03",
                    "severity": "ERROR",
                    "id": pl.preload_id,
                    "message": f"Duplicate preload_id: {pl.preload_id}",
                    "fix": "Ensure all preload IDs are unique",
                })
            preload_ids.add(pl.preload_id)

            m = lp_regex.match(pl.preload_id)
            if not m or m.group(1) != fam_name:
                findings.append({
                    "code": "V03",
                    "severity": "ERROR",
                    "id": pl.preload_id,
                    "message": f"Preload ID '{pl.preload_id}' does not match namespace LP-{fam_name}-*",
                    "fix": f"Rename preload to start with LP-{fam_name}-",
                })

            # V04 checks
            if pl.vendor_id not in vendor_ids:
                findings.append({
                    "code": "V04",
                    "severity": "ERROR",
                    "id": pl.preload_id,
                    "message": f"Preload {pl.preload_id} references unknown vendor {pl.vendor_id}",
                    "fix": f"Add {pl.vendor_id} to core.json or fix reference",
                })
            if pl.po_id not in po_ids:
                findings.append({
                    "code": "V04",
                    "severity": "ERROR",
                    "id": pl.preload_id,
                    "message": f"Preload {pl.preload_id} references unknown PO {pl.po_id}",
                    "fix": f"Define {pl.po_id} in family_{fam_name}.json or fix reference",
                })
            else:
                for l in pl.lines:
                    if l.po_line_no not in po_lines_map.get(pl.po_id, set()):
                        findings.append({
                            "code": "V04",
                            "severity": "ERROR",
                            "id": pl.preload_id,
                            "message": f"Preload {pl.preload_id} references unknown PO line {l.po_line_no} on {pl.po_id}",
                            "fix": f"Ensure line_no {l.po_line_no} exists on {pl.po_id}",
                        })
                    if has_more_than_two_decimals(l.unit_price) or to_decimal(l.unit_price) < Decimal("0.00"):
                        findings.append({
                            "code": "V05",
                            "severity": "ERROR",
                            "id": pl.preload_id,
                            "message": f"Preload {pl.preload_id} unit_price {l.unit_price} invalid decimals or negative",
                            "fix": "Format unit_price with at most 2 decimals and non-negative",
                        })

    # Scenarios
    for fam_name, fam in families.items():
        for sc in fam.scenarios:
            if sc.scenario_id in scenario_ids:
                findings.append({
                    "code": "V03",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"Duplicate scenario_id: {sc.scenario_id}",
                    "fix": "Ensure all scenario IDs are unique",
                })
            scenario_ids.add(sc.scenario_id)

            m = sc_regex.match(sc.scenario_id)
            if not m or m.group(1) != fam_name:
                findings.append({
                    "code": "V03",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"Scenario ID '{sc.scenario_id}' does not match namespace SC-{fam_name}-*",
                    "fix": f"Rename scenario to start with SC-{fam_name}-",
                })

            # Ground truth po_id if set
            if sc.po_id and sc.po_id not in po_ids:
                findings.append({
                    "code": "V04",
                    "severity": "ERROR",
                    "id": sc.scenario_id,
                    "message": f"Scenario {sc.scenario_id} ground truth po_id '{sc.po_id}' not found",
                    "fix": f"Define PO {sc.po_id} or fix scenario.po_id",
                })

            # Derive_from reference
            if sc.derive_from:
                src_id = sc.derive_from.scenario_id
                if not any(s.scenario_id == src_id for f in families.values() for s in f.scenarios):
                    findings.append({
                        "code": "V04",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"derive_from scenario '{src_id}' not found",
                        "fix": f"Ensure source scenario {src_id} exists",
                    })

            # Relation scenario_id reference
            if sc.relation and sc.relation.scenario_id:
                rel_id = sc.relation.scenario_id
                if not any(s.scenario_id == rel_id for f in families.values() for s in f.scenarios):
                    findings.append({
                        "code": "V04",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"relation.scenario_id '{rel_id}' not found",
                        "fix": f"Ensure relation scenario {rel_id} exists",
                    })

            # Invoice block
            if sc.invoice:
                inv = sc.invoice
                if inv.vendor_id not in vendor_ids:
                    findings.append({
                        "code": "V04",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"Invoice references unknown vendor {inv.vendor_id}",
                        "fix": f"Define {inv.vendor_id} in core.json or fix reference",
                    })
                if inv.po_reference and inv.po_reference not in po_ids and sc.mutation.name != "swap_po_ref":
                    # Note: if mutation is po_typo, po_reference starts as valid PO id
                    findings.append({
                        "code": "V04",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"Invoice po_reference '{inv.po_reference}' not found in POs",
                        "fix": f"Define {inv.po_reference} or fix po_reference",
                    })
                for l in inv.lines:
                    if l.po_line_no and inv.po_reference and inv.po_reference in po_lines_map:
                        if l.po_line_no not in po_lines_map[inv.po_reference]:
                            findings.append({
                                "code": "V04",
                                "severity": "ERROR",
                                "id": sc.scenario_id,
                                "message": f"Invoice line references non-existent po_line_no {l.po_line_no} on {inv.po_reference}",
                                "fix": f"Align po_line_no with lines on {inv.po_reference}",
                            })
                    if has_more_than_two_decimals(l.unit_price) or to_decimal(l.unit_price) < Decimal("0.00"):
                        findings.append({
                            "code": "V05",
                            "severity": "ERROR",
                            "id": sc.scenario_id,
                            "message": f"Invoice line unit_price {l.unit_price} invalid decimals or negative",
                            "fix": "Format unit_price with at most 2 decimals and non-negative",
                        })

    return findings
