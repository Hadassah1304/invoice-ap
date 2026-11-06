from __future__ import annotations

import time
from pathlib import Path
from invoice_pipeline.config import PipelineConfig
from invoice_pipeline.ingest.ocr.router import OCRRouter


def bench_ocr():
    cfg = PipelineConfig()
    router = OCRRouter(cfg.ocr)
    samples_dir = Path("samples")
    files = list(samples_dir.glob("*.pdf"))[:3]

    print(f"{'File':<25} | {'Engine':<12} | {'Duration (ms)':<15} | {'Conf':<6}")
    print("-" * 65)

    for f in files:
        # RapidOCR
        t0 = time.perf_counter_ns()
        _, _, conf_rapid, *_ = router.extract_text(f, force_engine="rapidocr")
        d_rapid = int((time.perf_counter_ns() - t0) / 1_000_000)
        print(f"{f.name:<25} | {'rapidocr':<12} | {d_rapid:<15} | {conf_rapid:.2f}")

        # Text layer directly
        t0 = time.perf_counter_ns()
        _, _, conf_txt, *_ = router.extract_text(f, force_engine=None)
        d_txt = int((time.perf_counter_ns() - t0) / 1_000_000)
        print(f"{f.name:<25} | {'text_layer':<12} | {d_txt:<15} | {conf_txt:.2f}")


if __name__ == "__main__":
    bench_ocr()
