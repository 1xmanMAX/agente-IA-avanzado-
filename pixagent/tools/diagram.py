"""Diagramas: diagramas de flujo, organigramas, arquitecturas, mapas de procesos.

Disposición automática por capas (tipo Sugiyama simplificado) y salida PNG + SVG (+ PDF opcional),
sin dependencias externas como Graphviz. También puede generar un HTML con Mermaid.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from . import drawing as D
from .base import ToolContext, ToolError, ToolResult, tool

SHAPES = ("box", "round", "diamond", "ellipse", "circle", "parallelogram", "cylinder", "note")


@tool("render_diagram",
      """Dibuja un diagrama (flujo, proceso, organigrama, arquitectura, árbol, estados) con disposición
      automática. Nodos: {id, label, shape: box|round|diamond|ellipse|circle|parallelogram|cylinder|note,
      color (relleno), group}. Aristas: {from, to, label, dashed, color}. direction: TB (arriba-abajo)
      o LR (izquierda-derecha). Genera PNG y SVG (y PDF si pdf=true). Alternativa: 'mermaid' con código
      Mermaid -> genera un HTML interactivo (ver en el navegador o con preview_page).""",
      {"properties": {
          "output": {"type": "string", "description": "Ruta base sin extensión o .png, p.ej. diagrams/proceso"},
          "title": {"type": "string"},
          "direction": {"type": "string", "enum": ["TB", "LR"]},
          "nodes": {"type": "array", "items": {"type": "object"}},
          "edges": {"type": "array", "items": {"type": "object"}},
          "groups": {"type": "array", "items": {"type": "object"},
                     "description": "[{id, label, color}] para agrupar nodos con el campo 'group'."},
          "theme_color": {"type": "string"},
          "mermaid": {"type": "string", "description": "Código Mermaid (alternativa a nodes/edges)."},
          "pdf": {"type": "boolean"}},
       "required": ["output"]})
def render_diagram(ctx: ToolContext, output: str, title: str = "", direction: str = "TB",
                   nodes: list | None = None, edges: list | None = None, groups: list | None = None,
                   theme_color: str = "#1f77b4", mermaid: str | None = None, pdf: bool = False) -> ToolResult:
    out = ctx.resolve(output)
    stem = out.with_suffix("") if out.suffix else out
    stem.parent.mkdir(parents=True, exist_ok=True)
    for ext in (".png", ".svg", ".pdf", ".html", ".diagram.json"):
        ctx.checkpoint(stem.with_suffix(ext))
    if mermaid:
        page = stem.with_suffix(".html")
        page.write_text(MERMAID_HTML.replace("{{TITLE}}", html.escape(title or "Diagrama"))
                        .replace("{{CODE}}", html.escape(mermaid)), "utf-8")
        return ToolResult(f"HTML Mermaid creado: {ctx.rel(page)}. Usa preview_page para verlo/convertirlo a PNG.",
                          files=[page])
    if not nodes:
        raise ToolError("Necesito 'nodes' (o 'mermaid').")
    layout = layout_graph(nodes, edges or [], direction)
    png = stem.with_suffix(".png")
    img = draw_png(layout, nodes, edges or [], groups or [], title, theme_color, direction)
    img.save(png)
    svg = stem.with_suffix(".svg")
    svg.write_text(draw_svg(layout, nodes, edges or [], groups or [], title, theme_color, direction), "utf-8")
    files = [png, svg]
    if pdf:
        p = stem.with_suffix(".pdf")
        img.convert("RGB").save(p, "PDF", resolution=150)
        files.append(p)
    stem.with_suffix(".diagram.json").write_text(json.dumps(
        {"title": title, "direction": direction, "nodes": nodes, "edges": edges, "groups": groups},
        ensure_ascii=False, indent=2), "utf-8")
    return ToolResult(f"Diagrama: {', '.join(ctx.rel(f) for f in files)}. Revisa la imagen y ajusta si hace falta.",
                      images=[png], files=files)


# ---------------------------------------------------------------- layout
NODE_W, NODE_H, GAP_X, GAP_Y = 230, 84, 70, 90


def layout_graph(nodes, edges, direction="TB"):
    ids = [n["id"] for n in nodes]
    idset = set(ids)
    out_e = defaultdict(list)
    for e in edges:
        if e.get("from") in idset and e.get("to") in idset:
            out_e[e["from"]].append(e["to"])
    # romper ciclos con DFS
    state, back = {}, set()

    def dfs(u):
        state[u] = 1
        for v in out_e[u]:
            if state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                dfs(v)
        state[u] = 2
    for i in ids:
        if i not in state:
            dfs(i)
    dag = defaultdict(list)
    indeg = defaultdict(int)
    for u in ids:
        for v in out_e[u]:
            if (u, v) not in back and u != v:
                dag[u].append(v)
                indeg[v] += 1
    # rango = camino más largo desde las raíces
    rank = {i: 0 for i in ids}
    queue = [i for i in ids if indeg[i] == 0]
    indeg2 = dict(indeg)
    while queue:
        u = queue.pop(0)
        for v in dag[u]:
            rank[v] = max(rank[v], rank[u] + 1)
            indeg2[v] -= 1
            if indeg2[v] == 0:
                queue.append(v)
    layers = defaultdict(list)
    for i in ids:
        layers[rank[i]].append(i)
    # orden por baricentro (varias pasadas)
    preds = defaultdict(list)
    for u in ids:
        for v in dag[u]:
            preds[v].append(u)
    order = {i: idx for r in layers for idx, i in enumerate(layers[r])}
    for _ in range(6):
        for r in sorted(layers)[1:]:
            layers[r].sort(key=lambda v: (sum(order[p] for p in preds[v]) / len(preds[v])) if preds[v] else order[v])
            for idx, v in enumerate(layers[r]):
                order[v] = idx
    sizes = {}
    for n in nodes:
        lines = str(n.get("label", n["id"])).split("\n")
        w = max(NODE_W, min(420, 14 * max(len(l) for l in lines) + 40))
        h = max(NODE_H, 30 * len(lines) + 30)
        if n.get("shape") == "diamond":
            w, h = w * 1.25, h * 1.35
        sizes[n["id"]] = (w, h)
    pos = {}
    nlayers = max(layers) + 1 if layers else 1
    maxw = max((sum(sizes[i][0 if direction == "TB" else 1] for i in layers[r]) +
                GAP_X * (len(layers[r]) - 1)) for r in layers)
    cursor = 0.0
    for r in range(nlayers):
        row = layers[r]
        thick = max((sizes[i][1 if direction == "TB" else 0] for i in row), default=NODE_H)
        total = sum(sizes[i][0 if direction == "TB" else 1] for i in row) + GAP_X * (len(row) - 1)
        s = (maxw - total) / 2
        for i in row:
            w, h = sizes[i]
            if direction == "TB":
                pos[i] = (s + w / 2, cursor + thick / 2)
                s += w + GAP_X
            else:
                pos[i] = (cursor + thick / 2, s + h / 2)
                s += h + GAP_X
        cursor += thick + GAP_Y + (40 if direction == "LR" else 0)
    return {"pos": pos, "sizes": sizes, "back": back}


def _bbox(layout, pad=60, title_h=0):
    xs, ys = [], []
    for i, (x, y) in layout["pos"].items():
        w, h = layout["sizes"][i]
        xs += [x - w / 2, x + w / 2]
        ys += [y - h / 2, y + h / 2]
    return min(xs) - pad, min(ys) - pad - title_h, max(xs) + pad, max(ys) + pad


def _shape_poly(shape, x, y, w, h):
    if shape == "diamond":
        return [(x, y - h / 2), (x + w / 2, y), (x, y + h / 2), (x - w / 2, y)]
    if shape == "parallelogram":
        s = w * 0.12
        return [(x - w / 2 + s, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2 - s, y + h / 2), (x - w / 2, y + h / 2)]
    return None


def _boundary(layout, nid, shape, target):
    """Punto del contorno real del nodo (caja, rombo o elipse) en dirección a target."""
    x, y = layout["pos"][nid]
    w, h = layout["sizes"][nid]
    dx, dy = target[0] - x, target[1] - y
    if dx == 0 and dy == 0:
        return x, y
    if shape == "diamond":
        k = 1 / (abs(dx) / (w / 2) + abs(dy) / (h / 2))
        return x + dx * k, y + dy * k
    if shape in ("ellipse", "circle"):
        k = 1 / ((dx / (w / 2)) ** 2 + (dy / (h / 2)) ** 2) ** 0.5
        return x + dx * k, y + dy * k
    return D.edge_point_towards((x - w / 2, y - h / 2, x + w / 2, y + h / 2), target)


def _edge_points(layout, a, b, direction, shapes=None):
    shapes = shapes or {}
    pa, pb = layout["pos"][a], layout["pos"][b]
    return _boundary(layout, a, shapes.get(a), pb), _boundary(layout, b, shapes.get(b), pa)


def draw_png(layout, nodes, edges, groups, title, theme, direction, scale=2):
    title_h = 70 if title else 0
    x0, y0, x1, y1 = _bbox(layout, title_h=title_h)
    W, H = int((x1 - x0) * scale), int((y1 - y0) * scale)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img, "RGBA")
    T = lambda p: ((p[0] - x0) * scale, (p[1] - y0) * scale)  # noqa: E731
    font = D.load_font(int(17 * scale))
    bold = D.load_font(int(26 * scale), bold=True)
    small = D.load_font(int(14 * scale))
    if title:
        d.text((W / 2, 30 * scale), title, font=bold, fill="#111", anchor="mm")
    nmap = {n["id"]: n for n in nodes}
    # grupos
    gmap = {g["id"]: g for g in groups}
    members = defaultdict(list)
    for n in nodes:
        if n.get("group"):
            members[n["group"]].append(n["id"])
    for gid, ids in members.items():
        g = gmap.get(gid, {"label": gid})
        bx = [layout["pos"][i][0] - layout["sizes"][i][0] / 2 - 20 for i in ids]
        by = [layout["pos"][i][1] - layout["sizes"][i][1] / 2 - 34 for i in ids]
        ex = [layout["pos"][i][0] + layout["sizes"][i][0] / 2 + 20 for i in ids]
        ey = [layout["pos"][i][1] + layout["sizes"][i][1] / 2 + 20 for i in ids]
        a, b = T((min(bx), min(by))), T((max(ex), max(ey)))
        c = D.color(g.get("color", "#888"))
        d.rounded_rectangle([a, b], radius=16 * scale, fill=c[:3] + (28,), outline=c, width=2 * scale)
        d.text((a[0] + 12 * scale, a[1] + 6 * scale), g.get("label", gid), font=small, fill=c)
    # aristas
    for e in edges:
        if e.get("from") not in nmap or e.get("to") not in nmap:
            continue
        s, t = _edge_points(layout, e["from"], e["to"], direction, {n["id"]: n.get("shape", "round") for n in nodes})
        col = e.get("color", "#555")
        curve = 0.25 if (e["from"], e["to"]) in layout["back"] else 0
        D.arrow(d, T(s), T(t), fill=col, width=2 * scale, head=11 * scale,
                dashed=e.get("dashed", False), curve=curve)
        if e.get("label"):
            m = T(((s[0] + t[0]) / 2, (s[1] + t[1]) / 2))
            D.label_box(d, m, e["label"], small, fg="#333", bg="#ffffffee", pad=3 * scale)
    # nodos
    for n in nodes:
        x, y = layout["pos"][n["id"]]
        w, h = layout["sizes"][n["id"]]
        shape = n.get("shape", "round")
        fill = D.color(n.get("color", theme), 0.16 if not n.get("solid") else None)
        line = D.color(n.get("border", n.get("color", theme)))
        (ax, ay), (bx2, by2) = T((x - w / 2, y - h / 2)), T((x + w / 2, y + h / 2))
        poly = _shape_poly(shape, x, y, w, h)
        if poly:
            d.polygon([T(p) for p in poly], fill=fill, outline=line, width=3 * scale)
        elif shape in ("ellipse", "circle"):
            d.ellipse([ax, ay, bx2, by2], fill=fill, outline=line, width=3 * scale)
        elif shape == "box":
            d.rectangle([ax, ay, bx2, by2], fill=fill, outline=line, width=3 * scale)
        elif shape == "cylinder":
            e_h = 14 * scale
            d.rectangle([ax, ay + e_h, bx2, by2 - e_h], fill=fill)
            d.ellipse([ax, by2 - 2 * e_h, bx2, by2], fill=fill, outline=line, width=3 * scale)
            d.line([(ax, ay + e_h), (ax, by2 - e_h)], fill=line, width=3 * scale)
            d.line([(bx2, ay + e_h), (bx2, by2 - e_h)], fill=line, width=3 * scale)
            d.ellipse([ax, ay, bx2, ay + 2 * e_h], fill=fill, outline=line, width=3 * scale)
        elif shape == "note":
            f = 18 * scale
            d.polygon([(ax, ay), (bx2 - f, ay), (bx2, ay + f), (bx2, by2), (ax, by2)], fill=D.color("#fff7c2"), outline=line, width=2 * scale)
        else:
            d.rounded_rectangle([ax, ay, bx2, by2], radius=18 * scale, fill=fill, outline=line, width=3 * scale)
        d.multiline_text(T((x, y)), str(n.get("label", n["id"])), font=font, fill="#111",
                         anchor="mm", align="center")
    return img


def draw_svg(layout, nodes, edges, groups, title, theme, direction):
    title_h = 70 if title else 0
    x0, y0, x1, y1 = _bbox(layout, title_h=title_h)
    W, H = x1 - x0, y1 - y0
    esc = html.escape
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" '
           f'font-family="Segoe UI, Arial, sans-serif">',
           '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
           '<path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker></defs>',
           f'<rect width="100%" height="100%" fill="white"/>']
    if title:
        out.append(f'<text x="{W / 2:.0f}" y="38" text-anchor="middle" font-size="26" font-weight="bold">{esc(title)}</text>')
    nmap = {n["id"]: n for n in nodes}
    for e in edges:
        if e.get("from") not in nmap or e.get("to") not in nmap:
            continue
        s, t = _edge_points(layout, e["from"], e["to"], direction, {n["id"]: n.get("shape", "round") for n in nodes})
        dash = ' stroke-dasharray="8 6"' if e.get("dashed") else ""
        out.append(f'<line x1="{s[0] - x0:.1f}" y1="{s[1] - y0:.1f}" x2="{t[0] - x0:.1f}" y2="{t[1] - y0:.1f}" '
                   f'stroke="{e.get("color", "#555")}" stroke-width="2"{dash} marker-end="url(#ah)"/>')
        if e.get("label"):
            mx, my = (s[0] + t[0]) / 2 - x0, (s[1] + t[1]) / 2 - y0
            out.append(f'<text x="{mx:.0f}" y="{my:.0f}" text-anchor="middle" font-size="14" fill="#333" '
                       f'paint-order="stroke" stroke="white" stroke-width="5">{esc(e["label"])}</text>')
    for n in nodes:
        x, y = layout["pos"][n["id"]]
        w, h = layout["sizes"][n["id"]]
        c = n.get("color", theme)
        x, y = x - x0, y - y0
        shape = n.get("shape", "round")
        style = f'fill="{c}" fill-opacity="0.16" stroke="{n.get("border", c)}" stroke-width="3"'
        poly = _shape_poly(shape, x, y, w, h)
        if poly:
            out.append(f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in poly)}" {style}/>')
        elif shape in ("ellipse", "circle"):
            out.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" {style}/>')
        else:
            r = 0 if shape == "box" else 18
            out.append(f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" {style}/>')
        lines = str(n.get("label", n["id"])).split("\n")
        for i, line in enumerate(lines):
            yy = y + (i - (len(lines) - 1) / 2) * 22 + 6
            out.append(f'<text x="{x:.1f}" y="{yy:.1f}" text-anchor="middle" font-size="17">{esc(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)


MERMAID_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>{{TITLE}}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#fff}h1{font-size:20px}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
</head><body><h1>{{TITLE}}</h1><pre class="mermaid">{{CODE}}</pre>
<script>mermaid.initialize({startOnLoad:true, theme:'default'});</script></body></html>
"""
