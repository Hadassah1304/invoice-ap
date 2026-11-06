"""Finalize step: compute all derived numbers and build state.json and base documents.

02_PIPELINE_SCRIPTS.md Section 3:
1. Load files; reject unknown fields; reject any authored derived field (V02).
2. Resolve offset_days to ISO dates against REFERENCE_DATE.
3. Compute for each PO: line totals, subtotal, tax, total. Compute preload invoice totals and line totals.
   Compute qty_remaining = qty_ordered - sum(preload qty on that line). Remaining money = PO total minus preload totals.
4. Build each scenario's base document from its invoice block (or derive_from copy):
   resolve printed description (null -> PO item name), compute line totals, subtotal, tax total, grand total with money.py;
   vendor block from the vendor record (name, GSTIN, email = billing@<email_domain>, phone, address, bank).
   title = "TAX INVOICE", document_type = "invoice", tax_mode = "separate".
5. Assign run_order, file_stem = f"{family.lower()}{run_order:02d}_{tag}".
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from datagen.constants import REFERENCE_DATE_STR
from datagen.loader import LoadedBase, resolve_offset_date
from datagen.models import (
    AuthoredFamily,
    AuthoredPO,
    AuthoredScenario,
    AuthoredVendor,
    Document,
    DocumentFlags,
    DocumentLine,
    DocumentOmit,
    StateMeta,
    StateOutput,
    StatePO,
    StatePOLine,
    StatePreload,
    StatePreloadLine,
    StateVendor,
    VendorBlock,
)
from datagen.money import (
    compute_line_tax,
    compute_line_total,
    compute_totals,
    quantize_money,
    to_decimal,
)
from datagen.norm import normalize_invoice_number


class FinalizedState:
    def __init__(
        self,
        state_output: StateOutput,
        base_documents: Dict[str, Document],  # scenario_id -> base Document before mutation
        ordered_scenarios: List[Tuple[str, AuthoredScenario]],  # (family, scenario) in run_order
    ):
        self.state_output = state_output
        self.base_documents = base_documents
        self.ordered_scenarios = ordered_scenarios


def finalize_state(loaded: LoadedBase, seed: int = 42) -> FinalizedState:
    """Computes all derived numbers on POs, preloads, and scenarios."""
    core = loaded.core
    families = loaded.families

    vendors_by_id: Dict[str, AuthoredVendor] = {v.vendor_id: v for v in core.vendors}
    catalog_by_sku = {c.sku: c for c in core.catalog}

    # 1. State Vendors
    state_vendors = [
        StateVendor(
            vendor_id=v.vendor_id,
            name=v.name,
            aliases=v.aliases,
            gstin=v.gstin,
            email_domain=v.email_domain,
            phone=v.phone,
            address=v.address,
            approved=v.approved,
            bank_account=v.bank_account,
            owner_family=v.owner_family,
        )
        for v in sorted(core.vendors, key=lambda x: x.vendor_id)
    ]

    # Collect all POs and preloads across families
    all_authored_pos: List[Tuple[str, AuthoredPO]] = []
    all_authored_preloads: List[Tuple[str, Any]] = []
    all_authored_scenarios: List[Tuple[str, AuthoredScenario]] = []

    for fam_name in sorted(families.keys()):
        fam = families[fam_name]
        for po in fam.pos:
            all_authored_pos.append((fam_name, po))
        for pl in fam.ledger_preload:
            all_authored_preloads.append((fam_name, pl))
        for sc in fam.scenarios:
            all_authored_scenarios.append((fam_name, sc))

    # Preload map: po_id -> list of preload lines
    preload_by_po: Dict[str, List[Any]] = {}
    for _, pl in all_authored_preloads:
        preload_by_po.setdefault(pl.po_id, []).append(pl)

    # 2. Finalize POs and StatePOs
    state_pos: List[StatePO] = []
    po_remaining_money: Dict[str, Decimal] = {}
    po_remaining_qty_by_line: Dict[Tuple[str, int], int] = {}
    authored_pos_by_id: Dict[str, AuthoredPO] = {}

    for fam_name, po in sorted(all_authored_pos, key=lambda x: x[1].po_id):
        authored_pos_by_id[po.po_id] = po
        # compute lines
        state_lines: List[StatePOLine] = []
        po_line_tuples: List[Tuple[Decimal, Decimal]] = []

        # Find preloads for this PO
        pls = preload_by_po.get(po.po_id, [])

        for line in po.lines:
            lt = compute_line_total(line.qty_ordered, line.unit_price)
            tx = compute_line_tax(lt, line.tax_rate)
            po_line_tuples.append((lt, tx))

            # sum preload qty on that line
            pre_qty = sum(
                sum(l.qty for l in p.lines if l.po_line_no == line.line_no)
                for p in pls
            )
            rem_qty = line.qty_ordered - pre_qty
            po_remaining_qty_by_line[(po.po_id, line.line_no)] = rem_qty

            state_lines.append(
                StatePOLine(
                    line_no=line.line_no,
                    sku=line.sku,
                    item_name=line.item_name,
                    description=line.description,
                    uom=line.uom,
                    qty_ordered=line.qty_ordered,
                    qty_remaining=rem_qty,
                    unit_price=float(line.unit_price),
                    tax_rate=float(line.tax_rate),
                    line_total=float(lt),
                    embedding=None,
                )
            )

        subtotal, tax_total, total = compute_totals(po_line_tuples)

        # Preload totals on this PO
        preload_total_sum = Decimal("0.00")
        for p in pls:
            p_tuples = [(compute_line_total(l.qty, l.unit_price), Decimal("0.00")) for l in p.lines]
            p_sub, _, p_tot = compute_totals(p_tuples)
            preload_total_sum += p_tot

        po_remaining_money[po.po_id] = quantize_money(total - preload_total_sum)

        state_pos.append(
            StatePO(
                po_id=po.po_id,
                vendor_id=po.vendor_id,
                po_date=resolve_offset_date(po.po_date.offset_days),
                currency=po.currency,
                status=po.status,
                payment_terms_days=po.payment_terms_days,
                group=po.group,
                subtotal=float(subtotal),
                tax_total=float(tax_total),
                total=float(total),
                lines=state_lines,
            )
        )

    # 3. Finalize Preloads
    state_preloads: List[StatePreload] = []
    for fam_name, pl in sorted(all_authored_preloads, key=lambda x: x[1].preload_id):
        po = authored_pos_by_id[pl.po_id]
        po_lines_by_no = {l.line_no: l for l in po.lines}

        pl_lines: List[StatePreloadLine] = []
        pl_tuples: List[Tuple[Decimal, Decimal]] = []

        for line in pl.lines:
            lt = compute_line_total(line.qty, line.unit_price)
            # Find description from PO
            desc = po_lines_by_no[line.po_line_no].item_name if line.po_line_no in po_lines_by_no else ""
            pl_lines.append(
                StatePreloadLine(
                    po_line_no=line.po_line_no,
                    description=desc,
                    qty=line.qty,
                    unit_price=float(line.unit_price),
                    line_total=float(lt),
                )
            )
            pl_tuples.append((lt, Decimal("0.00")))

        subtotal, tax_total, total = compute_totals(pl_tuples)

        state_preloads.append(
            StatePreload(
                preload_id=pl.preload_id,
                po_id=pl.po_id,
                vendor_id=pl.vendor_id,
                invoice_no=pl.invoice_no,
                invoice_no_norm=normalize_invoice_number(pl.invoice_no),
                invoice_date=resolve_offset_date(pl.invoice_date.offset_days),
                currency=pl.currency,
                subtotal=float(subtotal),
                tax_total=float(tax_total),
                total=float(total),
                lines=pl_lines,
            )
        )

    # 4. Scenario Ordering (02_PIPELINE_SCRIPTS.md Section 7.1)
    # Group by series; singles and series are ordered by (family, series id or case id);
    # series members consecutive by position; any derive_from must run after its source.
    # We assign run_order 1..N deterministically.

    # First, separate scenarios into series groups and standalone
    series_groups: Dict[Tuple[str, str], List[Tuple[str, AuthoredScenario]]] = {}
    standalone_scenarios: List[Tuple[str, AuthoredScenario]] = []

    for fam_name, sc in all_authored_scenarios:
        if sc.series:
            series_groups.setdefault((fam_name, sc.series.id), []).append((fam_name, sc))
        else:
            standalone_scenarios.append((fam_name, sc))

    # Sort within each series group by series.position
    for key in series_groups:
        series_groups[key].sort(key=lambda x: x[1].series.position)

    # Combine into units for ordering: (family, sort_key, is_series, items)
    units = []
    for (fam, series_id), items in series_groups.items():
        units.append((fam, series_id, True, items))
    for fam, sc in standalone_scenarios:
        units.append((fam, sc.scenario_id, False, [(fam, sc)]))

    # Sort units by (family, sort_key)
    units.sort(key=lambda u: (u[0], u[1]))

    ordered_scenarios: List[Tuple[str, AuthoredScenario]] = []
    for u in units:
        ordered_scenarios.extend(u[3])

    # Ensure any derive_from comes after its source
    # If a derive_from appears before its target, do a topological pass
    scenario_order_index = {sc.scenario_id: i for i, (_, sc) in enumerate(ordered_scenarios)}
    needs_reorder = True
    passes = 0
    while needs_reorder and passes < 50:
        needs_reorder = False
        passes += 1
        for i, (_, sc) in enumerate(ordered_scenarios):
            if sc.derive_from:
                src_id = sc.derive_from.scenario_id
                src_idx = scenario_order_index.get(src_id)
                if src_idx is not None and src_idx > i:
                    # Move sc after src_idx
                    item = ordered_scenarios.pop(i)
                    ordered_scenarios.insert(src_idx, item)
                    scenario_order_index = {s.scenario_id: idx for idx, (_, s) in enumerate(ordered_scenarios)}
                    needs_reorder = True
                    break

    # 5. Build Base Documents
    # Clean document before mutation
    base_documents: Dict[str, Document] = {}

    for fam_name, sc in ordered_scenarios:
        if sc.derive_from:
            # Will be copied from source base document during compile
            continue

        inv = sc.invoice
        vendor = vendors_by_id.get(inv.vendor_id)
        po = authored_pos_by_id.get(inv.po_reference) if inv.po_reference else None
        po_lines_by_no = {l.line_no: l for l in po.lines} if po else {}

        # vendor block
        email = f"billing@{vendor.email_domain}" if (vendor and vendor.email_domain) else None
        v_block = VendorBlock(
            name=vendor.name if vendor else "Unknown",
            gstin=vendor.gstin if vendor else None,
            email=email,
            phone=vendor.phone if vendor else None,
            address=vendor.address if vendor else None,
            bank_account=vendor.bank_account if vendor else None,
        )

        doc_lines: List[DocumentLine] = []
        line_tuples: List[Tuple[Decimal, Decimal]] = []
        line_counter = 1

        for l in inv.lines:
            desc = l.description
            if desc is None and l.po_line_no and l.po_line_no in po_lines_by_no:
                desc = po_lines_by_no[l.po_line_no].item_name
            elif desc is None:
                desc = "Item"

            lt = compute_line_total(l.qty, l.unit_price)
            tx = compute_line_tax(lt, l.tax_rate)
            line_tuples.append((lt, tx))

            # Find uom from po line if available
            uom = po_lines_by_no[l.po_line_no].uom if (l.po_line_no and l.po_line_no in po_lines_by_no) else "pcs"

            doc_lines.append(
                DocumentLine(
                    line_no=line_counter,
                    description=desc,
                    uom=uom,
                    qty=l.qty,
                    unit_price=float(l.unit_price),
                    line_total=float(lt),
                    tax_rate=float(l.tax_rate),
                )
            )
            line_counter += 1

        for el in inv.extra_lines:
            lt = compute_line_total(el.qty, el.unit_price)
            tx = compute_line_tax(lt, el.tax_rate)
            line_tuples.append((lt, tx))
            doc_lines.append(
                DocumentLine(
                    line_no=line_counter,
                    description=el.description,
                    uom="pcs",
                    qty=el.qty,
                    unit_price=float(el.unit_price),
                    line_total=float(lt),
                    tax_rate=float(el.tax_rate),
                )
            )
            line_counter += 1

        subtotal, tax_total, grand_total = compute_totals(line_tuples)

        doc = Document(
            title="TAX INVOICE",
            document_type="invoice",
            vendor_block=v_block,
            invoice_number=inv.invoice_no,
            invoice_date=resolve_offset_date(inv.invoice_date.offset_days),
            due_date=None,
            po_reference=inv.po_reference,
            currency=inv.currency,
            tax_mode="separate",
            lines=doc_lines,
            subtotal=float(subtotal),
            tax_total=float(tax_total),
            grand_total=float(grand_total),
            omit=DocumentOmit(),
            flags=DocumentFlags(),
        )
        base_documents[sc.scenario_id] = doc

    state_output = StateOutput(
        meta=StateMeta(reference_date=REFERENCE_DATE_STR, seed=seed),
        vendors=state_vendors,
        catalog=sorted(core.catalog, key=lambda c: c.sku),
        purchase_orders=state_pos,
        ledger_preload=state_preloads,
    )

    return FinalizedState(
        state_output=state_output,
        base_documents=base_documents,
        ordered_scenarios=ordered_scenarios,
    )
