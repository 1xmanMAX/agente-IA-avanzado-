"""Visión: ver imágenes, superponer cuadrícula de coordenadas y hacer zoom a regiones.

La cuadrícula es clave para ubicar con precisión fotos, flechas y etiquetas sobre un plano:
el modelo lee las coordenadas en píxeles ORIGINALES del archivo y las usa en compose_plan.
"""
from __future__ import annotations

import uuid

from PIL import Image, ImageDraw, ImageOps

from .base import ToolContext, ToolError, ToolResult, tool
from .drawing import load_font


@tool("view_image",
      """Mira una imagen (foto, plano, captura, gráfico). Opciones:
      - grid=true superpone una cuadrícula con coordenadas en píxeles del archivo ORIGINAL
        (úsala antes de colocar elementos sobre un plano con compose_plan).
      - cells=true superpone celdas grandes etiquetadas (A1, B2…), estilo Set-of-Mark: primero
        identifica la CELDA donde está algo y luego haz zoom con region=celda + grid=true para la
        coordenada exacta (dos niveles: más preciso que leer coordenadas en el plano entero).
      - region=[x, y, ancho, alto] hace zoom a una zona (coordenadas originales) para ver detalles.
      Devuelve también el tamaño original de la imagen.""",
      {"properties": {
          "path": {"type": "string"},
          "grid": {"type": "boolean"},
          "cells": {"type": "boolean", "description": "Celdas etiquetadas A1, B2… (localización gruesa)."},
          "cell_cols": {"type": "integer", "description": "Nº de columnas de celdas (def 8)."},
          "grid_step": {"type": "integer", "description": "Separación de la cuadrícula en px originales (auto si se omite)."},
          "region": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}},
       "required": ["path"]})
def view_image(ctx: ToolContext, path: str, grid: bool = False, grid_step: int | None = None,
               region: list | None = None, cells: bool = False, cell_cols: int = 8) -> ToolResult:
    p = ctx.resolve(path, must_exist=True)
    try:
        im = Image.open(p)
        im = ImageOps.exif_transpose(im)
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"No se pudo abrir la imagen: {e}")
    W, H = im.size
    offset = (0, 0)
    if region:
        x, y, w, h = [int(v) for v in region]
        x, y = max(0, x), max(0, y)
        im = im.crop((x, y, min(W, x + w), min(H, y + h)))
        offset = (x, y)
    info = f"{ctx.rel(p)}: tamaño original {W}x{H}px"
    if region:
        info += f"; región mostrada x={offset[0]} y={offset[1]} {im.size[0]}x{im.size[1]}"
    if grid:
        step = grid_step or _auto_step(max(im.size))
        # dibujar la cuadrícula sobre una versión escalada mantiene legibles las etiquetas
        scale = min(1.0, 1568 / max(im.size))
        disp = im.convert("RGB").resize((max(1, int(im.size[0] * scale)), max(1, int(im.size[1] * scale))))
        disp = _grid_overlay_scaled(disp, step, scale, offset)
        info += f"; cuadrícula cada {step}px (las etiquetas son coordenadas ORIGINALES)"
    elif cells:
        scale = min(1.0, 1568 / max(im.size))
        disp = im.convert("RGB").resize((max(1, int(im.size[0] * scale)), max(1, int(im.size[1] * scale))))
        disp, legend = _cells_overlay(disp, scale, offset, max(2, min(16, cell_cols)))
        info += "; celdas etiquetadas (coordenadas ORIGINALES):\n" + legend
    else:
        disp = im
    out = ctx.ws / ".tmp" / f"view_{uuid.uuid4().hex[:8]}.png"
    disp.convert("RGB").save(out)
    return ToolResult(info, images=[out])


def _cells_overlay(disp: Image.Image, scale: float, offset, cols: int):
    """Celdas grandes con etiqueta en el centro; devuelve la imagen y la tabla de límites."""
    draw = ImageDraw.Draw(disp, "RGBA")
    w, h = disp.size
    rows = max(2, round(cols * h / w))
    cw, ch = w / cols, h / rows
    font = load_font(max(12, int(min(cw, ch) / 7)), bold=True)
    ox, oy = offset
    letters = "ABCDEFGHIJKLMNOP"
    for c in range(cols + 1):
        draw.line([(c * cw, 0), (c * cw, h)], fill=(255, 0, 80, 150), width=2)
    for r in range(rows + 1):
        draw.line([(0, r * ch), (w, r * ch)], fill=(255, 0, 80, 150), width=2)
    for c in range(cols):
        for r in range(rows):
            # etiqueta pequeña en la esquina: no tapa el contenido del plano
            draw.text((c * cw + 4, r * ch + 3), f"{letters[c]}{r + 1}", font=font, anchor="la",
                      fill=(220, 0, 70, 230), stroke_width=2, stroke_fill=(255, 255, 255, 200))
    k = 1 / scale
    colspec = ", ".join(f"{letters[c]}={int(ox + c * cw * k)}–{int(ox + (c + 1) * cw * k)}" for c in range(cols))
    rowspec = ", ".join(f"{r + 1}={int(oy + r * ch * k)}–{int(oy + (r + 1) * ch * k)}" for r in range(rows))
    return disp, f"Columnas x: {colspec}\nFilas y: {rowspec}"


def _auto_step(side: int) -> int:
    for s in (25, 50, 100, 200, 250, 500, 1000):
        if side / s <= 24:
            return s
    return 2000


def _grid_overlay_scaled(disp: Image.Image, step: int, scale: float, offset) -> Image.Image:
    draw = ImageDraw.Draw(disp, "RGBA")
    w, h = disp.size
    font = load_font(max(11, min(w, h) // 65))
    ox, oy = offset
    W0 = int(w / scale) + ox
    H0 = int(h / scale) + oy
    start_x = ((ox + step - 1) // step) * step
    start_y = ((oy + step - 1) // step) * step
    for X in range(start_x, W0 + 1, step):
        x = (X - ox) * scale
        major = X % (step * 5) == 0
        draw.line([(x, 0), (x, h)], fill=(255, 0, 80, 160 if major else 80), width=2 if major else 1)
        draw.text((x + 2, 2), str(X), fill=(200, 0, 60, 255), font=font, stroke_width=2, stroke_fill="white")
    for Y in range(start_y, H0 + 1, step):
        y = (Y - oy) * scale
        major = Y % (step * 5) == 0
        draw.line([(0, y), (w, y)], fill=(0, 90, 255, 160 if major else 80), width=2 if major else 1)
        draw.text((2, y + 2), str(Y), fill=(0, 60, 200, 255), font=font, stroke_width=2, stroke_fill="white")
    return disp


@tool("image_tools",
      """Operaciones rápidas con imágenes: info (tamaño/EXIF), resize, crop, rotate, convert (formato),
      contact_sheet (hoja de contactos numerada con varias imágenes para revisarlas de un vistazo).""",
      {"properties": {
          "action": {"type": "string", "enum": ["info", "resize", "crop", "rotate", "convert", "contact_sheet"]},
          "path": {"type": "string", "description": "Imagen de entrada (no se usa en contact_sheet)."},
          "paths": {"type": "array", "items": {"type": "string"}, "description": "Para contact_sheet."},
          "output": {"type": "string"},
          "width": {"type": "integer"}, "height": {"type": "integer"},
          "box": {"type": "array", "items": {"type": "number"}, "description": "[x, y, ancho, alto] para crop"},
          "degrees": {"type": "number"}},
       "required": ["action"]})
def image_tools(ctx: ToolContext, action: str, path: str | None = None, paths: list | None = None,
                output: str | None = None, width: int | None = None, height: int | None = None,
                box: list | None = None, degrees: float = 90) -> ToolResult:
    if action == "contact_sheet":
        if not paths:
            raise ToolError("contact_sheet necesita 'paths'.")
        files = [ctx.resolve(x, must_exist=True) for x in paths]
        thumb = 320
        cols = min(4, len(files))
        rows = (len(files) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (thumb + 10) + 10, rows * (thumb + 40) + 10), "white")
        d = ImageDraw.Draw(sheet)
        font = load_font(16)
        for i, f in enumerate(files):
            im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
            im.thumbnail((thumb, thumb))
            cx = 10 + (i % cols) * (thumb + 10)
            cy = 10 + (i // cols) * (thumb + 40)
            sheet.paste(im, (cx + (thumb - im.width) // 2, cy + (thumb - im.height) // 2))
            d.text((cx, cy + thumb + 6), f"{i + 1}. {f.name[:34]}", fill="black", font=font)
        out = ctx.resolve(output) if output else ctx.ws / ".tmp" / f"sheet_{uuid.uuid4().hex[:6]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out)
        return ToolResult(f"Hoja de contactos: {ctx.rel(out)}\n" +
                          "\n".join(f"{i + 1}. {ctx.rel(f)}" for i, f in enumerate(files)),
                          images=[out], files=[out])

    if not path:
        raise ToolError("Falta 'path'.")
    p = ctx.resolve(path, must_exist=True)
    im = ImageOps.exif_transpose(Image.open(p))
    if action == "info":
        exif = {}
        try:
            raw = Image.open(p).getexif()
            exif = {k: str(v)[:80] for k, v in list(raw.items())[:20]}
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(f"{ctx.rel(p)}: {im.size[0]}x{im.size[1]} modo={im.mode} formato={Image.open(p).format} exif={exif}")
    out = ctx.resolve(output) if output else p
    out.parent.mkdir(parents=True, exist_ok=True)
    ctx.checkpoint(out)
    if action == "resize":
        if not width and not height:
            raise ToolError("resize necesita width y/o height.")
        w = width or int(im.width * height / im.height)
        h = height or int(im.height * width / im.width)
        im = im.resize((w, h), Image.LANCZOS)
    elif action == "crop":
        if not box:
            raise ToolError("crop necesita box.")
        x, y, w, h = [int(v) for v in box]
        im = im.crop((x, y, x + w, y + h))
    elif action == "rotate":
        im = im.rotate(-degrees, expand=True, fillcolor="white")
    elif action == "convert":
        if not output:
            raise ToolError("convert necesita output con la extensión deseada.")
    if out.suffix.lower() in (".jpg", ".jpeg"):
        im = im.convert("RGB")
    im.save(out)
    return ToolResult(f"Guardado {ctx.rel(out)} ({im.size[0]}x{im.size[1]})", images=[out], files=[out])
