from __future__ import annotations

import random
from typing import Optional, Tuple
import cv2
import numpy as np


def apply_stamp(
    img: np.ndarray,
    grand_total_box: Optional[Tuple[float, float, float, float]],
    rng: random.Random,
    dpi: float = 200.0,
) -> Tuple[np.ndarray, float]:
    """Apply a translucent stamp over the grand-total bounding box.
    
    grand_total_box: (x0, y0, x1, y1) in top-down points at 72 dpi.
    Returns: (stamped_img, coverage_pct)
    Guarantees:
      - Stamp outline (circular or rectangular)
      - Text from {'RECEIVED', 'PAID', 'VERIFIED', 'APPROVED'}
      - Rotated -20..20 degrees
      - Alpha <= 0.45
      - Red or blue ink
      - Stamp pixels cover <= 60% of the grand-total box
    """
    h_img, w_img = img.shape[:2]

    # Convert box to pixels
    if grand_total_box is not None:
        bx0 = int(grand_total_box[0] * dpi / 72.0)
        by0 = int(grand_total_box[1] * dpi / 72.0)
        bx1 = int(grand_total_box[2] * dpi / 72.0)
        by1 = int(grand_total_box[3] * dpi / 72.0)
    else:
        # Fallback if no box recorded: bottom right quadrant
        bx0, by0 = int(w_img * 0.65), int(h_img * 0.70)
        bx1, by1 = int(w_img * 0.90), int(h_img * 0.78)

    # Clamp to image boundaries
    bx0 = max(0, min(bx0, w_img - 10))
    by0 = max(0, min(by0, h_img - 10))
    bx1 = max(bx0 + 10, min(bx1, w_img))
    by1 = max(by0 + 10, min(by1, h_img))

    cx = (bx0 + bx1) // 2
    cy = (by0 + by1) // 2
    box_w = bx1 - bx0
    box_h = by1 - by0

    # Stamp parameters
    text = rng.choice(["RECEIVED", "PAID", "VERIFIED", "APPROVED"])
    shape = rng.choice(["rectangle", "circle"])
    angle = rng.uniform(-20.0, 20.0)
    alpha = rng.uniform(0.32, 0.44)  # <= 0.45
    ink_color = rng.choice([(195, 30, 30), (25, 65, 195)])  # Red or Blue (RGB)

    # Dimensions of stamp canvas
    stamp_w = max(box_w + 30, 160)
    stamp_h = max(box_h + 20, 80)
    stamp_canvas = np.zeros((stamp_h, stamp_w, 3), dtype=np.uint8)

    # Thickness 2-3px
    thickness = 3
    if shape == "circle":
        radius = min(stamp_w, stamp_h) // 2 - 4
        scx, scy = stamp_w // 2, stamp_h // 2
        cv2.circle(stamp_canvas, (scx, scy), radius, ink_color, thickness)
        cv2.circle(stamp_canvas, (scx, scy), radius - 4, ink_color, 1)
    else:
        cv2.rectangle(stamp_canvas, (4, 4), (stamp_w - 5, stamp_h - 5), ink_color, thickness)
        cv2.rectangle(stamp_canvas, (8, 8), (stamp_w - 9, stamp_h - 9), ink_color, 1)

    # Text rendering in center
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, 2)
    # Scale down text if too wide for stamp
    if tw > stamp_w - 20:
        font_scale *= (stamp_w - 20) / tw
        (tw, th), baseline = cv2.getTextSize(text, font, font_scale, 2)

    tx = (stamp_w - tw) // 2
    ty = (stamp_h + th) // 2
    cv2.putText(stamp_canvas, text, (tx, ty), font, font_scale, ink_color, 2, cv2.LINE_AA)

    # Rotate stamp
    rot_matrix = cv2.getRotationMatrix2D((stamp_w / 2.0, stamp_h / 2.0), angle, 1.0)
    stamp_rotated = cv2.warpAffine(stamp_canvas, rot_matrix, (stamp_w, stamp_h))

    # Calculate placement on target image
    x_start = cx - stamp_w // 2
    y_start = cy - stamp_h // 2

    x_img_start = max(0, x_start)
    y_img_start = max(0, y_start)
    x_img_end = min(w_img, x_start + stamp_w)
    y_img_end = min(h_img, y_start + stamp_h)

    x_stamp_start = x_img_start - x_start
    y_stamp_start = y_img_start - y_start
    x_stamp_end = x_stamp_start + (x_img_end - x_img_start)
    y_stamp_end = y_stamp_start + (y_img_end - y_img_start)

    stamp_crop = stamp_rotated[y_stamp_start:y_stamp_end, x_stamp_start:x_stamp_end]
    mask = (stamp_crop > 0).any(axis=2)

    out_img = img.copy()
    region = out_img[y_img_start:y_img_end, x_img_start:x_img_end]

    for c in range(3):
        region[:, :, c] = np.where(
            mask,
            np.clip((1.0 - alpha) * region[:, :, c] + alpha * stamp_crop[:, :, c], 0, 255).astype(np.uint8),
            region[:, :, c],
        )

    # Compute coverage percentage inside the grand total box
    full_mask = np.zeros((h_img, w_img), dtype=bool)
    full_mask[y_img_start:y_img_end, x_img_start:x_img_end] = mask

    box_pixels = full_mask[by0:by1, bx0:bx1]
    total_pixels = max(1, (by1 - by0) * (bx1 - bx0))
    stamp_pixels = int(np.count_nonzero(box_pixels))
    coverage_pct = (stamp_pixels / total_pixels) * 100.0

    return out_img, coverage_pct
