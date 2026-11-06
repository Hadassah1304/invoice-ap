from __future__ import annotations

import re
from typing import List, Optional, Set
import numpy as np
from rapidfuzz import fuzz
from invoice_pipeline.config import LineMatchConfig
from invoice_pipeline.models import LineMatchDetail
from invoice_pipeline.store.embeddings import Embedder


def _extract_tokens_and_numbers(text: str) -> tuple[Set[str], Set[str]]:
    """Extract alpha tokens and numeric tokens separately (e.g. '150g' -> '150', 'g')."""
    clean = re.sub(r"([0-9]+)([a-zA-Z]+)", r"\1 \2", text.lower())
    tokens = set(re.findall(r"\b[a-z]+\b", clean))
    numbers = set(re.findall(r"\b[0-9]+(?:\.[0-9]+)?\b", clean))
    return tokens, numbers


def _has_spec_conflict(inv_text: str, po_text: str) -> Optional[str]:
    """Universal spec guard: checks contradictory numbers and units (e.g. 500ml vs 1L, 80gsm vs 70gsm)."""
    inv_toks, inv_nums = _extract_tokens_and_numbers(inv_text)
    po_toks, po_nums = _extract_tokens_and_numbers(po_text)

    # Number conflict (e.g. 80 vs 70, 500 vs 1)
    if inv_nums and po_nums and not (inv_nums & po_nums):
        return f"Specification number mismatch ({inv_nums} vs {po_nums})"

    # Key unit or food contradictions
    contradictions = [
        ("veg", "chicken"), ("veg", "egg"), ("veg", "fish"), ("veg", "mutton"),
        ("500ml", "1l"), ("80gsm", "70gsm")
    ]
    for a, b in contradictions:
        if (a in inv_toks and b in po_toks) or (b in inv_toks and a in po_toks):
            return f"Contradictory token specifications ({a} vs {b})"

    return None


class ItemMatcher:
    """Matches an invoice line description to items of a specific PO with universal guards."""

    def __init__(self, config: LineMatchConfig, embedder: Optional[Embedder] = None) -> None:
        self.config = config
        self.embedder = embedder

    def match_line_to_po_items(
        self,
        invoice_line_no: int,
        invoice_desc: str,
        po_items: List[dict],
    ) -> LineMatchDetail:
        inv_clean = invoice_desc.strip().lower()

        # 1. Exact normalized name match
        for it in po_items:
            po_name_clean = it["item_name"].strip().lower()
            if inv_clean == po_name_clean:
                conflict = _has_spec_conflict(invoice_desc, f"{it['item_name']} {it.get('description') or ''}")
                if not conflict:
                    return LineMatchDetail(
                        invoice_line_no=invoice_line_no,
                        invoice_description=invoice_desc,
                        po_item_row_id=it["row_id"],
                        po_item_name=it["item_name"],
                        match_method="exact",
                        score=1.0,
                        notes=["Exact normalized name match"],
                    )

        # 2. Fuzzy match (rapidfuzz token_set_ratio)
        best_fuzzy_score = 0.0
        best_fuzzy_item = None
        for it in po_items:
            full_po_desc = f"{it['item_name']} {it.get('description') or ''}".strip()
            score = fuzz.token_set_ratio(invoice_desc, full_po_desc)
            if score > best_fuzzy_score:
                best_fuzzy_score = score
                best_fuzzy_item = it

        if best_fuzzy_score >= self.config.fuzzy_threshold and best_fuzzy_item:
            full_desc = f"{best_fuzzy_item['item_name']} {best_fuzzy_item.get('description') or ''}"
            conflict = _has_spec_conflict(invoice_desc, full_desc)
            if conflict:
                return LineMatchDetail(
                    invoice_line_no=invoice_line_no,
                    invoice_description=invoice_desc,
                    po_item_row_id=None,
                    match_method="none",
                    score=best_fuzzy_score / 100.0,
                    notes=[f"Fuzzy match rejected: {conflict}"],
                )

            return LineMatchDetail(
                invoice_line_no=invoice_line_no,
                invoice_description=invoice_desc,
                po_item_row_id=best_fuzzy_item["row_id"],
                po_item_name=best_fuzzy_item["item_name"],
                match_method="fuzzy",
                score=best_fuzzy_score / 100.0,
                notes=[f"Fuzzy match score {best_fuzzy_score:.1f}%"],
            )

        # 3. Embedding cosine match if enabled
        if self.config.use_embeddings and self.embedder and po_items:
            inv_emb = self.embedder.embed_text(invoice_desc)
            best_emb_score = -1.0
            best_emb_item = None
            for it in po_items:
                blob = it.get("embedding")
                if blob is not None:
                    if isinstance(blob, (bytes, bytearray)):
                        it_emb = np.frombuffer(blob, dtype=np.float32)
                    elif isinstance(blob, np.ndarray):
                        it_emb = blob
                    else:
                        it_emb = self.embedder.embed_text(f"{it['item_name']} {it.get('description') or ''}")
                else:
                    it_emb = self.embedder.embed_text(f"{it['item_name']} {it.get('description') or ''}")

                sim = float(np.dot(inv_emb, it_emb))
                if sim > best_emb_score:
                    best_emb_score = sim
                    best_emb_item = it

            if best_emb_score >= 0.70 and best_emb_item:
                full_desc = f"{best_emb_item['item_name']} {best_emb_item.get('description') or ''}"
                conflict = _has_spec_conflict(invoice_desc, full_desc)
                if conflict:
                    return LineMatchDetail(
                        invoice_line_no=invoice_line_no,
                        invoice_description=invoice_desc,
                        po_item_row_id=None,
                        match_method="none",
                        score=best_emb_score,
                        notes=[f"Embedding rejected: {conflict}"],
                    )

                return LineMatchDetail(
                    invoice_line_no=invoice_line_no,
                    invoice_description=invoice_desc,
                    po_item_row_id=best_emb_item["row_id"],
                    po_item_name=best_emb_item["item_name"],
                    match_method="embedding",
                    score=best_emb_score,
                    notes=[f"Embedding cosine match {best_emb_score:.2f}"],
                )

        return LineMatchDetail(
            invoice_line_no=invoice_line_no,
            invoice_description=invoice_desc,
            po_item_row_id=None,
            match_method="none",
            score=0.0,
            notes=["No matching PO item found"],
        )
