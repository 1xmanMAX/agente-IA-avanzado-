"""Primitivas de dibujo compartidas (fuentes, colores, flechas, cajas de texto) sobre Pillow."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import ImageColor, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
_BOLD_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


@lru_cache(maxsize=64)
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for cand in (_BOLD_CANDIDATES if bold else []) + _FONT_CANDIDATES:
        if Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    try:
        import matplotlib  # fuente DejaVu incluida con matplotlib
        f = Path(matplotlib.get_data_path()) / "fonts/ttf" / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
        return ImageFont.truetype(str(f), size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default(size=size)


PALETTE = ["#e6194b", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf",
           "#d62728", "#8c564b", "#e377c2", "#bcbd22"]


def color(c, alpha: float | None = None, default="#e6194b"):
    """Acepta '#rrggbb', nombres CSS, [r,g,b] o [r,g,b,a]; devuelve tupla RGBA."""
    if c is None:
        c = default
    if isinstance(c, (list, tuple)):
        vals = [int(v) for v in c]
        rgba = tuple(vals + [255] * (4 - len(vals)))[:4]
    else:
        rgba = ImageColor.getcolor(str(c), "RGBA")
    if alpha is not None:
        rgba = rgba[:3] + (int(255 * alpha),)
    return rgba


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    l, t, r, b = draw.multiline_textbbox((0, 0), text, font=font)
    return r - l, b - t


def label_box(draw, xy, text, font, fg="#111", bg="#ffffffe6", border=None, pad=6,
              anchor="mm", radius=6):
    """Dibuja un texto con fondo redondeado. anchor: 'mm' centrado, 'lt' esquina sup. izq."""
    tw, th = text_size(draw, text, font)
    x, y = xy
    if anchor == "mm":
        x0, y0 = x - tw / 2 - pad, y - th / 2 - pad
    else:
        x0, y0 = x, y
    box = [x0, y0, x0 + tw + 2 * pad, y0 + th + 2 * pad]
    draw.rounded_rectangle(box, radius=radius, fill=color(bg),
                           outline=color(border) if border else None, width=2 if border else 0)
    draw.multiline_text((x0 + pad, y0 + pad - 1), text, font=font, fill=color(fg))
    return box


def arrow(draw, start, end, fill="#e6194b", width=4, head=None, both=False, dashed=False,
          curve: float = 0.0):
    """Flecha recta o curva (curve = desplazamiento relativo del punto de control, p.ej. 0.2)."""
    fill = color(fill)
    head = head or max(12, width * 4)
    pts = _curve_points(start, end, curve) if curve else [start, end]
    if dashed:
        _dashed_polyline(draw, pts, fill, width, dash=width * 4)
    else:
        draw.line(pts, fill=fill, width=width, joint="curve")
    _arrow_head(draw, pts[-2], pts[-1], fill, head)
    if both:
        _arrow_head(draw, pts[1], pts[0], fill, head)


def _curve_points(a, b, k, n=40):
    (x1, y1), (x2, y2) = a, b
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    cx, cy = mx - dy * k, my + dx * k
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * x1 + 2 * (1 - t) * t * cx + t ** 2 * x2
        y = (1 - t) ** 2 * y1 + 2 * (1 - t) * t * cy + t ** 2 * y2
        pts.append((x, y))
    return pts


def _arrow_head(draw, p_from, p_to, fill, size):
    ang = math.atan2(p_to[1] - p_from[1], p_to[0] - p_from[0])
    x, y = p_to
    left = (x - size * math.cos(ang - math.pi / 7), y - size * math.sin(ang - math.pi / 7))
    right = (x - size * math.cos(ang + math.pi / 7), y - size * math.sin(ang + math.pi / 7))
    draw.polygon([p_to, left, right], fill=fill)


def _dashed_polyline(draw, pts, fill, width, dash=12):
    on = True
    rem = dash
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        pos = 0.0
        while pos < seg:
            step = min(rem, seg - pos)
            if on:
                t0, t1 = pos / seg, (pos + step) / seg
                draw.line([(x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0),
                           (x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1)], fill=fill, width=width)
            pos += step
            rem -= step
            if rem <= 0:
                on = not on
                rem = dash
    return


def dashed_line(draw, pts, fill, width, dash=12):
    _dashed_polyline(draw, pts, color(fill), width, dash)


def numbered_marker(draw, center, number, fill="#e6194b", radius=18, font=None):
    x, y = center
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color(fill),
                 outline=(255, 255, 255, 255), width=max(2, radius // 6))
    font = font or load_font(int(radius * 1.1), bold=True)
    draw.text((x, y), str(number), font=font, fill="white", anchor="mm")


def edge_point_towards(box, target):
    """Punto del borde de un rectángulo (x0,y0,x1,y1) en dirección a target."""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = target[0] - cx, target[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
    s = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    return cx + dx * s, cy + dy * s
