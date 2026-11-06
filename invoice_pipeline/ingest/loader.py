from __future__ import annotations

from pathlib import Path
from typing import List, Tuple
import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageSequence


def inspect_file(file_path: str | Path) -> Tuple[str, int]:
    """
    Safely detects file type ('pdf' or 'image') and page count.
    Never raises an uncaught exception on corrupt, password-protected, or bad files.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Inspect magic bytes first
    try:
        with open(p, "rb") as f:
            header = f.read(16)
    except Exception as e:
        raise ValueError(f"Unable to read file header: {e}")

    is_pdf = header.startswith(b"%PDF")
    suffix = p.suffix.lower()

    if is_pdf or suffix == ".pdf":
        try:
            with fitz.open(str(p)) as doc:
                if doc.is_encrypted:
                    raise ValueError("PDF is encrypted / password protected")
                count = len(doc)
                return "pdf", max(1, count)
        except Exception as e:
            raise ValueError(f"Corrupt or unreadable PDF: {e}")
    else:
        # Check image via PIL
        try:
            with Image.open(p) as img:
                # Count frames for multi-page formats (e.g. TIFF)
                count = getattr(img, "n_frames", 1)
                return "image", max(1, count)
        except Exception as e:
            raise ValueError(f"Corrupt or unsupported image file: {e}")


def load_image_pages(file_path: str | Path, max_pages: int = 50) -> List[Image.Image]:
    """
    Loads all frames from an image file (e.g. multi-page TIFF or phone photo),
    applying EXIF orientation transposition and RGB conversion.
    """
    p = Path(file_path)
    pages: List[Image.Image] = []
    with Image.open(p) as img:
        for idx, frame in enumerate(ImageSequence.Iterator(img)):
            if idx >= max_pages:
                break
            # Apply EXIF rotation for smartphone photos
            oriented = ImageOps.exif_transpose(frame)
            if oriented is None:
                oriented = frame
            pages.append(oriented.convert("RGB"))
    return pages
