"""Documentos: informes PDF profesionales desde Markdown, utilidades PDF (leer, a imágenes, unir...)."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .base import ToolContext, ToolError, ToolResult, tool, truncate


# ============================================================ create_pdf
@tool("create_pdf",
      """Genera un INFORME/documento PDF profesional desde Markdown con portada, índice, encabezado,
      pie con numeración, tablas, imágenes (fotos, planos, gráficos) y estilos. Markdown soportado:
      # títulos (1-4), párrafos con **negrita**, *cursiva*, `código`, [enlaces](url); listas - y 1.;
      tablas con | ... |; imágenes ![pie de foto](ruta.png){width=60%}; citas >; bloques ```; línea ---;
      salto de página con \\pagebreak. Para diseños muy personalizados usa html_to_pdf.
      Tras generarlo, usa pdf_tools(action='to_images') para revisar visualmente páginas clave.""",
      {"properties": {
          "output": {"type": "string", "description": "p.ej. reports/informe_obra.pdf"},
          "markdown": {"type": "string"},
          "title": {"type": "string"}, "subtitle": {"type": "string"}, "author": {"type": "string"},
          "date": {"type": "string"},
          "cover": {"type": "boolean", "description": "Portada (def true si hay título)."},
          "toc": {"type": "boolean", "description": "Índice automático."},
          "logo": {"type": "string"},
          "cover_image": {"type": "string"},
          "header_text": {"type": "string"},
          "theme_color": {"type": "string", "description": "Color principal, p.ej. #1f4e79"},
          "page_size": {"type": "string", "enum": ["A4", "letter", "A3"]},
          "landscape": {"type": "boolean"}},
       "required": ["output", "markdown"]})
def create_pdf(ctx: ToolContext, output: str, markdown: str, title: str = "", subtitle: str = "",
               author: str = "", date: str = "", cover: bool | None = None, toc: bool = False,
               logo: str | None = None, cover_image: str | None = None, header_text: str = "",
               theme_color: str = "#1f4e79", page_size: str = "A4", landscape: bool = False) -> ToolResult:
    out = ctx.resolve(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    build_pdf(ctx, out, markdown, title=title, subtitle=subtitle, author=author, date_text=date,
              cover=bool(title) if cover is None else cover, toc=toc, logo=logo, cover_image=cover_image,
              header_text=header_text or title, theme=theme_color, page_size=page_size,
              landscape_mode=landscape, warnings=warnings)
    pages = _page_count(out)
    msg = f"PDF creado: {ctx.rel(out)} ({pages} páginas)."
    if warnings:
        msg += "\nAvisos:\n- " + "\n- ".join(warnings)
    return ToolResult(msg, files=[out])


def _page_count(p: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(p)).pages)
    except Exception:  # noqa: BLE001
        return -1


def _inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" backColor="#f0f0f0">\1</font>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#1a5fb4"><u>\1</u></link>', text)
    return text


def build_pdf(ctx, out: Path, md: str, *, title, subtitle, author, date_text, cover, toc, logo,
              cover_image, header_text, theme, page_size, landscape_mode, warnings):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A3, A4, letter, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image as RLImage, KeepTogether, ListFlowable, ListItem, PageBreak,
                                    Paragraph, Preformatted, Spacer, Table, TableStyle)
    from reportlab.platypus.doctemplate import BaseDocTemplate, PageTemplate
    from reportlab.platypus.frames import Frame
    from reportlab.platypus.tableofcontents import TableOfContents
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # Fuente con soporte de acentos/ñ/símbolos (DejaVu, incluida con matplotlib)
    base_font, bold_font = "Helvetica", "Helvetica-Bold"
    try:
        import matplotlib
        fd = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVu", str(fd / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(fd / "DejaVuSans-Bold.ttf")))
            pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(fd / "DejaVuSans-Oblique.ttf")))
            pdfmetrics.registerFont(TTFont("DejaVu-BoldOblique", str(fd / "DejaVuSans-BoldOblique.ttf")))
            from reportlab.pdfbase.pdfmetrics import registerFontFamily
            registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold",
                               italic="DejaVu-Oblique", boldItalic="DejaVu-BoldOblique")
        base_font, bold_font = "DejaVu", "DejaVu-Bold"
    except Exception:  # noqa: BLE001
        pass

    size = {"A4": A4, "letter": letter, "A3": A3}.get(page_size, A4)
    if landscape_mode:
        size = landscape(size)
    PW, PH = size
    theme_c = colors.HexColor(theme)
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName=base_font, fontSize=10.5, leading=15,
                          spaceAfter=6)
    H = [ParagraphStyle(f"h{i}", parent=ss[f"Heading{i}"], fontName=bold_font,
                        textColor=theme_c if i <= 2 else colors.HexColor("#222222"),
                        fontSize=[20, 16, 13, 11.5][i - 1], leading=[26, 21, 17, 15][i - 1],
                        spaceBefore=[14, 12, 9, 7][i - 1], spaceAfter=6) for i in range(1, 5)]
    quote = ParagraphStyle("quote", parent=body, leftIndent=14, textColor=colors.HexColor("#444444"),
                           borderPadding=(6, 6, 6, 10), backColor=colors.HexColor("#f4f6fa"),
                           borderColor=theme_c, borderWidth=0)
    caption = ParagraphStyle("cap", parent=body, fontSize=9, textColor=colors.HexColor("#555555"),
                             alignment=TA_CENTER, spaceBefore=3, spaceAfter=10)
    cell = ParagraphStyle("cell", parent=body, fontSize=9.2, leading=12, spaceAfter=0)
    cellh = ParagraphStyle("cellh", parent=cell, fontName=bold_font, textColor=colors.white)
    code_style = ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8.5, leading=11,
                                backColor=colors.HexColor("#f5f5f5"), borderPadding=6)

    margin = 2 * cm
    frame_w = PW - 2 * margin

    class Doc(BaseDocTemplate):
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and flowable.style.name in ("h1", "h2"):
                lvl = 0 if flowable.style.name == "h1" else 1
                self.notify("TOCEntry", (lvl, flowable.getPlainText(), self.page))

    doc = Doc(str(out), pagesize=size, leftMargin=margin, rightMargin=margin,
              topMargin=margin + 0.4 * cm, bottomMargin=margin, title=title or out.stem, author=author)

    def on_page(canv, d):
        canv.saveState()
        if d.page > (1 if cover else 0):
            canv.setStrokeColor(theme_c)
            canv.setLineWidth(1.2)
            canv.line(margin, PH - margin + 0.2 * cm, PW - margin, PH - margin + 0.2 * cm)
            canv.setFont(base_font, 8.5)
            canv.setFillColor(colors.HexColor("#555555"))
            canv.drawString(margin, PH - margin + 0.35 * cm, header_text[:110])
            canv.drawRightString(PW - margin, margin - 0.9 * cm, f"Página {d.page}")
            if author:
                canv.drawString(margin, margin - 0.9 * cm, author[:80])
        canv.restoreState()

    def on_cover(canv, d):
        canv.saveState()
        canv.setFillColor(theme_c)
        canv.rect(0, PH - 9 * cm, PW, 9 * cm, stroke=0, fill=1)
        canv.restoreState()

    frame = Frame(margin, margin, frame_w, PH - 2 * margin - 0.4 * cm, id="f")
    templates = [PageTemplate(id="normal", frames=[frame], onPage=on_page)]
    if cover:
        templates.insert(0, PageTemplate(id="cover", frames=[frame], onPage=on_cover))
    doc.addPageTemplates(templates)

    story = []
    if cover:
        from reportlab.platypus.doctemplate import NextPageTemplate
        tstyle = ParagraphStyle("ct", parent=H[0], fontSize=30, leading=36, textColor=colors.white)
        sstyle = ParagraphStyle("cs", parent=body, fontSize=14, leading=19, textColor=colors.white)
        story += [Spacer(1, 1.2 * cm)]
        if logo:
            try:
                story.append(_rl_image(ctx, logo, 4 * cm, 2.2 * cm, RLImage))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Logo: {e}")
        story += [Spacer(1, 0.6 * cm), Paragraph(_inline(title), tstyle)]
        if subtitle:
            story.append(Paragraph(_inline(subtitle), sstyle))
        story.append(Spacer(1, 3.2 * cm))
        if cover_image:
            try:
                story.append(_rl_image(ctx, cover_image, frame_w, PH * 0.42, RLImage))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Imagen de portada: {e}")
        meta = " · ".join(x for x in [author, date_text or date.today().strftime("%d/%m/%Y")] if x)
        story += [Spacer(1, 0.8 * cm), Paragraph(meta, ParagraphStyle("cm", parent=body, fontSize=12))]
        story += [NextPageTemplate("normal"), PageBreak()]
    if toc:
        t = TableOfContents()
        t.levelStyles = [ParagraphStyle("t1", parent=body, fontName=bold_font, fontSize=11, leftIndent=10),
                         ParagraphStyle("t2", parent=body, fontSize=10, leftIndent=28)]
        story += [Paragraph("Índice", H[0]), t, PageBreak()]

    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    para: list[str] = []

    def flush():
        if para:
            story.append(Paragraph(_inline(" ".join(para)), body))
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush(); i += 1; continue
        if s in ("\\pagebreak", "---pagebreak---", "<!-- pagebreak -->"):
            flush(); story.append(PageBreak()); i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            flush()
            lvl = min(4, len(m.group(1)))
            story.append(Paragraph(_inline(m.group(2)), H[lvl - 1]))
            i += 1; continue
        if s.startswith("```"):
            flush()
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                buf.append(lines[j]); j += 1
            story.append(Preformatted("\n".join(buf), code_style))
            i = j + 1; continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            flush()
            from reportlab.platypus.flowables import HRFlowable
            story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc"), spaceBefore=6, spaceAfter=6))
            i += 1; continue
        mi = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)(\{[^}]*\})?", s)
        if mi:
            flush()
            cap, src, opts = mi.group(1), mi.group(2), mi.group(3) or ""
            wm = re.search(r"width\s*=\s*(\d+)%", opts)
            frac = int(wm.group(1)) / 100 if wm else 1.0
            try:
                img = _rl_image(ctx, src, frame_w * frac, (PH - 2 * margin) * 0.62, RLImage)
                block = [img] + ([Paragraph(_inline(cap), caption)] if cap else [])
                story.append(KeepTogether(block))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"Imagen {src}: {e}")
            i += 1; continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                r = lines[i].strip().strip("|")
                cells = [c.strip() for c in r.split("|")]
                if not all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                rows = [r + [""] * (ncol - len(r)) for r in rows]
                data = [[Paragraph(_inline(c), cellh if ri == 0 else cell) for c in r] for ri, r in enumerate(rows)]
                tbl = Table(data, colWidths=[frame_w / ncol] * ncol, repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), theme_c),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8ced8")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
                story += [tbl, Spacer(1, 8)]
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            ordered = bool(re.match(r"^\d+[.)]", s))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                txt = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", lines[i])
                txt = re.sub(r"^\[( |x|X)\]\s*", lambda mm: "☑ " if mm.group(1).lower() == "x" else "☐ ", txt)
                items.append(ListItem(Paragraph(_inline(txt), body), leftIndent=14))
                i += 1
            story.append(ListFlowable(items, bulletType="1" if ordered else "bullet", start="1" if ordered else None,
                                      bulletFontName=base_font, leftIndent=14, bulletColor=theme_c))
            continue
        if s.startswith(">"):
            flush()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            story.append(Paragraph(_inline(" ".join(buf)), quote))
            continue
        para.append(s)
        i += 1
    flush()
    if not story:
        raise ToolError("El documento está vacío.")
    if toc:
        doc.multiBuild(story)
    else:
        doc.build(story)


def _rl_image(ctx, src, max_w, max_h, RLImage):
    from PIL import Image
    p = ctx.resolve(src, must_exist=True)
    if p.suffix.lower() == ".svg":
        raise ToolError("SVG no soportado en create_pdf; usa la versión PNG.")
    with Image.open(p) as im:
        w, h = im.size
    k = min(max_w / w, max_h / h)
    return RLImage(str(p), width=w * k, height=h * k)


# ============================================================ pdf_tools
@tool("pdf_tools",
      """Utilidades PDF: info, read_text (texto por páginas), to_images (renderiza páginas a PNG y te las
      muestra: úsalo para revisar tus PDFs o para leer planos en PDF), merge (unir varios PDFs),
      split (extraer páginas), images_to_pdf (convertir imágenes en un PDF).""",
      {"properties": {
          "action": {"type": "string", "enum": ["info", "read_text", "to_images", "merge", "split", "images_to_pdf"]},
          "path": {"type": "string"},
          "paths": {"type": "array", "items": {"type": "string"}},
          "pages": {"type": "string", "description": "p.ej. '1-3,5' (1-based)."},
          "output": {"type": "string"},
          "dpi": {"type": "integer"}},
       "required": ["action"]})
def pdf_tools(ctx: ToolContext, action: str, path: str | None = None, paths: list | None = None,
              pages: str | None = None, output: str | None = None, dpi: int = 110) -> ToolResult:
    import pymupdf as fitz

    if action == "merge":
        if not paths or not output:
            raise ToolError("merge necesita paths y output.")
        out = ctx.resolve(output)
        res = fitz.open()
        for p in paths:
            res.insert_pdf(fitz.open(ctx.resolve(p, must_exist=True)))
        out.parent.mkdir(parents=True, exist_ok=True)
        res.save(out)
        return ToolResult(f"Unido en {ctx.rel(out)} ({res.page_count} páginas)", files=[out])
    if action == "images_to_pdf":
        if not paths or not output:
            raise ToolError("images_to_pdf necesita paths y output.")
        from PIL import Image
        ims = [Image.open(ctx.resolve(p, must_exist=True)).convert("RGB") for p in paths]
        out = ctx.resolve(output)
        out.parent.mkdir(parents=True, exist_ok=True)
        ims[0].save(out, "PDF", save_all=True, append_images=ims[1:], resolution=150)
        return ToolResult(f"PDF {ctx.rel(out)} con {len(ims)} páginas", files=[out])

    if not path:
        raise ToolError("Falta 'path'.")
    p = ctx.resolve(path, must_exist=True)
    doc = fitz.open(p)
    sel = _parse_pages(pages, doc.page_count)
    if action == "info":
        meta = doc.metadata or {}
        sizes = {f"{pg.rect.width:.0f}x{pg.rect.height:.0f}pt" for pg in doc}
        return ToolResult(f"{ctx.rel(p)}: {doc.page_count} páginas; tamaños {sizes}; metadatos {meta}")
    if action == "read_text":
        txt = "\n\n".join(f"--- Página {i + 1} ---\n{doc[i].get_text()}" for i in sel)
        return ToolResult(truncate(txt) or "(sin texto: puede ser escaneado; usa to_images)")
    if action == "to_images":
        outdir = ctx.resolve(output) if output else ctx.ws / ".tmp" / f"{p.stem}_pages"
        outdir.mkdir(parents=True, exist_ok=True)
        files = []
        for i in sel[:12]:
            pix = doc[i].get_pixmap(dpi=dpi)
            f = outdir / f"{p.stem}_p{i + 1}.png"
            pix.save(f)
            files.append(f)
        return ToolResult(f"Páginas renderizadas en {ctx.rel(outdir)}: " + ", ".join(f.name for f in files),
                          images=files[:6], files=files)
    if action == "split":
        if not output:
            raise ToolError("split necesita output.")
        out = ctx.resolve(output)
        res = fitz.open()
        for i in sel:
            res.insert_pdf(doc, from_page=i, to_page=i)
        out.parent.mkdir(parents=True, exist_ok=True)
        res.save(out)
        return ToolResult(f"Extraídas {len(sel)} páginas en {ctx.rel(out)}", files=[out])
    raise ToolError(f"Acción desconocida: {action}")


def _parse_pages(spec: str | None, n: int) -> list[int]:
    if not spec:
        return list(range(n))
    res = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            res += list(range(int(a) - 1, min(n, int(b))))
        elif part:
            res.append(int(part) - 1)
    return [i for i in res if 0 <= i < n]
