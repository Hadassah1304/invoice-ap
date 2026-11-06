from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple
import fitz
from PIL import Image
from invoice_pipeline.config import OCRConfig
from invoice_pipeline.ingest.loader import inspect_file, load_image_pages
from invoice_pipeline.ingest.ocr.rapidocr_engine import RapidOCREngine
from invoice_pipeline.ingest.ocr.tesseract_engine import TesseractEngine
from invoice_pipeline.ingest.preprocess import preprocess_image
from invoice_pipeline.ingest.text_layer import extract_pdf_text_layer

_RAPID_INSTANCE: Optional[RapidOCREngine] = None
_TESS_INSTANCE: Optional[TesseractEngine] = None


def get_ocr_engine(engine_name: str, config: OCRConfig):
    global _RAPID_INSTANCE, _TESS_INSTANCE
    clean_name = engine_name.lower().strip()
    if clean_name == "tesseract":
        if _TESS_INSTANCE is None:
            _TESS_INSTANCE = TesseractEngine(config.tesseract)
        return _TESS_INSTANCE, "ocr_tesseract"
    elif clean_name == "rapidocr":
        if _RAPID_INSTANCE is None:
            _RAPID_INSTANCE = RapidOCREngine(config.rapidocr)
        return _RAPID_INSTANCE, "ocr_rapidocr"
    else:
        raise ValueError(f"Unsupported OCR engine '{engine_name}'. Must be 'tesseract' or 'rapidocr'.")


class OCRRouter:
    """Orchestrates PDF text layer extraction, OCR fallback, and image preprocessing."""

    def __init__(self, config: OCRConfig) -> None:
        self.config = config

    def extract_text(
        self,
        file_path: str | Path,
        force_engine: Optional[str] = None,
    ) -> Tuple[str, str, float, List[Image.Image], bool, List[float]]:
        """
        Returns (raw_text, extraction_method, confidence, page_images, needs_vision, per_page_confidences).
        """
        f_type, page_count = inspect_file(file_path)
        page_images: List[Image.Image] = []

        # 1. Render all pages to page_images (always available for fallback/inspection)
        if f_type == "pdf":
            try:
                with fitz.open(str(file_path)) as doc:
                    dpi = self.config.pdf_render_dpi
                    zoom = dpi / 72.0
                    mat = fitz.Matrix(zoom, zoom)
                    for page in doc:
                        pix = page.get_pixmap(matrix=mat)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        page_images.append(img)
            except Exception as e:
                raise ValueError(f"Failed to render PDF pages: {e}")
        else:
            page_images = load_image_pages(file_path)

        # 2. Try text layer if PDF and not explicitly forced to an OCR engine
        if f_type == "pdf" and self.config.text_layer.enabled and not force_engine:
            text, valid, _, page_valids = extract_pdf_text_layer(str(file_path), self.config.text_layer)
            if valid and text:
                per_page_confs = [1.0 if v else 0.0 for v in page_valids]
                return text, "text_layer", 1.0, page_images, False, per_page_confs

        # 3. Preprocess images
        preprocessed = [preprocess_image(im, self.config.preprocess) for im in page_images]

        # 4. Run selected OCR Engine
        target_engine = force_engine or self.config.engine
        engine, method_name = get_ocr_engine(target_engine, self.config)

        text, conf, per_page_confs = engine.run_ocr(preprocessed)

        # Trigger vision fallback flag if mean OCR confidence is below threshold
        needs_vision = conf < self.config.min_confidence and self.config.vision_fallback.enabled

        return text, method_name, conf, page_images, needs_vision, per_page_confs
