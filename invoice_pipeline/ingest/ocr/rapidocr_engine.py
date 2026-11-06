from __future__ import annotations

from typing import List, Tuple
import numpy as np
from PIL import Image
from invoice_pipeline.config import RapidOCRConfig
from invoice_pipeline.ingest.ocr.base import OCREngine


class RapidOCREngine(OCREngine):
    def __init__(self, config: RapidOCRConfig) -> None:
        self.config = config
        self._engine = None

    def is_available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa
            return True
        except ImportError:
            return False

    def is_loaded(self) -> bool:
        return self._engine is not None

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            # Pass use_angle_cls from config
            self._engine = RapidOCR(use_angle_cls=self.config.use_angle_cls)
        return self._engine

    def run_ocr(self, images: List[Image.Image]) -> Tuple[str, float, List[float]]:
        engine = self._get_engine()
        all_text = []
        all_confidences = []
        per_page_confidences = []

        for idx, img in enumerate(images):
            np_img = np.array(img.convert("RGB"))
            try:
                result, _ = engine(np_img)
            except Exception:
                result = None

            page_text = []
            page_confs = []

            if result:
                for line in result:
                    # line format: [box, text, score]
                    text = str(line[1]).strip()
                    score = float(line[2])
                    if text:
                        page_text.append(text)
                        page_confs.append(score)
                        all_confidences.append(score)

            all_text.append(f"--- PAGE {idx+1} ---\n" + "\n".join(page_text))
            page_mean = sum(page_confs) / max(1, len(page_confs)) if page_confs else 0.0
            per_page_confidences.append(page_mean)

        full_text = "\n\n".join(all_text)
        overall_mean = (
            sum(all_confidences) / max(1, len(all_confidences)) if all_confidences else 0.0
        )
        return full_text, overall_mean, per_page_confidences
