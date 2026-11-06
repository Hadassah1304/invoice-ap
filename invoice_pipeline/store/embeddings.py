from __future__ import annotations

import zlib
from typing import List, Optional
import numpy as np


class Embedder:
    dim: int = 256

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        raise NotImplementedError

    def embed_text(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]

    def is_available(self) -> bool:
        return True

    def is_loaded(self) -> bool:
        return True


class TFIDFCharEmbedder(Embedder):
    """Deterministic char n-gram TF-IDF embedder using CRC32 hashing (process-independent)."""

    def __init__(self, n_gram: int = 3, dim: int = 256) -> None:
        self.n_gram = n_gram
        self.dim = dim

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            clean = " " + " ".join(text.lower().split()) + " "
            counts = [0] * self.dim
            if len(clean) < self.n_gram:
                h = zlib.crc32(clean.encode("utf-8")) % self.dim
                counts[h] += 1
            else:
                for j in range(len(clean) - self.n_gram + 1):
                    gram = clean[j : j + self.n_gram]
                    h = zlib.crc32(gram.encode("utf-8")) % self.dim
                    counts[h] += 1

            for bucket in range(self.dim):
                c = counts[bucket]
                if c > 0:
                    matrix[i, bucket] = 1.0 + float(np.log(c))

            norm = float(np.linalg.norm(matrix[i]))
            if norm > 0:
                matrix[i] /= norm

        return matrix


class MiniLMEmbedder(Embedder):
    """sentence-transformers/all-MiniLM-L6-v2 embedder (lazy-loaded)."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None
        self.dim = 384

    def is_available(self) -> bool:
        try:
            import sentence_transformers  # noqa
            return True
        except ImportError:
            return False

    def is_loaded(self) -> bool:
        return self._model is not None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception:
                # Fallback to deterministic TFIDF if unavailable
                self._model = TFIDFCharEmbedder(dim=self.dim)

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        self._load()
        if isinstance(self._model, TFIDFCharEmbedder):
            return self._model.embed_texts(texts)
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(embeddings, dtype=np.float32)


_CACHED_EMBEDDER: Optional[Embedder] = None


def get_embedder(backend: str = "minilm", model_name: str = "") -> Embedder:
    global _CACHED_EMBEDDER
    if _CACHED_EMBEDDER is not None:
        return _CACHED_EMBEDDER

    if backend == "minilm":
        _CACHED_EMBEDDER = MiniLMEmbedder(model_name or "sentence-transformers/all-MiniLM-L6-v2")
    else:
        _CACHED_EMBEDDER = TFIDFCharEmbedder()
    return _CACHED_EMBEDDER
