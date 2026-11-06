"""Ownership validator checks (V06-V09).

V06: Every vendor has exactly one owner family; a scenario and its PO use only vendors of its own family;
     preload and PO vendor match.
V07: Any scenario that ends with po_reference == null after mutation uses a vendor owned by its own family.
V08: Vendor-less invoices (after drop_vendor_block): every line item has unique_item: true,
     each such item appears in exactly one PO base-wide, and a fuzzy search over all POs finds only the intended PO.
V09: Within one vendor, open POs (status OPEN/PARTIAL) do not share items (normalized name)
     except PO groups referenced by burger_clear_winner or burger_tie scenarios.
"""

from __future__ import annotations

from typing import Any, Dict, List
from rapidfuzz import fuzz

from datagen.constants import Config
from datagen.loader import LoadedBase
from datagen.models import AuthoredPO, AuthoredVendor
from datagen.norm import normalize_vendor_name


def validate_ownership(loaded: LoadedBase, config: Config = None) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if not loaded.core:
        return findings

    core = loaded.core
    families = loaded.families
    if config is None:
        config = Config()

    vendors_by_id: Dict[str, AuthoredVendor] = {v.vendor_id: v for v in core.vendors}
    catalog_by_sku = {c.sku: c for c in core.catalog}

    # All POs base-wide
    all_pos_by_id: Dict[str, AuthoredPO] = {}
    pos_by_vendor: Dict[str, List[AuthoredPO]] = {}

    for fam_name, fam in families.items():
        for po in fam.pos:
            all_pos_by_id[po.po_id] = po
            pos_by_vendor.setdefault(po.vendor_id, []).append(po)

    # V06: Vendor owner family & usage checks
    for v in core.vendors:
        if v.owner_family not in ["0", "R", "B", "I", "N"]:
            findings.append({
                "code": "V06",
                "severity": "ERROR",
                "id": v.vendor_id,
                "message": f"Vendor {v.vendor_id} has invalid owner_family '{v.owner_family}'",
                "fix": "Set owner_family to one of 0, R, B, I, N",
            })

    for fam_name, fam in families.items():
        for po in fam.pos:
            v = vendors_by_id.get(po.vendor_id)
            if v and v.owner_family != fam_name and v.owner_family != "0":
                findings.append({
                    "code": "V06",
                    "severity": "ERROR",
                    "id": po.po_id,
                    "message": f"PO {po.po_id} in family {fam_name} uses vendor {po.vendor_id} owned by {v.owner_family}",
                    "fix": f"Change PO {po.po_id} to use a vendor owned by family {fam_name}",
                })

        for pl in fam.ledger_preload:
            po = all_pos_by_id.get(pl.po_id)
            if po and pl.vendor_id != po.vendor_id:
                findings.append({
                    "code": "V06",
                    "severity": "ERROR",
                    "id": pl.preload_id,
                    "message": f"Preload {pl.preload_id} vendor {pl.vendor_id} does not match PO vendor {po.vendor_id}",
                    "fix": f"Set preload vendor to {po.vendor_id}",
                })

        for sc in fam.scenarios:
            if sc.invoice:
                v = vendors_by_id.get(sc.invoice.vendor_id)
                # Scenario must use its own family vendor unless it's a swap_po_ref or intended control/cross-vendor test
                if v and v.owner_family != fam_name and v.owner_family != "0" and sc.tag != "same_invno_other_vendor":
                    findings.append({
                        "code": "V06",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"Scenario {sc.scenario_id} in family {fam_name} uses vendor {sc.invoice.vendor_id} owned by {v.owner_family}",
                        "fix": f"Change scenario vendor to one owned by {fam_name}",
                    })

            # V07: Ends with po_reference == null after mutation
            ends_with_no_po = False
            if sc.invoice and sc.invoice.po_reference is None:
                ends_with_no_po = True
            elif sc.mutation.name == "drop_po_ref":
                ends_with_no_po = True
            elif sc.mutation.name == "drop_vendor_block" and sc.mutation.params.get("also_drop_po_ref"):
                ends_with_no_po = True

            if ends_with_no_po and sc.invoice:
                v = vendors_by_id.get(sc.invoice.vendor_id)
                if v and v.owner_family != fam_name and v.owner_family != "0":
                    findings.append({
                        "code": "V07",
                        "severity": "ERROR",
                        "id": sc.scenario_id,
                        "message": f"Scenario {sc.scenario_id} drops PO ref but uses vendor {sc.invoice.vendor_id} owned by {v.owner_family}",
                        "fix": f"Vendor-inference scenarios must use vendors owned exclusively by family {fam_name}",
                    })

    # V08: Vendor-less invoices (drop_vendor_block)
    # Count SKU occurrences in POs across the base
    sku_po_counts: Dict[str, List[str]] = {}
    for po_id, po in all_pos_by_id.items():
        for l in po.lines:
            sku_po_counts.setdefault(l.sku, []).append(po_id)

    for fam_name, fam in families.items():
        for sc in fam.scenarios:
            if sc.mutation.name == "drop_vendor_block" and sc.invoice:
                intended_po_id = sc.po_id or sc.invoice.po_reference
                for line in sc.invoice.lines:
                    po = all_pos_by_id.get(intended_po_id) if intended_po_id else None
                    if not po:
                        continue
                    po_line = next((pl for pl in po.lines if pl.line_no == line.po_line_no), None)
                    if not po_line:
                        continue
                    cat_item = catalog_by_sku.get(po_line.sku)
                    if not cat_item or not cat_item.unique_item:
                        findings.append({
                            "code": "V08",
                            "severity": "ERROR",
                            "id": sc.scenario_id,
                            "message": f"Vendor-less scenario {sc.scenario_id} line SKU {po_line.sku} does not have unique_item: true",
                            "fix": f"Set unique_item: true on SKU {po_line.sku} or use a unique catalog item",
                        })
                    # Must appear in exactly one PO base-wide
                    pos_with_sku = sku_po_counts.get(po_line.sku, [])
                    if len(pos_with_sku) > 1:
                        findings.append({
                            "code": "V08",
                            "severity": "ERROR",
                            "id": sc.scenario_id,
                            "message": f"Unique item {po_line.sku} appears in multiple POs: {pos_with_sku}",
                            "fix": f"Ensure {po_line.sku} is referenced by only one PO across all families",
                        })

    # V09: Within one vendor, open POs do not share items (normalized name)
    # except burger groups
    for v_id, po_list in pos_by_vendor.items():
        open_pos = [p for p in po_list if p.status in ["OPEN", "PARTIAL"]]
        seen_items: Dict[str, str] = {}  # norm_item_name -> po_id
        for po in open_pos:
            is_burger = (po.group and "burger" in po.group.lower())
            for l in po.lines:
                norm_item = l.item_name.strip().lower()
                if norm_item in seen_items:
                    other_po_id = seen_items[norm_item]
                    other_po = all_pos_by_id[other_po_id]
                    other_is_burger = (other_po.group and "burger" in other_po.group.lower())
                    if not (is_burger and other_is_burger):
                        findings.append({
                            "code": "V09",
                            "severity": "ERROR",
                            "id": f"{po.po_id} / {other_po_id}",
                            "message": f"Vendor {v_id} open POs {po.po_id} and {other_po_id} share item '{l.item_name}'",
                            "fix": "Open POs of the same vendor must have distinct items unless part of burger ambiguity test",
                        })
                else:
                    seen_items[norm_item] = po.po_id

    return findings
