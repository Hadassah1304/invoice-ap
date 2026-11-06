from __future__ import annotations

import io
import math
import random
from typing import Dict, List, Optional, Tuple
import cv2
import fitz  # PyMuPDF
import numpy as np
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from render.stamps import apply_stamp


def rasterize_pdf_page(doc: fitz.Document, page_num: int = 0, dpi: int = 200) -> np.ndarray:
    """Rasterize a single PDF page at specified dpi returning an RGB numpy array."""
    page = doc[page_num]
    pix = page.get_pixmap(dpi=int(dpi))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
    if pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
    elif pix.n == 1:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    return img


def degrade_image(
    img: np.ndarray,
    level: str,
    case_rng: random.Random,
    np_rng: np.random.Generator,
    grand_total_box: Optional[Tuple[float, float, float, float]] = None,
    dpi: float = 200.0,
) -> Tuple[np.ndarray, Dict[str, any]]:
    """Apply degradation pipeline according to level ('light', 'medium', 'heavy')."""
    h, w = img.shape[:2]
    out = img.copy()
    params = {"level": level}

    # 1. Heavy extra: Stamp over grand total
    stamp_coverage = 0.0
    if level == "heavy":
        out, stamp_coverage = apply_stamp(out, grand_total_box, case_rng, dpi=dpi)
        params["stamp_coverage_pct"] = stamp_coverage

    # 2. Heavy extra: Perspective warp (phone-photo look, corner offsets up to 2.5%)
    if level == "heavy":
        max_ox = 0.025 * w
        max_oy = 0.025 * h
        dx0, dy0 = np_rng.uniform(-max_ox, max_ox), np_rng.uniform(-max_oy, max_oy)
        dx1, dy1 = np_rng.uniform(-max_ox, max_ox), np_rng.uniform(-max_oy, max_oy)
        dx2, dy2 = np_rng.uniform(-max_ox, max_ox), np_rng.uniform(-max_oy, max_oy)
        dx3, dy3 = np_rng.uniform(-max_ox, max_ox), np_rng.uniform(-max_oy, max_oy)

        src_pts = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
        dst_pts = np.array(
            [
                [max(0, dx0), max(0, dy0)],
                [min(w, w + dx1), max(0, dy1)],
                [min(w, w + dx2), min(h, h + dy2)],
                [max(0, dx3), min(h, h + dy3)],
            ],
            dtype=np.float32,
        )
        m_warp = cv2.getPerspectiveTransform(src_pts, dst_pts)
        out = cv2.warpPerspective(out, m_warp, (w, h), borderValue=(255, 255, 255))
        params["perspective_warp"] = True

    # 3. Rotation
    if level == "light":
        deg = case_rng.choice([-1.0, 1.0]) * case_rng.uniform(0.3, 1.0)
    elif level == "medium":
        deg = case_rng.choice([-1.0, 1.0]) * case_rng.uniform(1.0, 2.0)
    elif level == "heavy":
        deg = case_rng.choice([-1.0, 1.0]) * case_rng.uniform(1.5, 3.0)
    else:
        deg = 0.0

    if abs(deg) > 0.01:
        m_rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), deg, 1.0)
        out = cv2.warpAffine(out, m_rot, (w, h), borderValue=(255, 255, 255))
    params["rotation_deg"] = deg

    # 4. Extras: Page-edge shadow / Uneven lighting / Speckles
    if level == "light":
        # Slight page-edge shadow along one random edge
        edge = case_rng.choice(["left", "top"])
        shadow_depth = int(case_rng.uniform(25, 45))
        min_factor = case_rng.uniform(0.82, 0.90)
        if edge == "left":
            grad = np.linspace(min_factor, 1.0, shadow_depth, dtype=np.float32)
            out[:, :shadow_depth] = np.clip(out[:, :shadow_depth].astype(np.float32) * grad[None, :, None], 0, 255).astype(np.uint8)
        else:
            grad = np.linspace(min_factor, 1.0, shadow_depth, dtype=np.float32)
            out[:shadow_depth, :] = np.clip(out[:shadow_depth, :].astype(np.float32) * grad[:, None, None], 0, 255).astype(np.uint8)
        params["edge_shadow"] = edge

    elif level == "medium":
        # Uneven lighting gradient (smooth across page)
        gx = np.linspace(case_rng.uniform(0.88, 0.94), case_rng.uniform(1.00, 1.04), w, dtype=np.float32)
        gy = np.linspace(case_rng.uniform(0.92, 0.96), case_rng.uniform(1.00, 1.04), h, dtype=np.float32)
        grid = np.outer(gy, gx)[:, :, None]
        out = np.clip(out.astype(np.float32) * grid, 0, 255).astype(np.uint8)

        # Faint speckles
        num_speckles = case_rng.randint(50, 90)
        for _ in range(num_speckles):
            sx = case_rng.randint(0, w - 2)
            sy = case_rng.randint(0, h - 2)
            darkness = case_rng.randint(70, 140)
            out[sy:sy+2, sx:sx+2] = (darkness, darkness, darkness)
        params["speckles_count"] = num_speckles

    # 5. Contrast and Brightness Shift
    if level == "light":
        contrast = case_rng.uniform(0.92, 1.00)
        brightness = 0.0
    elif level == "medium":
        contrast = case_rng.uniform(0.80, 0.92)
        brightness = case_rng.uniform(-8.0, 8.0)
    elif level == "heavy":
        contrast = case_rng.uniform(0.70, 0.85)
        brightness = case_rng.uniform(-15.0, 8.0)
    else:
        contrast = 1.0
        brightness = 0.0

    img_f = out.astype(np.float32) * contrast + brightness
    out = np.clip(img_f, 0, 255).astype(np.uint8)
    params["contrast"] = contrast
    params["brightness"] = brightness

    # 6. Blur (Gaussian sigma)
    if level == "light":
        sigma = case_rng.uniform(0.4, 0.7)
    elif level == "medium":
        sigma = case_rng.uniform(0.8, 1.2)
    elif level == "heavy":
        sigma = case_rng.uniform(1.2, 1.8)
    else:
        sigma = 0.0

    if sigma > 0.1:
        k = int(2 * math.ceil(2 * sigma) + 1)
        if k % 2 == 0:
            k += 1
        out = cv2.GaussianBlur(out, (k, k), sigma)
    params["blur_sigma"] = sigma

    # 7. Noise (Gaussian sigma)
    if level == "light":
        noise_sigma = case_rng.uniform(3.0, 6.0)
    elif level == "medium":
        noise_sigma = case_rng.uniform(6.0, 10.0)
    elif level == "heavy":
        noise_sigma = case_rng.uniform(10.0, 16.0)
    else:
        noise_sigma = 0.0

    if noise_sigma > 0.1:
        noise = np_rng.normal(0, noise_sigma, out.shape)
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    params["noise_sigma"] = noise_sigma

    return out, params


def save_image_only_pdf(images: List[np.ndarray], output_path: str, target_dpi: float = 150.0, source_dpi: float = 200.0):
    """Save raster image(s) as a deterministic image-only PDF with invariant=1 and zero text layer."""
    c = None
    scale = target_dpi / source_dpi

    for img in images:
        h, w = img.shape[:2]
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Convert to PNG bytes
        success, png_bytes = cv2.imencode(".png", cv2.cvtColor(resized, cv2.COLOR_RGB2BGR))
        if not success:
            raise RuntimeError("Failed to encode image to PNG for PDF wrapper")

        # Page dimensions in points (72 pt per inch)
        pt_w = new_w * (72.0 / target_dpi)
        pt_h = new_h * (72.0 / target_dpi)

        if c is None:
            c = canvas.Canvas(output_path, pagesize=(pt_w, pt_h), invariant=1)
        else:
            c.setPageSize((pt_w, pt_h))

        reader = ImageReader(io.BytesIO(png_bytes.tobytes()))
        c.drawImage(reader, 0, 0, width=pt_w, height=pt_h)
        c.showPage()

    if c:
        c.save()


def process_degraded_document(
    digital_pdf_path: str,
    output_path: str,
    level: str,
    seed: int,
    case_id: str,
    bounding_boxes: Optional[Dict[str, Tuple[int, float, float, float, float]]] = None,
) -> Dict[str, any]:
    """Render a digital PDF into a degraded scanned document (PDF, PNG, or JPG) with no text layer."""
    case_rng = random.Random(f"{seed}:{case_id}")
    np_seed = case_rng.randint(0, 2**31 - 1)
    np_rng = np.random.default_rng(np_seed)

    doc = fitz.open(digital_pdf_path)
    page_count = len(doc)

    grand_total_box = None
    if bounding_boxes and "grand_total" in bounding_boxes:
        gt = bounding_boxes["grand_total"]
        # (page_idx, x0, y0, x1, y1)
        grand_total_box = (gt[1], gt[2], gt[3], gt[4])

    degraded_pages = []
    all_params = []

    for page_idx in range(page_count):
        raw_img = rasterize_pdf_page(doc, page_num=page_idx, dpi=200)
        box_for_page = grand_total_box if (bounding_boxes and bounding_boxes.get("grand_total", (0,))[0] == page_idx) else None
        deg_img, params = degrade_image(
            raw_img,
            level=level,
            case_rng=case_rng,
            np_rng=np_rng,
            grand_total_box=box_for_page,
            dpi=200.0,
        )
        degraded_pages.append(deg_img)
        all_params.append(params)

    doc.close()

    # Encode according to level
    if level == "light":
        # Image-only PDF at 150 dpi
        save_image_only_pdf(degraded_pages, output_path, target_dpi=150.0, source_dpi=200.0)

    elif level == "medium":
        # PNG: single page or stacked if multi-page
        if len(degraded_pages) == 1:
            final_img = degraded_pages[0]
        else:
            final_img = np.vstack(degraded_pages)
        bgr = cv2.cvtColor(final_img, cv2.COLOR_RGB2BGR)
        cv2.imwrite(output_path, bgr)

    elif level == "heavy":
        # JPG with quality 35-55
        quality = int(case_rng.uniform(35, 55))
        if len(degraded_pages) == 1:
            final_img = degraded_pages[0]
        else:
            final_img = np.vstack(degraded_pages)
        bgr = cv2.cvtColor(final_img, cv2.COLOR_RGB2BGR)
        cv2.imwrite(output_path, bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        all_params[0]["jpeg_quality"] = quality

    return {"pages": page_count, "level": level, "params": all_params}
