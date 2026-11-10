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
      Agrupa las fotos por zona/frente con 'group' para que cada grupo tenga su apartado.
      OBRAS POR ADMINISTRACIÓN DIRECTA: plantillas 'informe-mensual-residente' (Anexo 2), 'preliquidacion-obra'
      (7.3.10), 'anexo10-modificacion', 'anexo11-conformidad', 'anexo12-revision-et', 'anexo13-supervision',
      'anexo14-ampliacion-plazo', 'anexo15-reprogramacion', 'anexo16-mayores-gastos-generales',
      'anexo17-cronograma-actualizado', 'anexo18-adicional', 'anexo19-mayores-metrados', 'anexo20-liquidacion',
      'informe-final-obra'. Con obra_id (o la obra activa) y periodo AAAA-MM, create rellena los datos maestros desde el
      perfil de la obra, pone en cada cuadro D1–D15 la tabla entregada por el equipo (CSV/Excel) y adjunta al
      final los entregables en PDF/foto. Antes de generar revisa el tablero (obra action='tablero').""",
      {"properties": {
          "action": {"type": "string", "enum": ["templates", "save_template", "create", "generate", "build", "status"]},
          "template": {"type": "object"}, "template_id": {"type": "string"},
          "report_id": {"type": "string"}, "title": {"type": "string"},
          "fields": {"type": "object"}, "notes": {"type": "string"},
          "photos": {"type": "array", "items": {"type": "object"}},
          "target_pages": {"type": "integer"}, "model": {"type": "string"},
          "sections": {"type": "array", "items": {"type": "string"}}, "force": {"type": "boolean"},
          "obra_id": {"type": "string"}, "periodo": {"type": "string"}},
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
        fields, extra, note = dict(kw.get("fields") or {}), {}, ""
        if kw.get("obra_id") or str(tpl.get("norma", "")).startswith("Directiva"):
            fields, extra, note = _from_obra(ctx, kw.get("obra_id"), kw.get("periodo"), tpl, fields)
        p = ReportProject.create(ctx.ws, tpl, kw.get("title") or tpl["name"], fields, kw.get("notes", ""),
                                 kw.get("photos"), kw.get("target_pages"), kw.get("model") or ctx.settings.model)
        if extra:
            p.update(**extra)
        est = p.estimate()
        return ToolResult(f"Informe creado: {p.id}\nEstimación: {est['calls']} llamadas, ~{est['pages_estimate']} páginas, "
                          f"~{est['input_tokens']:,} tokens de entrada y ~{est['output_tokens']:,} de salida "
                          f"(≈ {est['usd']} USD con {est['model']}).\nAbre /reports para verlo y editarlo." + note,
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


def _from_obra(ctx: ToolContext, oid, periodo, tpl: dict, fields: dict) -> tuple[dict, dict, str]:
    """Datos maestros, cuadros (tablas) y anexos (PDF/fotos) desde el perfil de la obra y sus entregables."""
    from ..obras.obra import Obra, get_activa, periodo_actual
    o = Obra(ctx.ws, oid) if oid else get_activa(ctx.ws)
    if o is None or not o.data:
        return fields, {}, "\nNo hay obra activa: los datos maestros deben darse en 'fields' (o crea la obra con la herramienta obra)."
    per = periodo or periodo_actual()
    merged = {**o.campos_informe(), "periodo": per, **{k: v for k, v in fields.items() if v not in (None, "")}}
    p = o.periodo(per)
    tables, anexos, pend = {}, [], []
    wanted = {s.get("table") for s in tpl["sections"] if s.get("kind") == "table"}
    for k, e in p["entregables"].items():
        if k not in wanted:
            continue
        if e.get("tabla"):
            tables[k] = e["tabla"]
        for a in e.get("archivos", []):
            if a.lower().endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
                anexos.append({"key": k, "path": a, "title": f"Cuadro {k} {e['titulo']} ({a.split('/')[-1]})"})
        if e["estado"] in ("pendiente", "observado"):
            pend.append(f"{k} ({e['estado']})")
    # cuadros que salen del registro de la obra (no los entrega nadie: ya están en el perfil)
    if "ampliaciones" in wanted and o.data.get("ampliaciones"):
        tables["ampliaciones"] = [["N.º ampliación", "Documento de aprobación", "Fecha", "N.º días", "Nueva fecha de término"]] + [
            [str(a["n"]), a.get("resolucion", ""), a.get("fecha", ""), str(a.get("dias", "")), ""]
            for a in o.data["ampliaciones"] if a.get("estado") == "aprobada"]
    if "mm_aprobados" in wanted:
        mms = [m for m in o.data.get("modificaciones", []) if m["tipo"] == "mayor_metrado" and m.get("estado") == "aprobada"]
        base = o.data.get("costo_et") or o.data.get("presupuesto_aprobado")
        if mms:
            tables["mm_aprobados"] = [["N.º", "Partida", "Descripción", "Monto total", "% incidencia"]] + [
                [str(m["n"]), "", m.get("descripcion", ""), f"{m['importe']:,.2f}", f"{m['importe'] / base:.2%}" if base else ""]
                for m in mms]
    tables = {k: v for k, v in tables.items() if len(v) > 1}
    faltan = [f["label"] for f in tpl.get("fields", []) if f.get("required") and not merged.get(f["key"])]
    note = f"\nObra: {o.data.get('nombre')} · periodo {per} · {len(tables)} cuadros con datos, {len(anexos)} anexos."
    if pend:
        note += "\nCuadros pendientes u observados: " + ", ".join(pend) + " (quedan marcados [CUADRO PENDIENTE])."
    if faltan:
        note += "\nFaltan datos obligatorios: " + ", ".join(faltan)
    if not o.data.get("categoria"):
        note += "\nCategoría de la obra SIN DETERMINAR: pregúntala (obra action='categoria')."
    return merged, {"tables": tables, "anexos": anexos, "obra": o.id}, note
