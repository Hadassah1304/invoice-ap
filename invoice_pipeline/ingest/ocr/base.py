from __future__ import annotations

import abc
from typing import List, Tuple
from PIL import Image


class OCREngine(abc.ABC):
    @abc.abstractmethod
    def run_ocr(self, images: List[Image.Image]) -> Tuple[str, float, List[float]]:
        """
        Runs OCR on given page images.
        Returns (extracted_text, mean_confidence, per_page_confidences).
        """
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check if engine binary/dependencies are present."""
        pass

    @abc.abstractmethod
    def is_loaded(self) -> bool:
        """Check if engine weights/sessions are loaded in memory."""
        pass
