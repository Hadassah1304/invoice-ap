from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Register custom fonts if available
_FONTS_DIR = Path(__file__).parent / "fonts"
_NOTO_SANS_PATH = _FONTS_DIR / "NotoSans-Regular.ttf"

if _NOTO_SANS_PATH.exists():
    try:
        pdfmetrics.registerFont(TTFont("NotoSans", str(_NOTO_SANS_PATH)))
    except Exception:
        pass


def get_font_for_text(text: str, preferred_font: str = "Helvetica") -> str:
    """Return NotoSans if text contains Unicode symbols like ₹ that built-in fonts lack."""
    if "₹" in text or "\u20b9" in text:
        return "NotoSans"
    return preferred_font


class PDFBuilder:
    """Helper wrapper around ReportLab Canvas providing top-down coordinates and bounding box tracking."""

    def __init__(self, filename: str, pagesize: Tuple[float, float] = letter):
        self.filename = filename
        self.pagesize = pagesize
        self.width, self.height = pagesize
        self.canvas = canvas.Canvas(filename, pagesize=pagesize, invariant=1)
        self.current_page = 0
        self.bounding_boxes: Dict[str, Tuple[int, float, float, float, float]] = {}

    def set_bounding_box(self, name: str, x0: float, y0: float, x1: float, y1: float):
        """Record bounding box in (page_index, x0, y0, x1, y1) format using top-down points."""
        self.bounding_boxes[name] = (self.current_page, float(x0), float(y0), float(x1), float(y1))

    def draw_text(
        self,
        x: float,
        y_top: float,
        text: str,
        font_name: str = "Helvetica",
        font_size: float = 10,
        color: Union[Color, str] = HexColor("#000000"),
        align: str = "left",
    ) -> Tuple[float, float, float, float]:
        """Draw text using top-down coordinates. Returns (x0, y0, x1, y1) bounding box."""
        if not text:
            return (x, y_top, x, y_top)

        font = get_font_for_text(text, font_name)
        self.canvas.setFont(font, font_size)

        if isinstance(color, str):
            color = HexColor(color)
        self.canvas.setFillColor(color)

        str_w = self.canvas.stringWidth(text, font, font_size)

        if align == "right":
            draw_x = x - str_w
        elif align == "center":
            draw_x = x - (str_w / 2.0)
        else:
            draw_x = x

        # In ReportLab, text baseline is specified in bottom-up coordinates
        # Top of text is roughly y_top, baseline is at (height - y_top - font_size)
        y_canvas = self.height - y_top - font_size
        self.canvas.drawString(draw_x, y_canvas, text)

        return (draw_x, y_top, draw_x + str_w, y_top + font_size + 2)

    def draw_rect(
        self,
        x: float,
        y_top: float,
        width: float,
        height: float,
        fill_color: Optional[Union[Color, str]] = None,
        stroke_color: Optional[Union[Color, str]] = HexColor("#000000"),
        stroke_width: float = 1,
    ):
        """Draw rectangle in top-down coordinates."""
        y_canvas = self.height - y_top - height
        self.canvas.setLineWidth(stroke_width)
        fill = 0
        stroke = 0

        if fill_color:
            fill = 1
            if isinstance(fill_color, str):
                fill_color = HexColor(fill_color)
            self.canvas.setFillColor(fill_color)

        if stroke_color:
            stroke = 1
            if isinstance(stroke_color, str):
                stroke_color = HexColor(stroke_color)
            self.canvas.setStrokeColor(stroke_color)

        self.canvas.rect(x, y_canvas, width, height, fill=fill, stroke=stroke)

    def draw_line(
        self,
        x1: float,
        y1_top: float,
        x2: float,
        y2_top: float,
        stroke_color: Union[Color, str] = HexColor("#000000"),
        stroke_width: float = 1,
    ):
        """Draw line in top-down coordinates."""
        y1_canvas = self.height - y1_top
        y2_canvas = self.height - y2_top
        self.canvas.setLineWidth(stroke_width)
        if isinstance(stroke_color, str):
            stroke_color = HexColor(stroke_color)
        self.canvas.setStrokeColor(stroke_color)
        self.canvas.line(x1, y1_canvas, x2, y2_canvas)

    def show_page(self):
        """Advance to next page."""
        self.canvas.showPage()
        self.current_page += 1

    def save(self) -> Dict[str, Tuple[int, float, float, float, float]]:
        """Finalize and save PDF, returning the bounding boxes."""
        self.canvas.save()
        return self.bounding_boxes
