"""Editor de planos declarativo.

El modelo describe una ESCENA en JSON (plano base + elementos) y esta herramienta la renderiza.
Así el agente puede: mirar el plano con cuadrícula, colocar fotos con flechas hacia el punto
exacto donde se tomaron, añadir conos de visión, cotas, habitaciones con área, textos, leyenda y
cajetín; luego mirar el resultado y corregir la escena (bucle de auto-verificación).

Todas las coordenadas están en PÍXELES DEL PLANO BASE (las que muestra view_image con grid=true).
Los márgenes amplían el lienzo alrededor del plano: las fotos pueden ir en coordenadas negativas
o mayores que el tamaño del plano (zona de margen) sin que cambie el sistema de coordenadas.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from . import drawing as D
from .base import ToolContext, ToolError, ToolResult, tool

ELEMENT_DOC = """
Tipos de elemento (campo "type"):
- photo: {src, anchor:[x,y] punto del plano donde se tomó/ubica, position:[x,y] esquina sup-izq de la
  miniatura o se omite para colocación automática en el margen, size: lado mayor px (def 260),
  caption, number (auto), color, view_angle: grados (0=derecha, 90=abajo) dibuja cono de visión,
  fov: apertura del cono (def 60), arrow: true/false}
- arrow: {from:[x,y], to:[x,y], color, width, label, curve (p.ej. 0.25), dashed, both}
- marker: {at:[x,y], text o number, color, radius}
- text: {at:[x,y], text, size, color, bg, bold, anchor:'mm'|'lt'}
- callout: {at:[x,y] punto señalado, text, position:[x,y] de la caja, color}
- rect / highlight: {box:[x,y,w,h], stroke, fill (p.ej. '#ff000033'), width, dashed, label}
- ellipse: {box:[x,y,w,h], stroke, fill, width, label}
- room: {points:[[x,y],...], name, fill, stroke} -> muestra nombre y área si hay escala
- polygon: {points, stroke, fill, width, dashed}
- line / wall: {points:[[x,y],...], color, width (wall def 10), dashed}
- dimension: {from, to, text (auto con escala), offset px, color}
- door: {at:[x,y] bisagra, width px, angle grados, swing: 1|-1}
- window: {from, to}
- image: {src, box:[x,y,w,h]} (logo, icono, croquis)
"""


def _pt(p, ox, oy, k=1.0):
    return (float(p[0]) * k + ox, float(p[1]) * k + oy)


@tool("compose_plan",
      """Crea o edita un PLANO/croquis anotado a partir de una escena JSON. Úsalo para: colocar fotos
      dentro/alrededor de un plano con flechas al punto exacto, numerarlas, dibujar conos de visión,
      flechas, cotas, habitaciones con área, puertas, ventanas, resaltados, textos, leyenda y cajetín.
      Flujo recomendado: (1) view_image(plano, grid=true) para leer coordenadas; (2) compose_plan;
      (3) revisa la imagen devuelta y vuelve a llamar ajustando la escena hasta que quede perfecto.
      La escena se guarda como <output>.scene.json para poder editarla después (scene_path).
      Sin 'base' se crea un plano desde cero sobre un lienzo en blanco ('canvas')."""
      + ELEMENT_DOC,
      {"properties": {
          "output": {"type": "string", "description": "PNG de salida, p.ej. plans/plano_fotos.png"},
          "base": {"type": "string", "description": "Imagen del plano base (png/jpg) o PDF (se usa la página 'page')."},
          "page": {"type": "integer", "description": "Página del PDF base (1-based)."},
          "scene_path": {"type": "string", "description": "Cargar una escena guardada y aplicar cambios encima."},
          "canvas": {"type": "object", "description": "{width, height, background} si no hay base."},
          "margin": {"description": "Número o {left,right,top,bottom} en px de margen alrededor del plano."},
          "upscale": {"type": "number", "description": "Factor de ampliación del plano base (planos pequeños)."},
          "scale": {"type": "object", "description": "{px_per_meter: n} para cotas y áreas automáticas."},
          "elements": {"type": "array", "items": {"type": "object"}},
          "legend": {"type": "boolean", "description": "Leyenda con fotos numeradas (def true si hay fotos)."},
          "legend_items": {"type": "array", "items": {"type": "object"}, "description": "[{color, text}] extra."},
          "title_block": {"type": "object", "description": "{title, subtitle, author, date, scale_text, logo}"},
          "theme_color": {"type": "string"},
          "pdf": {"type": "boolean", "description": "Exportar también a PDF."}},
       "required": ["output"]})
def compose_plan(ctx: ToolContext, output: str, **scene) -> ToolResult:
    if scene.get("scene_path"):
        sp = ctx.resolve(scene.pop("scene_path"), must_exist=True)
        saved = json.loads(sp.read_text("utf-8"))
        saved.update({k: v for k, v in scene.items() if v is not None})
        scene = saved
    out = ctx.resolve(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img, report = render_scene(ctx, scene)
    img.convert("RGB").save(out, quality=95)
    files = [out]
    scene_file = out.with_suffix(".scene.json")
    scene_file.write_text(json.dumps({k: v for k, v in scene.items() if k != "output"},
                                     indent=2, ensure_ascii=False), "utf-8")
    files.append(scene_file)
    if scene.get("pdf"):
        pdf = out.with_suffix(".pdf")
        img.convert("RGB").save(pdf, "PDF", resolution=150)
        files.append(pdf)
    msg = (f"Plano renderizado: {ctx.rel(out)} ({img.width}x{img.height}px). Escena: {ctx.rel(scene_file)}.\n"
           + report + "\nRevisa la imagen: si algo se solapa o una flecha no apunta bien, ajusta y repite.")
    return ToolResult(msg, images=[out], files=files)


# ---------------------------------------------------------------------------
def _load_base(ctx: ToolContext, scene: dict) -> Image.Image:
    base = scene.get("base")
    if base:
        p = ctx.resolve(base, must_exist=True)
        if p.suffix.lower() == ".pdf":
            try:
                import pymupdf as fitz
            except ImportError:
                raise ToolError("Para usar un PDF como plano base instala pymupdf, o conviértelo antes a imagen.")
            doc = fitz.open(p)
            page = doc[max(0, int(scene.get("page", 1)) - 1)]
            pix = page.get_pixmap(dpi=150)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        else:
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGBA")
        k = float(scene.get("upscale") or 1)
        if k != 1:
            im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
        return im.convert("RGBA")
    cv = scene.get("canvas") or {}
    return Image.new("RGBA", (int(cv.get("width", 2000)), int(cv.get("height", 1400))),
                     D.color(cv.get("background", "white")))


def _margins(scene: dict, photos_auto: bool, size: int) -> dict:
    m = scene.get("margin")
    if m is None:
        # por defecto las fotos automáticas van a izquierda y derecha del plano
        side = size + 90 if photos_auto else 40
        return {"left": side, "right": side, "top": 50, "bottom": 70}
    if isinstance(m, (int, float)):
        return {"left": int(m), "right": int(m), "top": int(m), "bottom": int(m)}
    return {k: int(m.get(k, 40)) for k in ("left", "right", "top", "bottom")}


def render_scene(ctx: ToolContext, scene: dict) -> tuple[Image.Image, str]:
    elements = list(scene.get("elements") or [])
    k = float(scene.get("upscale") or 1)  # las coordenadas del usuario son del plano original
    base = _load_base(ctx, scene)
    photos = [e for e in elements if e.get("type") == "photo"]
    default_size = int(max([e.get("size", 260) for e in photos] or [260]))
    auto = any(not e.get("position") for e in photos)
    M = _margins(scene, auto, default_size)
    theme = scene.get("theme_color", "#e6194b")

    # numeración y colores automáticos de fotos
    n = 0
    for e in photos:
        n += 1
        e.setdefault("number", n)
        e.setdefault("color", D.PALETTE[(e["number"] - 1) % len(D.PALETTE)] if scene.get("multicolor") else theme)

    tb = scene.get("title_block")
    show_legend = scene.get("legend", bool(photos)) and (photos or scene.get("legend_items"))
    legend_lines = _legend_lines(photos, scene.get("legend_items"))
    font_sz = max(16, int(min(base.width, base.height) / 55))
    legend_h = 0
    if show_legend or tb:
        legend_h = max(150 if tb else 0, 60 + 34 * math.ceil(len(legend_lines) / 2)) if legend_lines else 170

    W = base.width + M["left"] + M["right"]
    H = base.height + M["top"] + M["bottom"] + legend_h
    # Lienzo RGB: así los rellenos semitransparentes se MEZCLAN con el plano (en RGBA lo reemplazarían)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    canvas.paste(base, (M["left"], M["top"]), base)
    ox, oy = M["left"], M["top"]
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = D.load_font(font_sz)
    bold = D.load_font(font_sz, bold=True)
    scale = (scene.get("scale") or {}).get("px_per_meter")
    notes: list[str] = []

    # colocación automática de las miniaturas en los márgenes
    plan_box = (ox, oy, ox + base.width, oy + base.height)
    placed = _auto_place(ctx, photos, plan_box, M, k, ox, oy, notes)

    # 1) geometría (debajo)
    order = {"room": 0, "highlight": 1, "rect": 1, "ellipse": 1, "polygon": 1, "wall": 2, "line": 2,
             "window": 2, "door": 2, "dimension": 3, "image": 3, "arrow": 4, "marker": 5,
             "callout": 6, "text": 6, "photo": 7}
    for e in sorted(elements, key=lambda e: order.get(e.get("type"), 5)):
        t = e.get("type")
        try:
            if t == "photo":
                continue
            _draw_element(ctx, canvas, draw, e, ox, oy, k, font, bold, scale, theme, notes)
        except ToolError:
            raise
        except Exception as ex:  # noqa: BLE001
            notes.append(f"Elemento {t} con error: {ex}")

    # 2) fotos (arriba): cono, flecha, miniatura, número
    for e, box in placed:
        _draw_photo(ctx, canvas, draw, e, box, ox, oy, k, font_sz)

    # 3) leyenda + cajetín
    if legend_h:
        _draw_footer(ctx, canvas, draw, legend_lines if show_legend else [], tb, scene,
                     (0, H - legend_h, W, H), font_sz, theme)

    report = f"Lienzo {W}x{H}; márgenes {M}; {len(photos)} foto(s); {len(elements)} elemento(s)."
    if notes:
        report += "\nAvisos:\n- " + "\n- ".join(notes)
    return canvas, report


def _legend_lines(photos, extra):
    lines = []
    for e in photos:
        cap = e.get("caption") or Path(str(e.get("src", ""))).stem
        lines.append((e.get("color"), f"{e['number']}. {cap}", True))
    for it in extra or []:
        lines.append((it.get("color", "#333"), it.get("text", ""), False))
    return lines


def _auto_place(ctx, photos, plan_box, M, k, ox, oy, notes):
    """Coloca miniaturas: las que tienen position se respetan; el resto se reparte por los márgenes
    en el lado más cercano a su anchor, ordenadas para que las flechas no se crucen."""
    px0, py0, px1, py1 = plan_box
    cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
    result = []
    sides = {"left": [], "right": [], "top": [], "bottom": []}
    for e in photos:
        im_size = _thumb_size(ctx, e)
        if e.get("position"):
            x, y = _pt(e["position"], ox, oy, k)
            result.append((e, (x, y, x + im_size[0], y + im_size[1])))
            continue
        ax, ay = _pt(e.get("anchor", [0, 0]), ox, oy, k)
        # elegir el lado: distancia normalizada al borde con margen disponible
        cands = []
        if M["left"] > 120: cands.append(("left", (ax - px0) / max(1, px1 - px0)))
        if M["right"] > 120: cands.append(("right", (px1 - ax) / max(1, px1 - px0)))
        if M["top"] > 120: cands.append(("top", (ay - py0) / max(1, py1 - py0)))
        if M["bottom"] > 120: cands.append(("bottom", (py1 - ay) / max(1, py1 - py0)))
        side = min(cands, key=lambda c: c[1])[0] if cands else "right"
        sides[side].append((e, im_size, ax, ay))
    gap = 18
    for side, items in sides.items():
        if not items:
            continue
        vertical = side in ("left", "right")
        items.sort(key=lambda it: it[3] if vertical else it[2])
        total = sum((it[1][1] if vertical else it[1][0]) + gap for it in items) - gap
        span = (py1 - py0) if vertical else (px1 - px0)
        if total > span + (M["top"] + M["bottom"] if vertical else M["left"] + M["right"]) - 20:
            notes.append(f"Demasiadas fotos en el margen {side}; reduce 'size' o aumenta 'margin'.")
        # posición ideal = alineada con su anchor; luego resolver solapes barriendo
        pos = []
        for e, (tw, th), ax, ay in items:
            ideal = (ay - th / 2) if vertical else (ax - tw / 2)
            pos.append(ideal)
        lo = (py0 - M["top"] + 10) if vertical else (px0 - M["left"] + 10)
        hi_lim = (py1 + M["bottom"] - 10) if vertical else (px1 + M["right"] - 10)
        cur = lo
        for i, (e, (tw, th), ax, ay) in enumerate(items):
            length = th if vertical else tw
            pos[i] = max(pos[i], cur)
            cur = pos[i] + length + gap
        overflow = cur - gap - hi_lim
        if overflow > 0:  # desplazar hacia atrás si nos salimos
            for i in range(len(items) - 1, -1, -1):
                length = items[i][1][1] if vertical else items[i][1][0]
                limit = hi_lim if i == len(items) - 1 else pos[i + 1] - gap
                pos[i] = min(pos[i], limit - length)
        for (e, (tw, th), ax, ay), p in zip(items, pos):
            if side == "left":
                x = px0 - M["left"] + (M["left"] - tw) / 2
                box = (x, p, x + tw, p + th)
            elif side == "right":
                x = px1 + (M["right"] - tw) / 2
                box = (x, p, x + tw, p + th)
            elif side == "top":
                y = py0 - M["top"] + (M["top"] - th) / 2
                box = (p, y, p + tw, y + th)
            else:
                y = py1 + (M["bottom"] - th) / 2
                box = (p, y, p + tw, y + th)
            result.append((e, box))
    return result


_thumb_cache: dict = {}


def _thumb(ctx, e) -> Image.Image:
    src = ctx.resolve(e.get("src"), must_exist=True)
    size = int(e.get("size", 260))
    key = (str(src), size)
    if key not in _thumb_cache:
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        _thumb_cache[key] = im
    return _thumb_cache[key]


def _thumb_size(ctx, e):
    im = _thumb(ctx, e)
    cap_h = 0
    return im.width + 12, im.height + 12 + cap_h


def _draw_photo(ctx, canvas, draw, e, box, ox, oy, k, font_sz):
    col = D.color(e.get("color"))
    x0, y0, x1, y1 = box
    anchor = e.get("anchor")
    if anchor is not None:
        ax, ay = _pt(anchor, ox, oy, k)
        if e.get("view_angle") is not None:
            ang = math.radians(float(e["view_angle"]))
            fov = math.radians(float(e.get("fov", 60)))
            r = float(e.get("cone_length", max(60, font_sz * 5)))
            pts = [(ax, ay)] + [(ax + r * math.cos(ang + t), ay + r * math.sin(ang + t))
                                for t in [(-fov / 2) + fov * i / 12 for i in range(13)]]
            draw.polygon(pts, fill=col[:3] + (70,), outline=col)
        r_mark = max(14, font_sz * 0.8)
        if e.get("arrow", True):
            start = D.edge_point_towards(box, (ax, ay))
            # la punta se detiene en el borde del marcador para que se vea
            dist = math.dist(start, (ax, ay)) or 1
            end = (ax - (ax - start[0]) * r_mark / dist, ay - (ay - start[1]) * r_mark / dist)
            D.arrow(draw, start, end, fill=col, width=max(3, font_sz // 6), curve=float(e.get("curve", 0)))
        D.numbered_marker(draw, (ax, ay), e["number"], fill=col, radius=r_mark)
    # miniatura con marco
    thumb = _thumb(ctx, e)
    draw.rectangle([x0 + 4, y0 + 4, x1 + 4, y1 + 4], fill=(0, 0, 0, 50))  # sombra
    draw.rectangle([x0, y0, x1, y1], fill="white", outline=col, width=4)
    canvas.paste(thumb, (int(x0 + 6), int(y0 + 6)))
    draw = ImageDraw.Draw(canvas, "RGBA")
    D.numbered_marker(draw, (x0 + 4, y0 + 4), e["number"], fill=col, radius=max(14, font_sz * 0.8))
    if e.get("caption") and e.get("caption_on_photo", True):
        f = D.load_font(max(13, int(font_sz * 0.8)))
        cap = str(e["caption"])[:60]
        D.label_box(draw, ((x0 + x1) / 2, y1 - 6 - font_sz * 0.6), cap, f, fg="white", bg=col[:3] + (220,), pad=4)


def _draw_element(ctx, canvas, draw, e, ox, oy, k, font, bold, scale, theme, notes):
    t = e.get("type")
    col = e.get("color") or e.get("stroke") or theme
    width = int(e.get("width", 4))
    if t == "arrow":
        a, b = _pt(e["from"], ox, oy, k), _pt(e["to"], ox, oy, k)
        D.arrow(draw, a, b, fill=col, width=width, both=e.get("both", False),
                dashed=e.get("dashed", False), curve=float(e.get("curve", 0)))
        if e.get("label"):
            D.label_box(draw, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), e["label"], font,
                        fg=col, border=col)
    elif t == "marker":
        D.numbered_marker(draw, _pt(e["at"], ox, oy, k), e.get("text", e.get("number", "•")),
                          fill=col, radius=int(e.get("radius", 18)))
    elif t == "text":
        f = D.load_font(int(e.get("size", font.size)), bold=e.get("bold", False))
        x, y = _pt(e["at"], ox, oy, k)
        if e.get("bg"):
            D.label_box(draw, (x, y), e["text"], f, fg=e.get("color", "#111"), bg=e["bg"],
                        anchor=e.get("anchor", "mm"))
        else:
            draw.multiline_text((x, y), e["text"], font=f, fill=D.color(e.get("color", "#111")),
                                anchor=e.get("anchor", "mm") if "\n" not in e["text"] else "la",
                                stroke_width=e.get("outline", 0), stroke_fill="white")
    elif t == "callout":
        at = _pt(e["at"], ox, oy, k)
        pos = _pt(e.get("position", [e["at"][0] + 120, e["at"][1] - 80]), ox, oy, k)
        tw, th = D.text_size(draw, e["text"], font)
        box = [pos[0], pos[1], pos[0] + tw + 16, pos[1] + th + 16]
        start = D.edge_point_towards(box, at)
        D.arrow(draw, start, at, fill=col, width=3)
        D.label_box(draw, (pos[0], pos[1]), e["text"], font, fg="#111", border=col, anchor="lt", pad=8)
    elif t in ("rect", "highlight", "ellipse"):
        x, y, w, h = e["box"]
        x0, y0 = _pt((x, y), ox, oy, k)
        x1, y1 = _pt((x + w, y + h), ox, oy, k)
        fill = D.color(e["fill"]) if e.get("fill") else (D.color(col, 0.18) if t == "highlight" else None)
        if t == "ellipse":
            draw.ellipse([x0, y0, x1, y1], outline=D.color(col), fill=fill, width=width)
        elif e.get("dashed"):
            if fill:
                draw.rectangle([x0, y0, x1, y1], fill=fill)
            D.dashed_line(draw, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], col, width)
        else:
            draw.rectangle([x0, y0, x1, y1], outline=D.color(col), fill=fill, width=width)
        if e.get("label"):
            D.label_box(draw, ((x0 + x1) / 2, y0 - font.size), e["label"], font, fg=col, border=col)
    elif t in ("polygon", "room"):
        pts = [_pt(p, ox, oy, k) for p in e["points"]]
        fill = D.color(e["fill"]) if e.get("fill") else (D.color(col, 0.12) if t == "room" else None)
        draw.polygon(pts, fill=fill, outline=D.color(e.get("stroke", col)), width=width if t == "polygon" else 2)
        if e.get("dashed"):
            D.dashed_line(draw, pts + [pts[0]], col, width)
        if t == "room":
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            label = e.get("name", "")
            if scale:
                area = _poly_area(e["points"]) / (scale ** 2)
                label += f"\n{area:.2f} m²"
            if label:
                draw.multiline_text((cx, cy), label, font=bold, fill=D.color(e.get("text_color", "#222")),
                                    anchor="mm", align="center", stroke_width=3, stroke_fill="white")
    elif t in ("line", "wall"):
        pts = [_pt(p, ox, oy, k) for p in e["points"]]
        w = int(e.get("width", 10 if t == "wall" else 4))
        c = e.get("color", "#222" if t == "wall" else col)
        if e.get("dashed"):
            D.dashed_line(draw, pts, c, w)
        else:
            draw.line(pts, fill=D.color(c), width=w, joint="curve")
            if t == "wall":
                for p in pts:
                    draw.rectangle([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=D.color(c))
    elif t == "dimension":
        a, b = _pt(e["from"], ox, oy, k), _pt(e["to"], ox, oy, k)
        off = float(e.get("offset", 30))
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        nx, ny = -math.sin(ang) * off, math.cos(ang) * off
        a2, b2 = (a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny)
        c = e.get("color", "#333")
        draw.line([a, a2], fill=D.color(c), width=1)
        draw.line([b, b2], fill=D.color(c), width=1)
        D.arrow(draw, a2, b2, fill=c, width=2, both=True, head=12)
        txt = e.get("text")
        if not txt and scale:
            dist = math.dist(e["from"], e["to"]) / scale
            txt = f"{dist:.2f} m"
        if txt:
            D.label_box(draw, ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2), txt, font, fg=c, pad=3)
    elif t == "door":
        hx, hy = _pt(e["at"], ox, oy, k)
        r = float(e.get("width", 80)) * k
        ang = math.radians(float(e.get("angle", 0)))
        sw = float(e.get("swing", 1))
        end = (hx + r * math.cos(ang), hy + r * math.sin(ang))
        leaf = (hx + r * math.cos(ang + sw * math.pi / 2), hy + r * math.sin(ang + sw * math.pi / 2))
        draw.line([(hx, hy), leaf], fill=D.color("#222"), width=3)
        a0, a1 = sorted([math.degrees(ang), math.degrees(ang + sw * math.pi / 2)])
        draw.arc([hx - r, hy - r, hx + r, hy + r], a0, a1, fill=D.color("#555"), width=2)
        draw.line([(hx, hy), end], fill=(255, 255, 255, 255), width=1)
    elif t == "window":
        a, b = _pt(e["from"], ox, oy, k), _pt(e["to"], ox, oy, k)
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        nx, ny = -math.sin(ang) * 5, math.cos(ang) * 5
        draw.line([a, b], fill="white", width=12)
        for s in (-1, 1):
            draw.line([(a[0] + s * nx, a[1] + s * ny), (b[0] + s * nx, b[1] + s * ny)], fill=D.color("#1f77b4"), width=2)
    elif t == "image":
        src = ctx.resolve(e["src"], must_exist=True)
        x, y, w, h = e["box"]
        x0, y0 = _pt((x, y), ox, oy, k)
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
        im.thumbnail((int(w * k), int(h * k)), Image.LANCZOS)
        canvas.paste(im, (int(x0), int(y0)), im)
    else:
        notes.append(f"Tipo de elemento desconocido: {t}")


def _poly_area(pts):
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def _draw_footer(ctx, canvas, draw, lines, tb, scene, box, font_sz, theme):
    x0, y0, x1, y1 = box
    draw.line([(x0 + 20, y0 + 8), (x1 - 20, y0 + 8)], fill=D.color("#999"), width=2)
    font = D.load_font(max(14, int(font_sz * 0.9)))
    bold = D.load_font(max(15, int(font_sz)), bold=True)
    tb_w = 0
    if tb:
        tb_w = min(620, (x1 - x0) // 2)
        bx0, by0, bx1, by1 = x1 - tb_w - 20, y0 + 22, x1 - 20, y1 - 16
        draw.rectangle([bx0, by0, bx1, by1], outline=D.color("#333"), width=3)
        draw.rectangle([bx0, by0, bx1, by0 + font_sz * 2.2], fill=D.color(tb.get("color", theme)))
        draw.text((bx0 + 12, by0 + font_sz * 0.35), tb.get("title", "Plano"), font=bold, fill="white")
        yy = by0 + font_sz * 2.5
        info = [tb.get("subtitle"), tb.get("author") and f"Autor: {tb['author']}",
                f"Fecha: {tb.get('date') or date.today().isoformat()}",
                tb.get("scale_text") and f"Escala: {tb['scale_text']}"]
        for line in [i for i in info if i]:
            draw.text((bx0 + 12, yy), line, font=font, fill="#222")
            yy += font_sz * 1.35
        if tb.get("logo"):
            try:
                logo = Image.open(ctx.resolve(tb["logo"], must_exist=True)).convert("RGBA")
                logo.thumbnail((int(tb_w * 0.3), int((by1 - by0) * 0.55)))
                canvas.paste(logo, (int(bx1 - logo.width - 10), int(by1 - logo.height - 10)), logo)
            except Exception:  # noqa: BLE001
                pass
    if lines:
        draw.text((x0 + 30, y0 + 22), "Leyenda", font=bold, fill="#222")
        col_w = (x1 - x0 - tb_w - 80) / 2
        for i, (c, text, is_num) in enumerate(lines):
            cx = x0 + 30 + (i % 2) * col_w
            cy = y0 + 22 + font_sz * 1.8 + (i // 2) * 34
            draw.rounded_rectangle([cx, cy + 2, cx + 22, cy + 22], radius=5, fill=D.color(c))
            draw.text((cx + 32, cy), text[:70], font=font, fill="#222")
