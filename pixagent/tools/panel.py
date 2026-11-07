"""Panel fotográfico: maquetación determinista de fotos en páginas PDF (sin gastar tokens).

Lo usan la mini app "Panel fotográfico" (vía /api/photo-panel) y el agente (herramienta photo_panel).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PIL import Image, ImageOps

from .base import ToolContext, ToolError, ToolResult, tool

LAYOUTS = {"1x1": (1, 1), "1x2": (1, 2), "2x1": (2, 1), "2x2": (2, 2), "2x3": (2, 3), "3x2": (3, 2),
           "3x3": (3, 3), "3x4": (3, 4), "4x3": (4, 3)}


def build_photo_panel(ctx: ToolContext, spec: dict) -> tuple[Path, int]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A3, A4, landscape, letter
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    from .documents import register_fonts

    photos = spec.get("photos") or []
    if not photos:
        raise ToolError("El panel necesita al menos una foto.")
    out = ctx.resolve(spec.get("output") or f"outputs/paneles/panel_{date.today():%Y%m%d}.pdf")
    if out.suffix.lower() != ".pdf":
        out = out.with_suffix(".pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    cols, rows = LAYOUTS.get(spec.get("layout", "2x3"), (2, 3))
    size = {"A4": A4, "A3": A3, "letter": letter}.get(spec.get("page", "A4"), A4)
    if spec.get("orientation") == "landscape":
        size = landscape(size)
    PW, PH = size
    theme = colors.HexColor(spec.get("theme_color") or "#1f4e79")
    base, bold = register_fonts()
    fit = spec.get("fit", "cover")
    numbering = spec.get("numbering", True)
    fields = spec.get("fields") or {}
    m = 1.2 * cm
    header_h = 2.0 * cm + (0.45 * cm * ((len(fields) + 1) // 2) if fields else 0)
    footer_h = 0.8 * cm
    gap = 0.35 * cm
    cap_h = 0.75 * cm
    per_page = cols * rows
    pages = (len(photos) + per_page - 1) // per_page
    c = rl_canvas.Canvas(str(out), pagesize=size)
    c.setTitle(spec.get("title") or "Panel fotográfico")
    logo = None
    if spec.get("logo"):
        try:
            logo = ImageReader(str(ctx.resolve(spec["logo"], must_exist=True)))
        except Exception:  # noqa: BLE001
            logo = None
    tmpdir = ctx.ws / ".tmp" / "panel"
    tmpdir.mkdir(parents=True, exist_ok=True)

    for pg in range(pages):
        # cabecera
        c.setFillColor(theme)
        c.rect(0, PH - 1.25 * cm, PW, 1.25 * cm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(bold, 14)
        c.drawString(m, PH - 0.85 * cm, (spec.get("title") or "Panel fotográfico")[:80])
        if spec.get("subtitle"):
            c.setFont(base, 9.5)
            c.drawRightString(PW - m - (2.6 * cm if logo else 0), PH - 0.82 * cm, str(spec["subtitle"])[:90])
        if logo:
            c.drawImage(logo, PW - m - 2.3 * cm, PH - 1.15 * cm, 2.2 * cm, 1.0 * cm, preserveAspectRatio=True, mask="auto")
        y = PH - 1.25 * cm - 0.5 * cm
        if fields:
            c.setFillColor(colors.HexColor("#222222"))
            items = list(fields.items())
            colw = (PW - 2 * m) / 2
            for i, (k, v) in enumerate(items):
                xx = m + (i % 2) * colw
                yy = y - (i // 2) * 0.45 * cm
                c.setFont(bold, 8.5)
                c.drawString(xx, yy, f"{k}:")
                c.setFont(base, 8.5)
                c.drawString(xx + c.stringWidth(f"{k}: ", bold, 8.5), yy, str(v)[:70])
        # rejilla
        top = PH - header_h - 0.2 * cm
        bottom = footer_h + m * 0.5
        cell_w = (PW - 2 * m - (cols - 1) * gap) / cols
        cell_h = (top - bottom - (rows - 1) * gap) / rows
        img_h = cell_h - cap_h
        for k, ph in enumerate(photos[pg * per_page:(pg + 1) * per_page]):
            idx = pg * per_page + k
            r, col = divmod(k, cols)
            x0 = m + col * (cell_w + gap)
            y0 = top - (r + 1) * cell_h - r * gap
            p = ctx.resolve(ph["path"], must_exist=True)
            im = ImageOps.exif_transpose(Image.open(p))
            im.draft("RGB", (int(cell_w / cm * 120), int(img_h / cm * 120)))
            im = im.convert("RGB")
            box_ratio = cell_w / img_h
            if fit == "cover":
                ir = im.width / im.height
                if ir > box_ratio:
                    nw = int(im.height * box_ratio)
                    im = im.crop(((im.width - nw) // 2, 0, (im.width + nw) // 2, im.height))
                else:
                    nh = int(im.width / box_ratio)
                    im = im.crop((0, (im.height - nh) // 2, im.width, (im.height + nh) // 2))
            # ~150 dpi en la celda: PDF ligero pero nítido
            target = (max(1, int(cell_w / 72 * 150)), max(1, int(img_h / 72 * 150)))
            im.thumbnail(target, Image.LANCZOS)
            tmp = tmpdir / f"p{idx}.jpg"
            im.save(tmp, "JPEG", quality=85)
            iw, ih = im.size
            k_fit = min(cell_w / iw, img_h / ih)
            dw, dh = iw * k_fit, ih * k_fit
            c.drawImage(str(tmp), x0 + (cell_w - dw) / 2, y0 + cap_h + (img_h - dh) / 2, dw, dh)
            c.setStrokeColor(colors.HexColor("#c8ced8"))
            c.setLineWidth(0.6)
            c.rect(x0, y0, cell_w, cell_h, stroke=1, fill=0)
            c.setFillColor(colors.HexColor("#f3f6fa"))
            c.rect(x0, y0, cell_w, cap_h, stroke=0, fill=1)
            c.setFillColor(colors.HexColor("#222222"))
            caption = str(ph.get("caption") or "")
            label = (f"Foto {idx + 1}. " if numbering else "") + caption
            fs = 8.5
            while c.stringWidth(label, base, fs) > cell_w - 0.3 * cm and fs > 6:
                fs -= 0.5
            if c.stringWidth(label, base, fs) > cell_w - 0.3 * cm:
                while label and c.stringWidth(label + "…", base, fs) > cell_w - 0.3 * cm:
                    label = label[:-1]
                label += "…"
            c.setFont(base, fs)
            c.drawString(x0 + 0.15 * cm, y0 + cap_h / 2 - fs / 3, label)
            if numbering:
                c.setFillColor(theme)
                c.circle(x0 + 0.45 * cm, y0 + cell_h - 0.45 * cm, 0.3 * cm, stroke=0, fill=1)
                c.setFillColor(colors.white)
                c.setFont(bold, 8)
                c.drawCentredString(x0 + 0.45 * cm, y0 + cell_h - 0.55 * cm, str(idx + 1))
        c.setFillColor(colors.HexColor("#666666"))
        c.setFont(base, 8)
        c.drawString(m, 0.6 * cm, spec.get("footer") or f"Generado con PixAgent · {date.today():%d/%m/%Y}")
        c.drawRightString(PW - m, 0.6 * cm, f"Página {pg + 1} de {pages}")
        c.showPage()
    c.save()
    return out, pages


@tool("photo_panel",
      """Crea un PANEL FOTOGRÁFICO en PDF (rejilla de fotos numeradas con pie de foto, cabecera con
      título, datos del proyecto y logo). Es determinista y barato: úsalo en lugar de maquetar fotos a
      mano. layout: 1x1, 1x2, 2x2, 2x3 (def), 3x3, 3x4... Escribe tú los pies de foto si hace falta.""",
      {"properties": {
          "output": {"type": "string"},
          "title": {"type": "string"}, "subtitle": {"type": "string"},
          "fields": {"type": "object", "description": "Datos de cabecera {Proyecto: ..., Fecha: ...}"},
          "logo": {"type": "string"},
          "layout": {"type": "string"}, "page": {"type": "string", "enum": ["A4", "A3", "letter"]},
          "orientation": {"type": "string", "enum": ["portrait", "landscape"]},
          "photos": {"type": "array", "items": {"type": "object"}, "description": "[{path, caption}]"},
          "numbering": {"type": "boolean"}, "theme_color": {"type": "string"},
          "fit": {"type": "string", "enum": ["cover", "contain"]}},
       "required": ["photos"]})
def photo_panel(ctx: ToolContext, **spec) -> ToolResult:
    out, pages = build_photo_panel(ctx, spec)
    return ToolResult(f"Panel fotográfico: {ctx.rel(out)} ({pages} páginas, {len(spec['photos'])} fotos).", files=[out])
