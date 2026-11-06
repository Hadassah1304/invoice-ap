from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def degrade_scan(
    img: Image.Image,
    rotate_deg: float = 1.5,
    blur_kernel: int = 3,
    noise_sigma: float = 15.0,
    jpeg_quality: int = 40,
) -> Image.Image:
    """Degrade image to simulate real low-quality mobile scan or fax."""
    cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    h, w = cv_img.shape[:2]

    # 1. Subtle rotation / skew
    if abs(rotate_deg) > 0.1:
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, rotate_deg, 1.0)
        cv_img = cv2.warpAffine(cv_img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

    # 2. Gaussian blur
    if blur_kernel > 1:
        cv_img = cv2.GaussianBlur(cv_img, (blur_kernel, blur_kernel), 0)

    # 3. Add Gaussian noise
    if noise_sigma > 0:
        noise = np.random.normal(0, noise_sigma, cv_img.shape).astype(np.float32)
        noisy = np.clip(cv_img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        cv_img = noisy

    # 4. JPEG compression artifacts
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
    _, encimg = cv2.imencode(".jpg", cv_img, encode_param)
    decimg = cv2.imdecode(encimg, 1)

    return Image.fromarray(cv2.cvtColor(decimg, cv2.COLOR_BGR2RGB))
