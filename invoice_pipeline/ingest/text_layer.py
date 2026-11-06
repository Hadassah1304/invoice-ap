from __future__ import annotations

from typing import List, Optional, Tuple
import fitz
from invoice_pipeline.config import TextLayerConfig


def extract_pdf_text_layer(
    pdf_path: str, config: TextLayerConfig
) -> Tuple[Optional[str], bool, List[str], List[bool]]:
    """
    Extracts text layer from PDF using PyMuPDF per page.
    Returns (full_text, is_overall_valid, page_texts, per_page_valid_flags).
    """
    if not config.enabled:
        return None, False, [], []

    page_texts: List[str] = []
    page_valids: List[bool] = []

    try:
        with fitz.open(pdf_path) as doc:
            for i, p in enumerate(doc):
                t = p.get_text()
                page_texts.append(t)
                clean_t = t.strip()
                if len(clean_t) < config.min_chars:
                    page_valids.append(False)
                else:
                    alnum_count = sum(1 for c in clean_t if c.isalnum())
                    ratio = alnum_count / max(1, len(clean_t))
                    page_valids.append(ratio >= config.min_alnum_ratio)
    except Exception:
        return None, False, [], []

    overall_valid = all(page_valids) if page_valids else False
    formatted_pages = [f"--- PAGE {idx+1} ---\n{t.strip()}" for idx, t in enumerate(page_texts)]
    full_text = "\n\n".join(formatted_pages)

    return full_text, overall_valid, page_texts, page_valids
