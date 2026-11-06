from __future__ import annotations

import sqlite3
from typing import List, Tuple
import numpy as np
from invoice_pipeline.store.embeddings import Embedder
from invoice_pipeline.store.repositories import ItemRepo


class InMemoryItemIndex:
    """Keeps all active PO items in memory with their embeddings for fast vector search."""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.row_ids: List[int] = []
        self.po_ids: List[str] = []
        self.items: List[dict] = []
        self.matrix: Optional[np.ndarray] = None

    def build_from_db(self, conn: sqlite3.Connection) -> None:
        item_repo = ItemRepo(conn)
        rows = item_repo.list_all_open()

        self.row_ids = []
        self.po_ids = []
        self.items = []
        embeddings_list = []

        missing_texts = []
        missing_indices = []

        for i, row in enumerate(rows):
            self.row_ids.append(row["row_id"])
            self.po_ids.append(row["po_id"])
            self.items.append(row)

            blob = row["embedding"]
            if blob:
                emb = np.frombuffer(blob, dtype=np.float32)
                embeddings_list.append(emb)
            else:
                desc = f"{row['item_name']} {row['description'] or ''}".strip()
                missing_texts.append(desc)
                missing_indices.append(i)
                embeddings_list.append(None)

        if missing_texts:
            computed = self.embedder.embed_texts(missing_texts)
            for idx, c_emb in zip(missing_indices, computed):
                embeddings_list[idx] = c_emb

        if embeddings_list:
            self.matrix = np.vstack(embeddings_list)
        else:
            self.matrix = np.empty((0, self.embedder.dim if hasattr(self.embedder, "dim") else 256), dtype=np.float32)

    def search(
        self,
        query_text: str,
        top_k: int = 10,
        min_similarity: float = 0.0,
    ) -> List[Tuple[dict, float]]:
        if self.matrix is None or len(self.row_ids) == 0:
            return []

        query_vec = self.embedder.embed_text(query_text)
        sims = np.dot(self.matrix, query_vec)

        # Sort descending
        top_indices = np.argsort(-sims)[:top_k]
        results = []
        for idx in top_indices:
            score = float(sims[idx])
            if score >= min_similarity:
                results.append((self.items[idx], score))
        return results
