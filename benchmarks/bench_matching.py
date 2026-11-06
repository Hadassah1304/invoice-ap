from __future__ import annotations

import time
import numpy as np
from invoice_pipeline.store.embeddings import TFIDFCharEmbedder


def bench_matching():
    embedder = TFIDFCharEmbedder()
    scales = [100, 1000, 5000]

    print(f"{'Catalog Lines':<15} | {'Build Time (ms)':<18} | {'Query Search (ms)':<18}")
    print("-" * 55)

    for n in scales:
        texts = [f"Item Description variant {i} specification A4 80gsm" for i in range(n)]

        t0 = time.perf_counter_ns()
        matrix = embedder.embed_texts(texts)
        d_build = int((time.perf_counter_ns() - t0) / 1_000_000)

        query_vec = embedder.embed_text("Item Description variant 42")
        t0 = time.perf_counter_ns()
        sims = np.dot(matrix, query_vec)
        top5 = np.argsort(-sims)[:5]
        d_query = int((time.perf_counter_ns() - t0) / 1_000_000)

        print(f"{n:<15} | {d_build:<18} | {d_query:<18}")


if __name__ == "__main__":
    bench_matching()
