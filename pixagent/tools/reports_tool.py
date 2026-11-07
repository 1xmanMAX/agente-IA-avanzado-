"""Herramienta del agente para el creador de informes estructurados/extensos."""
from __future__ import annotations

import json

from .base import ToolContext, ToolError, ToolResult, tool


@tool("report_builder",
      """Creador de INFORMES ESTRUCTURADOS y EXTENSOS (decenas o cientos de páginas) a partir de
      plantillas definidas por el usuario. Redacta cada sección en una llamada separada (en paralelo),
      guarda el progreso y ensambla un PDF con portada, índice, fotos y panel fotográfico.
      Acciones:
      - templates: lista las plantillas (id, nombre, secciones, campos).
      - save_template: guarda una plantilla nueva/editada (template = {name, description, fields:[{key,label,type}],
        sections:[{id,title,kind: ai|per_group|auto_outline|fields_table|photo_grid|static, instructions, words,
        depends_on, photos, layout, content}], style:{theme_color, cover, toc}}).
      - create: crea un informe (template_id, title, fields, notes, photos:[{path, caption, group}], target_pages
        solo para auto_outline). Devuelve id y estimación de coste: COMUNÍCALA al usuario antes de generar si es alta.
      - generate: redacta las secciones pendientes (o 'sections' concretas; force=true para rehacer).
      - build: ensambla el PDF.  - status: estado de cada sección.
      Agrupa las fotos por zona/frente con 'group' para que cada grupo tenga su apartado.""",
      {"properties": {
          "action": {"type": "string", "enum": ["templates", "save_template", "create", "generate", "build", "status"]},
          "template": {"type": "object"}, "template_id": {"type": "string"},
          "report_id": {"type": "string"}, "title": {"type": "string"},
          "fields": {"type": "object"}, "notes": {"type": "string"},
          "photos": {"type": "array", "items": {"type": "object"}},
          "target_pages": {"type": "integer"}, "model": {"type": "string"},
          "sections": {"type": "array", "items": {"type": "string"}}, "force": {"type": "boolean"}},
       "required": ["action"]})
def report_builder(ctx: ToolContext, action: str, **kw) -> ToolResult:
    from ..reports.engine import (ReportGenerator, ReportProject, Templates, assemble_markdown,
                                  build_report_pdf)
    T = Templates(ctx.ws)
    if action == "templates":
        return ToolResult(json.dumps([{"id": t["id"], "name": t["name"], "description": t.get("description", ""),
                                       "fields": [f["key"] for f in t.get("fields", [])],
                                       "sections": [f"{s['id']} ({s['kind']})" for s in t["sections"]]}
                                      for t in T.list()], ensure_ascii=False, indent=1))
    if action == "save_template":
        try:
            t = T.save(kw.get("template") or {})
        except ValueError as e:
            raise ToolError(str(e))
        return ToolResult(f"Plantilla guardada: {t['id']}")
    if action == "create":
        try:
            tpl = T.get(kw.get("template_id") or "")
        except KeyError as e:
            raise ToolError(str(e))
        for ph in kw.get("photos") or []:
            ctx.resolve(ph["path"] if isinstance(ph, dict) else ph, must_exist=True)
        p = ReportProject.create(ctx.ws, tpl, kw.get("title") or tpl["name"], kw.get("fields"), kw.get("notes", ""),
                                 kw.get("photos"), kw.get("target_pages"), kw.get("model") or ctx.settings.model)
        est = p.estimate()
        return ToolResult(f"Informe creado: {p.id}\nEstimación: {est['calls']} llamadas, ~{est['pages_estimate']} páginas, "
                          f"~{est['input_tokens']:,} tokens de entrada y ~{est['output_tokens']:,} de salida "
                          f"(≈ {est['usd']} USD con {est['model']}).\nAbre /reports para verlo y editarlo.",
                          data={"report": p.id})
    rid = kw.get("report_id")
    if not rid:
        raise ToolError("Falta report_id.")
    p = ReportProject(ctx.ws, rid)
    if not p.data:
        raise ToolError(f"No existe el informe {rid}.")
    if action == "status":
        st = p.status()
        lines = [f"{u['status']:>8}  {u['id']}  {u['title']}" for u in st["units"]]
        return ToolResult("\n".join(lines))
    if action == "generate":
        gen = ReportGenerator(ctx.settings, p, emit=ctx.emit)
        res = gen.run(only=kw.get("sections"), force=bool(kw.get("force")))
        st = p.status()
        done = sum(1 for u in st["units"] if u["status"] == "done")
        errs = [f"{u['id']}: {u['error']}" for u in st["units"] if u["status"] == "error"]
        return ToolResult(f"Redacción terminada en {res['seconds']}s: {done} partes listas, {len(errs)} con error."
                          + ("\n" + "\n".join(errs) if errs else "")
                          + f"\nTokens usados: {p.data['usage']}", is_error=bool(errs) and done == 0)
    if action == "build":
        out = build_report_pdf(ctx.settings, p)
        words = len(assemble_markdown(p).split())
        return ToolResult(f"PDF del informe: {ctx.rel(out)} (~{words:,} palabras). Revisa algunas páginas con pdf_tools.",
                          files=[out])
    raise ToolError(f"Acción desconocida: {action}")
