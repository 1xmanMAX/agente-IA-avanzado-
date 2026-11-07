"""Miniaturas WebP en caché para que móviles y tablets no descarguen imágenes a resolución completa.

También rasteriza páginas de PDF: iOS/iPadOS solo muestra la primera página de un PDF dentro de un
iframe, así que en móviles el visor muestra las páginas como imágenes ligeras.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps

ALLOWED_WIDTHS = (160, 320, 480, 720, 1080, 1600, 2400)


def snap_width(w: int) -> int:
    """Redondea al tamaño permitido más cercano por arriba (limita la variedad de la caché)."""
    for a in ALLOWED_WIDTHS:
        if w <= a:
            return a
    return ALLOWED_WIDTHS[-1]


def thumb_path(ws: Path, src: Path, width: int, page: int = 0) -> Path:
    st = src.stat()
    key = f"{src}|{st.st_mtime_ns}|{st.st_size}|{width}|{page}"
    return ws / ".thumbs" / (hashlib.sha1(key.encode()).hexdigest()[:20] + ".webp")


def make_thumb(ws: Path, src: Path, width: int, page: int = 0) -> Path | None:
    """Devuelve la ruta de la miniatura (creándola si hace falta) o None si no aplica."""
    width = snap_width(width)
    out = thumb_path(ws, src, width, page)
    if out.exists():
        return out
    ext = src.suffix.lower()
    if ext == ".pdf":
        try:
            import pymupdf
        except ImportError:
            return None
        doc = pymupdf.open(src)
        if page >= doc.page_count:
            return None
        pg = doc[page]
        zoom = width / max(1.0, pg.rect.width)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic", ".heif"):
        im = Image.open(src)
        # draft() hace que el decodificador JPEG lea ya reducido: mucho menos RAM con fotos de 48 MP
        im.draft("RGB", (width, width * 4))
        im = ImageOps.exif_transpose(im)
        if im.width <= width and src.stat().st_size < 400_000 and ext != ".heic":
            return None  # ya es pequeña: servir el original
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
        im.thumbnail((width, width * 4), Image.LANCZOS)
    else:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    im.save(tmp, "WEBP", quality=80, method=4)
    tmp.replace(out)
    return out


def pdf_page_count(src: Path) -> int:
    try:
        import pymupdf
        return pymupdf.open(src).page_count
    except Exception:  # noqa: BLE001
        try:
            from pypdf import PdfReader
            return len(PdfReader(str(src)).pages)
        except Exception:  # noqa: BLE001
            return 0
