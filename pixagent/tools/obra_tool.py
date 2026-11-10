"""Herramientas de obras por administración directa (Directiva 017-2023-CG/GMPL):
perfil de obra + equipo técnico con órdenes por rol, y revisor de informes por inconsistencias."""
from __future__ import annotations

import json
from pathlib import Path

from .base import ToolContext, ToolError, ToolResult, tool

# Para pruebas: fábrica del lector de documentos (por defecto, Claude con visión).
writer_factory = None


def _obra(ctx: ToolContext, oid: str | None):
    from ..obras.obra import Obra, get_activa
    if oid:
        o = Obra(ctx.ws, oid)
        if not o.data:
            raise ToolError(f"No existe la obra {oid}. Usa action='listar'.")
        return o
    o = get_activa(ctx.ws)
    if o is None:
        raise ToolError("No hay obra activa. Crea una con action='nueva' (pide al usuario el nombre y los datos).")
    return o


@tool("obra",
      """Gestiona la OBRA por administración directa (Directiva 017-2023-CG/GMPL) y su EQUIPO TÉCNICO.
      Acciones:
      - listar | nueva(nombre, datos) | activar(obra_id) | ver | actualizar(datos)
        datos = {cui, infobras, entidad, unidad_ejecutora, pliego, oad, secuencia_funcional, localidad, distrito,
        provincia, departamento, anio_presupuestal, modalidad, sistema, fuente_financiamiento, costo_et,
        presupuesto_aprobado, presupuesto_analitico, aprobacion_et, fecha_presupuesto, viabilidad, acta_terreno,
        acta_inicio, fecha_inicio (AAAA-MM-DD), plazo_dias, fecha_fin, accesibilidad, canteras, zona_especial (bool)}
      - categoria: sin 'categoria' devuelve la categoría o LO QUE FALTA para saberla (preguntas y ejemplos).
        La categoría CAMBIA según la obra: pregúntala SIEMPRE con ask_user; si el usuario no entiende, da los
        ejemplos o pide costo del ET y ubicación para deducirla. Con categoria='A|B|C' y motivo la fija.
      - personal: personal clave exigido según la categoría y quién falta.
      - miembro(nombre, rol, dni, cip, telefono, email): registra a quien se presenta («soy el almacenero Juan»)
        y devuelve SU ORDEN de trabajo. Roles: residente, supervisor, administrador, ssoma, almacenero,
        asistente, calidad, maquinaria.
      - orden(rol, periodo AAAA-MM): orden de trabajo de un rol: cuadros del Anexo 2 que entrega, columnas, plazo.
      - ordenes(periodo): órdenes de todo el equipo (para repartirlas).
      - entrega(cuadro 'D1'..'D15', archivos, autor, periodo, notas): registra y valida un entregable
        (CSV/Excel: columnas y sumas; PDF/fotos: revísalo luego con revisar_informe).
      - marcar(cuadro, estado pendiente|entregado|observado|conforme, observaciones)
      - tablero(periodo): estado de entregables por responsable.  - plazos: vencimientos próximos.
      - modificacion(tipo adicional|deductivo|mayor_metrado|partida_nueva|otra, importe, descripcion, estado
        'en trámite'|'aprobada'|'rechazada', resolucion): registra y devuelve la incidencia ACUMULADA y si pasa
        el 15 % (significativa) o el 50 % (Contraloría).  - ampliacion(dias, causal, estado, resolucion,
        inicio_evento, fin_evento): registra y devuelve la fecha de fin vigente.  - historial: ambas listas.""",
      {"properties": {
          "action": {"type": "string", "enum": ["listar", "nueva", "activar", "ver", "actualizar", "categoria", "personal",
                                                "miembro", "orden", "ordenes", "entrega", "marcar", "tablero", "plazos",
                                                "modificacion", "ampliacion", "historial"]},
          "obra_id": {"type": "string"}, "nombre": {"type": "string"}, "datos": {"type": "object"},
          "categoria": {"type": "string"}, "motivo": {"type": "string"},
          "rol": {"type": "string"}, "dni": {"type": "string"}, "cip": {"type": "string"},
          "telefono": {"type": "string"}, "email": {"type": "string"},
          "periodo": {"type": "string"}, "cuadro": {"type": "string"},
          "archivos": {"type": "array", "items": {"type": "string"}}, "autor": {"type": "string"},
          "notas": {"type": "string"}, "estado": {"type": "string"},
          "observaciones": {"type": "array", "items": {"type": "string"}},
          "tipo": {"type": "string"}, "importe": {"type": "number"}, "descripcion": {"type": "string"},
          "resolucion": {"type": "string"}, "dias": {"type": "integer"}, "causal": {"type": "string"},
          "inicio_evento": {"type": "string"}, "fin_evento": {"type": "string"}},
       "required": ["action"]})
def obra(ctx: ToolContext, action: str, **kw) -> ToolResult:
    from ..obras import norma as N
    from ..obras.obra import Obra, listar, set_activa
    if action == "listar":
        obras = listar(ctx.ws)
        return ToolResult(json.dumps(obras, ensure_ascii=False, indent=1) if obras else "No hay obras registradas.")
    if action == "nueva":
        if not kw.get("nombre"):
            raise ToolError("Falta 'nombre' de la obra.")
        o = Obra.create(ctx.ws, kw["nombre"], **(kw.get("datos") or {}))
        cat = o.categoria_info()
        msg = f"Obra creada y activa: {o.id}\n{o.resumen_texto()}"
        if not cat.get("categoria"):
            msg += ("\n\nCATEGORÍA PENDIENTE: pregúntala al usuario con ask_user. Datos que faltan:\n- "
                    + "\n- ".join(cat["faltan"]))
        return ToolResult(msg, data={"obra": o.id})
    if action == "activar":
        o = _obra(ctx, kw.get("obra_id"))
        set_activa(ctx.ws, o.id)
        return ToolResult(o.resumen_texto())
    o = _obra(ctx, kw.get("obra_id"))
    per = kw.get("periodo")
    try:
        if action == "ver":
            return ToolResult(o.resumen_texto() + "\n\n" + json.dumps(
                {k: v for k, v in o.data.items() if k not in ("periodos",)}, ensure_ascii=False, indent=1))
        if action == "actualizar":
            avisos = o.update(**(kw.get("datos") or {}))
            return ToolResult(o.resumen_texto() + ("\nAvisos:\n- " + "\n- ".join(avisos) if avisos else ""))
        if action == "categoria":
            if kw.get("categoria"):
                o.fijar_categoria(kw["categoria"].strip().upper(), kw.get("motivo") or "Indicada por el usuario")
            info = o.categoria_info()
            if info.get("categoria"):
                pers = "\n".join(f"- {p['cargo']}: {p['requisito']} ({p['experiencia']})" for p in info["personal"])
                return ToolResult(f"Categoría {info['categoria']}: {info['motivo']}\nPersonal clave:\n{pers}")
            return ToolResult(
                "Categoría SIN DETERMINAR. " + info["motivo"] + "\nPregunta al usuario (ask_user):\n- "
                + "\n- ".join(info["faltan"]) + "\n\nCriterios:\n" + "\n".join(f"- {k}: {v}" for k, v in info["criterios"].items())
                + "\n\nEjemplos para explicarlo si no entiende:\n- " + "\n- ".join(info["ejemplos"]))
        if action == "personal":
            info = o.categoria_info()
            if not info.get("categoria"):
                return ToolResult("Primero hay que determinar la categoría (action='categoria').")
            falt = o.faltantes_equipo()
            return ToolResult("\n".join(f"- {p['cargo']}: {p['requisito']}; {p['perfil']} Exp.: {p['experiencia']}"
                                        for p in info["personal"])
                              + ("\nFaltan por registrar: " + ", ".join(falt) if falt else "\nEquipo obligatorio completo."))
        if action == "miembro":
            if not kw.get("nombre") or not kw.get("rol"):
                raise ToolError("Necesito 'nombre' y 'rol' del integrante (pregúntaselos).")
            m = o.registrar_miembro(kw["nombre"], kw["rol"], **{k: kw.get(k) for k in ("dni", "cip", "telefono", "email")})
            ctx.state["miembro"] = {"obra": o.id, "id": m["id"], "nombre": m["nombre"], "rol": m["rol"]}
            return ToolResult(f"Registrado: {m['nombre']} — {m['cargo']}.\n\n{o.orden(m['rol'], per)}")
        if action == "orden":
            rol = kw.get("rol") or (ctx.state.get("miembro") or {}).get("rol")
            if not rol:
                raise ToolError("¿Para qué rol? Pregunta a la persona quién es y su cargo.")
            return ToolResult(o.orden(rol, per))
        if action == "ordenes":
            roles = sorted({r for _, _, r, _ in N.ANEXO2_CUADROS} | {"ssoma", "supervisor"})
            return ToolResult("\n\n".join(o.orden(r, per) for r in roles))
        if action == "entrega":
            if not kw.get("cuadro") or not kw.get("archivos"):
                raise ToolError("Necesito 'cuadro' (D1..D15) y 'archivos'.")
            arch = [ctx.rel(ctx.resolve(a, must_exist=True)) for a in kw["archivos"]]
            autor = kw.get("autor") or (ctx.state.get("miembro") or {}).get("nombre", "")
            e = o.registrar_entrega(kw["cuadro"], arch, per, autor, kw.get("notas", ""))
            msg = f"Cuadro {kw['cuadro'].upper()} «{e['titulo']}»: {e['estado']}."
            if e["obs"]:
                msg += "\nObservaciones para devolver al responsable:\n- " + "\n- ".join(e["obs"])
            elif any(a.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")) for a in arch):
                msg += "\nEs PDF/imagen: revísalo con revisar_informe(tipo='cuadro') antes de darlo por conforme."
            return ToolResult(msg)
        if action == "marcar":
            e = o.marcar(kw.get("cuadro", ""), kw.get("estado", ""), per, kw.get("observaciones"))
            return ToolResult(f"{kw.get('cuadro', '').upper()}: {e['estado']}")
        if action == "tablero":
            return ToolResult(o.tablero(per))
        if action == "modificacion":
            m = o.registrar_modificacion(kw.get("tipo") or "otra", kw.get("importe"), kw.get("descripcion", ""),
                                         kw.get("estado") or "en trámite", resolucion=kw.get("resolucion", ""))
            a = m["acumulado"]
            return ToolResult(f"Modificación N.º {m['n']} ({m['tipo']}, {m['estado']}): S/ {m['importe']:,.2f}"
                              + (f" = {m['incidencia']:.2%} del ET" if m["incidencia"] is not None else "")
                              + f"\nAcumulado neto: S/ {a['importe']:,.2f}"
                              + (f" = {a['pct']:.2%} del ET" if a["pct"] is not None else " (falta el costo del ET para el %)")
                              + (f"\n⚠ {a['aviso']}" if a["aviso"] else ""))
        if action == "ampliacion":
            a = o.registrar_ampliacion(kw.get("dias") or 0, kw.get("causal", ""), kw.get("estado") or "en trámite",
                                       kw.get("resolucion", ""), inicio_evento=kw.get("inicio_evento", ""),
                                       fin_evento=kw.get("fin_evento", ""))
            return ToolResult(f"Ampliación N.º {a['n']} ({a['estado']}): {a['dias']} d.c. por «{a['causal']}». "
                              f"Fin vigente (solo cuenta las aprobadas): {a['fecha_fin_vigente'] or 'falta fecha de fin'}.\n"
                              "Recuerda: solo procede si afecta la ruta crítica y con plazo vigente (7.3.7); registrar en "
                              "SNPMGI/INFOBRAS antes de iniciarla; cronograma actualizado 2 d.c. tras el reinicio.")
        if action == "historial":
            return ToolResult(json.dumps({"modificaciones": o.data.get("modificaciones", []),
                                          "acumulado": o.modificaciones_acumuladas(),
                                          "ampliaciones": o.data.get("ampliaciones", []),
                                          "fin_vigente": o.fecha_fin_vigente()}, ensure_ascii=False, indent=1))
        if action == "plazos":
            return ToolResult("\n".join(f"- {x['fecha']} ({x['dias']:+d} d): {x['que']}" for x in o.plazos()))
    except (ValueError, KeyError) as e:
        raise ToolError(str(e))
    raise ToolError(f"Acción desconocida: {action}")


@tool("revisar_informe",
      """Revisa informes de obra (PDF escaneados o digitales, fotos de páginas, Excel/CSV, Word) por
      INCONSISTENCIAS según la Directiva 017-2023-CG/GMPL y genera un REPORTE RÁPIDO en PDF con semáforo:
      sumas y saldos (acumulado = anterior + actual, saldo, total ejecutado, almacén), atraso > 20 % sin
      acciones, modificaciones > 15 %/50 %, fechas y plazos, coherencia con la obra y con el mes anterior,
      apartados del Anexo 2 faltantes, fotos y firmas. Lee los escaneados por bloques de páginas con visión.
      tipo: mensual_residente | preliquidacion | supervision | cuadro, o el id de un formato de la directiva
      (anexo10-modificacion … anexo20-liquidacion, informe-final-obra): entonces lee también sus casillas y aplica
      sus reglas (incidencias, 15 %/50 %, causales y fechas de ampliación, máx. 50 palabras, saldos de liquidación).
      paginas: '1-40' para limitar.""",
      {"properties": {"paths": {"type": "array", "items": {"type": "string"}},
                      "tipo": {"type": "string"},
                      "obra_id": {"type": "string"}, "paginas": {"type": "string"}},
       "required": ["paths"]})
def revisar_informe(ctx: ToolContext, paths: list, tipo: str = "mensual_residente", obra_id: str | None = None,
                    paginas: str | None = None) -> ToolResult:
    from ..obras.obra import Obra, get_activa
    from ..obras.revisor import ETIQUETA, revisar_documentos
    files = [ctx.resolve(p, must_exist=True) for p in paths]
    o = Obra(ctx.ws, obra_id) if obra_id else get_activa(ctx.ws)
    if o is not None and not o.data:
        o = None
    rango = None
    if paginas:
        a, _, b = paginas.partition("-")
        rango = (int(a), int(b or a))
    if writer_factory is not None:
        writer = writer_factory(ctx.settings)
    else:
        from ..reports.engine import ClaudeWriter
        writer = ClaudeWriter(ctx.settings, ctx.settings.model)
    res = revisar_documentos(ctx.settings, files, writer, tipo, o, ctx.emit, rango)
    g = ctx.state.get("guia") or {}
    if g.get("objetivo") == "revision":   # el modo guiado marca el paso de revisión como hecho
        g["revisado"] = True
        g["reporte"] = ctx.rel(res["pdf"])
        g.setdefault("archivos", [])
        g["archivos"] += [ctx.rel(f) for f in files if ctx.rel(f) not in g["archivos"]]
    H = res["hallazgos"]
    cnt = {k: sum(1 for h in H if h["nivel"] == k) for k in ETIQUETA}
    top = "\n".join(f"- [{ETIQUETA[h['nivel']]}] p.{h.get('pagina') or '—'} {h['regla']}: {h['detalle']}"
                    + (f" → esperado {h['esperado']}" if h.get("esperado") else "") for h in H[:25])
    return ToolResult(f"Revisión de {res['datos'].get('_paginas', 0)} páginas en {res['segundos']} s: "
                      f"{cnt['error']} errores, {cnt['alerta']} alertas, {cnt['ia']} a verificar.\n"
                      f"Reporte PDF: {ctx.rel(res['pdf'])}\n\n{top or 'Sin hallazgos.'}",
                      files=[Path(res["pdf"])])
