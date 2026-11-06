from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

from render.layouts.bundled import render_bundled_layout
from render.layouts.itemised import render_itemised_layout
from render.layouts.multi_page import render_multi_page_layout
from render.layouts.tax_embedded import render_tax_embedded_layout

LAYOUTS: Dict[str, Callable[[Any, Any, str], Dict[str, Tuple[int, float, float, float, float]]]] = {
    "itemised": render_itemised_layout,
    "bundled": render_bundled_layout,
    "tax_embedded": render_tax_embedded_layout,
    "multi_page": render_multi_page_layout,
}


def get_layout_renderer(layout_name: str) -> Callable[[Any, Any, str], Dict[str, Tuple[int, float, float, float, float]]]:
    """Retrieve the layout renderer function by name."""
    if layout_name not in LAYOUTS:
        raise ValueError(f"Unknown layout: '{layout_name}'. Available: {list(LAYOUTS.keys())}")
    return LAYOUTS[layout_name]
