from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from invoice_pipeline.config import PreprocessConfig


def preprocess_image(img: Image.Image, config: PreprocessConfig) -> Image.Image:
    """Grayscale, deskew, and upscale/denoise image for OCR quality enhancement."""
    if not config.enabled:
        return img

    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    if config.denoise:
        # Use fast bilateral filter instead of heavy non-local means to avoid 1.5s+ latency per page
        gray = cv2.bilateralFilter(gray, 9, 75, 75)

    if config.deskew:
        # Deskew using Hough text-line profiling with border exclusion
        h, w = gray.shape[:2]
        # Crop 5% border to avoid scanner bed shadow edges dominating the angle
        border_y, border_x = int(h * 0.05), int(w * 0.05)
        roi = gray[border_y : h - border_y, border_x : w - border_x]

        edges = cv2.Canny(roi, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=w // 4, maxLineGap=20)

        angle = 0.0
        if lines is not None and len(lines) > 0:
            angles = []
            for line in lines:
                coords = line.flatten()
                if len(coords) >= 4:
                    x1, y1, x2, y2 = coords[:4]
                    if x2 - x1 != 0:
                        deg = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                        if abs(deg) < 45.0:
                            angles.append(deg)
            if angles:
                angle = float(np.median(angles))

        if abs(angle) > 0.5 and abs(angle) < 45.0:
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            gray = cv2.warpAffine(
                gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )

    return Image.fromarray(gray)
