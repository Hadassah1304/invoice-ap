from __future__ import annotations

import sqlite3
from typing import Any, List, Optional, Tuple
from rapidfuzz import fuzz
from invoice_pipeline.config import MatchingConfig
from invoice_pipeline.matching.item_matcher import ItemMatcher
from invoice_pipeline.matching.scoring import score_candidate_po
from invoice_pipeline.models import (
    MatchMethodEnum,
    MatchResult,
    POCandidate,
    ReasonCodeEnum,
)
from invoice_pipeline.store.embeddings import Embedder
from invoice_pipeline.store.index import InMemoryItemIndex
from invoice_pipeline.store.repositories import (
    InvoiceRepo,
    ItemRepo,
    PORepo,
    VendorRepo,
)


class MatchingRouter:
    """Orchestrates Tier 1 (Explicit), Tier 2 (Vendor Inferred), and Tier 3 (Item Inferred)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        config: MatchingConfig,
        embedder: Optional[Embedder] = None,
        item_index: Optional[InMemoryItemIndex] = None,
        exclude_invoice_id: Optional[int] = None,
    ) -> None:
        self.conn = conn
        self.config = config
        self.embedder = embedder
        self.item_index = item_index
        self.exclude_invoice_id = exclude_invoice_id
        self.po_repo = PORepo(conn)
        self.item_repo = ItemRepo(conn)
        self.vendor_repo = VendorRepo(conn)
        self.inv_repo = InvoiceRepo(conn)
        self.item_matcher = ItemMatcher(config.line_match, embedder)

    def route_match(
        self,
        po_reference: Optional[str],
        resolved_vendor: Optional[dict],
        invoice_lines: List[Any],
        invoice_total: float,
        invoice_date: Optional[str],
        currency: str = "INR",
    ) -> Tuple[MatchResult, Optional[ReasonCodeEnum], Optional[str]]:
        # --- TIER 1: Explicit PO reference ---
        if po_reference:
            clean_po_id = po_reference.strip().upper()
            po = self.po_repo.get_by_id(clean_po_id)
            if not po:
                all_pos = self.po_repo.list_by_vendor(resolved_vendor["vendor_id"]) if resolved_vendor else []
                if not all_pos:
                    cur = self.conn.execute("SELECT po_id FROM purchase_orders LIMIT 50")
                    all_pos = [dict(r) for r in cur.fetchall()]
                suggestions = [
                    p["po_id"] for p in all_pos
                    if fuzz.ratio(clean_po_id, p["po_id"]) > 70
                ]
                msg = f"Referenced PO '{po_reference}' not found in procurement system."
                if suggestions:
                    msg += f" Did you mean: {', '.join(suggestions)}?"
                return MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT), ReasonCodeEnum.INVALID_PO_REF, msg

            # Vendor check
            if resolved_vendor and po["vendor_id"] != resolved_vendor["vendor_id"]:
                msg = f"PO {clean_po_id} belongs to vendor {po['vendor_id']}, but invoice resolved to {resolved_vendor['vendor_id']}"
                return MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT, selected_po=clean_po_id), ReasonCodeEnum.VENDOR_MISMATCH, msg

            # Status check
            if po["status"] in ("CLOSED", "CANCELLED"):
                return MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT, selected_po=clean_po_id), ReasonCodeEnum.PO_CLOSED, f"PO {clean_po_id} is {po['status']}"

            # Check remaining balance
            consumed = self.inv_repo.get_po_consumed_amount(
                clean_po_id, include_pending=True, exclude_invoice_id=self.exclude_invoice_id
            )
            if float(po["total"]) - consumed <= 0:
                return MatchResult(tier=1, method=MatchMethodEnum.EXPLICIT, selected_po=clean_po_id), ReasonCodeEnum.PO_CLOSED, f"PO {clean_po_id} has zero remaining balance"

            # Match lines
            po_items = self.item_repo.list_by_po(clean_po_id)
            line_matches = [
                self.item_matcher.match_line_to_po_items(l.line_no or idx + 1, l.description, po_items)
                for idx, l in enumerate(invoice_lines)
            ]
            candidate = score_candidate_po(
                po, po_items, invoice_lines, line_matches, invoice_total, consumed, invoice_date, self.config
            )

            res = MatchResult(
                tier=1,
                method=MatchMethodEnum.EXPLICIT,
                selected_po=clean_po_id,
                candidates=[candidate],
            )
            return res, None, None

        # --- TIER 2: Vendor Known, Inferred PO ---
        if resolved_vendor:
            vendor_id = resolved_vendor["vendor_id"]
            open_pos = self.po_repo.list_by_vendor(vendor_id, statuses=["OPEN", "PARTIAL"])
            
            eligible_pos = []
            for p in open_pos:
                if p.get("currency", "INR").upper() != currency.upper():
                    continue
                if invoice_date and p.get("po_date"):
                    if str(invoice_date) < str(p["po_date"]):
                        continue
                items = self.item_repo.list_by_po(p["po_id"])
                if any(float(it["qty_remaining"]) > 0 for it in items):
                    eligible_pos.append((p, items))

            if not eligible_pos:
                return (
                    MatchResult(tier=2, method=MatchMethodEnum.INFERRED_VENDOR),
                    ReasonCodeEnum.NO_MATCHING_PO,
                    f"No open eligible POs found for vendor {vendor_id}",
                )

            # Score each candidate
            scored_candidates: List[POCandidate] = []
            for p, p_items in eligible_pos:
                consumed = self.inv_repo.get_po_consumed_amount(
                    p["po_id"], include_pending=True, exclude_invoice_id=self.exclude_invoice_id
                )
                l_matches = [
                    self.item_matcher.match_line_to_po_items(l.line_no or idx + 1, l.description, p_items)
                    for idx, l in enumerate(invoice_lines)
                ]
                cand = score_candidate_po(
                    p, p_items, invoice_lines, l_matches, invoice_total, consumed, invoice_date, self.config
                )
                scored_candidates.append(cand)

            scored_candidates.sort(key=lambda c: c.score, reverse=True)

            top = scored_candidates[0]
            second_score = scored_candidates[1].score if len(scored_candidates) > 1 else 0.0
            margin = top.score - second_score

            min_score = self.config.tier2.min_score
            min_margin = self.config.tier2.min_margin

            if top.score >= min_score and margin >= min_margin:
                res = MatchResult(
                    tier=2,
                    method=MatchMethodEnum.INFERRED_VENDOR,
                    selected_po=top.po_id,
                    candidates=scored_candidates[: self.config.tier2.top_k],
                )
                return res, ReasonCodeEnum.INFERRED_MATCH, f"Inferred PO {top.po_id} with score {top.score:.2f} (margin {margin:.2f})"
            else:
                res = MatchResult(
                    tier=2,
                    method=MatchMethodEnum.INFERRED_VENDOR,
                    selected_po=None,
                    candidates=scored_candidates[: self.config.tier2.top_k],
                )
                return res, ReasonCodeEnum.AMBIGUOUS_PO, f"Ambiguous PO match for vendor {vendor_id}: top score {top.score:.2f}, margin {margin:.2f}"

        # --- TIER 3: No PO, No Vendor -> Search items across entire catalog ---
        if not self.item_index:
            return MatchResult(tier=3), ReasonCodeEnum.NO_MATCHING_PO, "No PO or vendor specified, and item index is not loaded"

        po_sets_per_line: List[set[str]] = []
        unmatched = []

        for idx, line in enumerate(invoice_lines):
            results = self.item_index.search(
                line.description,
                top_k=self.config.tier3.top_k_per_line,
                min_similarity=self.config.tier3.item_similarity_threshold,
            )
            matching_pos = set()
            for it, sim in results:
                po_price = float(it["unit_price"])
                if po_price > 0 and line.unit_price is not None:
                    diff_pct = abs(float(line.unit_price) - po_price) / po_price * 100.0
                    if diff_pct <= self.config.tier3.price_tolerance_pct:
                        matching_pos.add(it["po_id"])
            if matching_pos:
                po_sets_per_line.append(matching_pos)
            else:
                unmatched.append(line.description)

        if not po_sets_per_line:
            return (
                MatchResult(tier=3, method=MatchMethodEnum.INFERRED_ITEMS, unmatched_lines=unmatched),
                ReasonCodeEnum.NO_MATCHING_PO,
                "No open POs matched any invoice items",
            )

        intersection = set.intersection(*po_sets_per_line) if po_sets_per_line else set()

        if len(intersection) == 1:
            chosen_po_id = list(intersection)[0]
            po = self.po_repo.get_by_id(chosen_po_id)
            items = self.item_repo.list_by_po(chosen_po_id)
            consumed = self.inv_repo.get_po_consumed_amount(
                chosen_po_id, include_pending=True, exclude_invoice_id=self.exclude_invoice_id
            )
            l_matches = [
                self.item_matcher.match_line_to_po_items(l.line_no or i + 1, l.description, items)
                for i, l in enumerate(invoice_lines)
            ]
            cand = score_candidate_po(
                po, items, invoice_lines, l_matches, invoice_total, consumed, invoice_date, self.config
            )
            res = MatchResult(
                tier=3,
                method=MatchMethodEnum.INFERRED_ITEMS,
                selected_po=chosen_po_id,
                candidates=[cand],
                unmatched_lines=unmatched,
            )
            return res, ReasonCodeEnum.INFERRED_MATCH, f"Inferred PO {chosen_po_id} via item set intersection"

        # Check line coverage threshold
        candidate_pos = list(intersection) if intersection else list(set.union(*po_sets_per_line))
        scored = []
        for p_id in candidate_pos:
            po = self.po_repo.get_by_id(p_id)
            if not po:
                continue
            items = self.item_repo.list_by_po(p_id)
            consumed = self.inv_repo.get_po_consumed_amount(
                p_id, include_pending=True, exclude_invoice_id=self.exclude_invoice_id
            )
            l_matches = [
                self.item_matcher.match_line_to_po_items(l.line_no or i + 1, l.description, items)
                for i, l in enumerate(invoice_lines)
            ]
            cand = score_candidate_po(
                po, items, invoice_lines, l_matches, invoice_total, consumed, invoice_date, self.config
            )
            if cand.signals.line_coverage >= self.config.tier3.min_line_coverage_for_partial:
                scored.append(cand)

        if not scored:
            return (
                MatchResult(tier=3, method=MatchMethodEnum.INFERRED_ITEMS, unmatched_lines=unmatched),
                ReasonCodeEnum.NO_MATCHING_PO,
                f"Candidate POs did not satisfy minimum line coverage ({self.config.tier3.min_line_coverage_for_partial*100}%)",
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        res = MatchResult(
            tier=3,
            method=MatchMethodEnum.INFERRED_ITEMS,
            selected_po=None,
            candidates=scored[: self.config.tier3.top_k_candidates_to_user],
            unmatched_lines=unmatched,
        )
        return res, ReasonCodeEnum.AMBIGUOUS_PO, f"Multiple POs ({len(scored)}) match items"
