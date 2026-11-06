from __future__ import annotations

import hashlib
from types import SimpleNamespace
import fitz
import numpy as np
import pytest

from render.degrade import process_degraded_document
from render.layouts.itemised import render_itemised_layout
from render.stamps import apply_stamp
from tests.render.test_layouts import make_dummy_document


def test_stamp_coverage_limit():
    # Letter page at 200 dpi: 1700 x 2200
    img = np.full((2200, 1700, 3), 255, dtype=np.uint8)
    # Grand total box in points: x0=350, y0=600, x1=572, y1=630
    box = (350.0, 600.0, 572.0, 630.0)
    import random
    rng = random.Random("test_seed_42")

    stamped, coverage = apply_stamp(img, box, rng, dpi=200.0)
    assert coverage <= 60.0, f"Stamp coverage was {coverage:.1f}%, expected <= 60%"
    assert coverage > 0.0, "Stamp must produce non-zero ink pixels"


@pytest.mark.parametrize("level, expected_ext", [
    ("light", ".pdf"),
    ("medium", ".png"),
    ("heavy", ".jpg"),
])
def test_degrade_levels_and_no_text_layer(tmp_path, level, expected_ext):
    doc_data = make_dummy_document(line_count=3, grand_total=630.0)
    render_conf = SimpleNamespace(
        layout="itemised",
        degrade="none",
        number_format="plain",
        currency_style="Rs.",
        date_style="dmy_slash",
    )
    digital_pdf = tmp_path / f"digital_{level}.pdf"
    bboxes = render_itemised_layout(doc_data, render_conf, str(digital_pdf))

    scanned_file = tmp_path / f"scanned_{level}{expected_ext}"
    res = process_degraded_document(
        digital_pdf_path=str(digital_pdf),
        output_path=str(scanned_file),
        level=level,
        seed=42,
        case_id=f"SC-TEST-{level}",
        bounding_boxes=bboxes,
    )

    assert scanned_file.exists()
    assert scanned_file.stat().st_size > 0

    if expected_ext == ".pdf":
        doc = fitz.open(str(scanned_file))
        assert len(doc) == 1
        text = doc[0].get_text().strip()
        doc.close()
        assert text == "", f"Scanned image-only PDF must have empty text layer, got: '{text}'"


def test_degradation_determinism(tmp_path):
    doc_data = make_dummy_document(line_count=2, grand_total=420.0)
    render_conf = SimpleNamespace(
        layout="itemised",
        degrade="none",
        number_format="plain",
        currency_style="Rs.",
        date_style="dmy_slash",
    )
    digital_pdf = tmp_path / "digital_det.pdf"
    bboxes = render_itemised_layout(doc_data, render_conf, str(digital_pdf))

    out1 = tmp_path / "run1_heavy.jpg"
    out2 = tmp_path / "run2_heavy.jpg"

    process_degraded_document(str(digital_pdf), str(out1), "heavy", seed=100, case_id="SC-DETERMINISM", bounding_boxes=bboxes)
    process_degraded_document(str(digital_pdf), str(out2), "heavy", seed=100, case_id="SC-DETERMINISM", bounding_boxes=bboxes)

    h1 = hashlib.sha256(open(out1, "rb").read()).hexdigest()
    h2 = hashlib.sha256(open(out2, "rb").read()).hexdigest()
    assert h1 == h2, "Degradation must produce byte-identical output for the same seed and case_id"
