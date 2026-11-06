from __future__ import annotations

from collections import defaultdict
import shutil
from typing import List, Tuple
from PIL import Image
from invoice_pipeline.config import TesseractConfig
from invoice_pipeline.ingest.ocr.base import OCREngine


class TesseractEngine(OCREngine):
    def __init__(self, config: TesseractConfig) -> None:
        self.config = config
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is None:
            # Check custom command or system tesseract
            cmd = self.config.cmd or "tesseract"
            self._available = shutil.which(cmd) is not None
        return self._available

    def is_loaded(self) -> bool:
        # Tesseract is a CLI subprocess tool, ready whenever available
        return self.is_available()

    def run_ocr(self, images: List[Image.Image]) -> Tuple[str, float, List[float]]:
        try:
            import pytesseract
        except ImportError:
            raise RuntimeError("pytesseract package is not installed.")

        if self.config.cmd:
            pytesseract.pytesseract.tesseract_cmd = self.config.cmd

        all_text = []
        all_confidences = []
        per_page_confidences = []

        cfg = f"--psm {self.config.psm}"

        for idx, img in enumerate(images):
            try:
                data = pytesseract.image_to_data(
                    img,
                    lang=self.config.lang,
                    config=cfg,
                    output_type=pytesseract.Output.DICT,
                )
            except Exception as e:
                # Engine failure on this page
                all_text.append(f"--- PAGE {idx+1} ---\n[OCR_FAILED]")
                per_page_confidences.append(0.0)
                continue

            # Group words by (block_num, par_num, line_num) to preserve lines & tables
            lines_dict = defaultdict(list)
            page_confs = []

            n_boxes = len(data["text"])
            for i in range(n_boxes):
                text = data["text"][i].strip()
                if not text:
                    continue
                conf = float(data["conf"][i])
                key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                lines_dict[key].append(text)
                if conf >= 0:
                    page_confs.append(conf / 100.0)
                    all_confidences.append(conf / 100.0)

            # Sort lines in reading order
            sorted_keys = sorted(lines_dict.keys())
            page_lines = [" ".join(lines_dict[k]) for k in sorted_keys]
            page_str = "\n".join(page_lines)

            all_text.append(f"--- PAGE {idx+1} ---\n{page_str}")
            page_mean = sum(page_confs) / max(1, len(page_confs)) if page_confs else 0.0
            per_page_confidences.append(page_mean)

        full_text = "\n\n".join(all_text)
        overall_mean = (
            sum(all_confidences) / max(1, len(all_confidences)) if all_confidences else 0.0
        )
        return full_text, overall_mean, per_page_confidences
