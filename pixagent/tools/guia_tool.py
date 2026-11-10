"""Herramienta del modo guiado: «dime qué quieres → te digo qué necesito → lo construimos paso a paso»."""
from __future__ import annotations

from pathlib import Path

from .base import ToolContext, ToolError, ToolResult, tool

writer_factory = None  # para pruebas: redactor simulado


def _writer(ctx):
    if writer_factory is not None:
        return writer_factory(ctx.settings)
    return None  # ReportGenerator usa Claude por defecto


@tool("guia",
      """MODO GUIADO para construir documentos paso a paso con el usuario. Úsalo SIEMPRE que pida un informe o
      documento (informe mensual, pre-liquidación, revisión de un informe, informe con plantilla).
      Flujo: iniciar(objetivo) → muestra al usuario QUÉ NECESITAS (lista corta) → pide UNA cosa por vez
      (ask_user con las opciones sugeridas, o que adjunte archivos) → aportar(paso, datos/archivos/texto) tras
      cada respuesta → cuando estén los datos: redactar (una sección), muéstrala y pregunta → aprobar /
      corregir(instrucciones) / editar(markdown) → siguiente sección … → finalizar (PDF + comprobaciones).
      Si el usuario eligió ritmo «rápido»: redactar(todas=true) y luego finalizar.
      Objetivos: informe_mensual, preliquidacion, revision, informe (otra plantilla) y los formatos de la Directiva
      017-2023: modificacion (Anexo 10), conformidad (11), revision_et (12), supervision (13), ampliacion_plazo (14),
      reprogramacion (15), mayores_gastos_generales (16), cronograma_actualizado (17), adicional (18),
      mayores_metrados (19), liquidacion_final (20), informe_final (7.4.2). También acepta la frase del usuario.
      Acciones: iniciar(objetivo, plantilla, periodo, ritmo) ·
      estado · aportar(paso, datos, archivos, texto) · omitir(paso, motivo) · redactar(seccion?, todas?) ·
      aprobar(seccion|'todas') · corregir(seccion, texto) · editar(seccion, texto=markdown) · finalizar.
      Pasos de aportar: obra{nombre,cui,entidad,distrito,provincia,departamento,costo_et,fecha_inicio,plazo_dias,...},
      categoria{categoria|costo_et,zona_especial}, periodo{periodo,numero,periodo_liquidado}, equipo{miembros:[{nombre,rol}]},
      cuadros{cuadro,autor}+archivos, fotos{fotos:[{path,caption,grupo,etapa}]}+archivos,
      cifras{valorizacion_mes,valorizacion_acumulada,mayores_metrados,adicionales,deductivos,total_ejecutado,
      avance_programado,avance_real,metas}, notas(texto), datos{campos de la plantilla}, plantilla, archivos, tipo, ritmo;
      en formatos: firmantes{res_*, sup_*}, datos / datos_extra{claves del formato}, tablas{tabla, filas}+archivos,
      checklist{seccion, respuestas:[{n, r, c}]}, sustento + archivos. El resultado trae las CLAVES EXACTAS del paso
      actual: úsalas. Si el usuario da documentos, puedes proponerle respuestas a las preguntas para que confirme.
      El progreso se calcula solo y se ve en el panel «Plan».""",
      {"properties": {
          "action": {"type": "string", "enum": ["iniciar", "estado", "aportar", "omitir", "redactar", "aprobar",
                                                "corregir", "editar", "finalizar"]},
          "objetivo": {"type": "string"}, "plantilla": {"type": "string"}, "periodo": {"type": "string"},
          "ritmo": {"type": "string", "enum": ["paso a paso", "rápido"]},
          "paso": {"type": "string"}, "datos": {"type": "object"},
          "archivos": {"type": "array", "items": {"type": "string"}},
          "texto": {"type": "string"}, "motivo": {"type": "string"},
          "seccion": {"type": "string"}, "todas": {"type": "boolean"}},
       "required": ["action"]})
def guia(ctx: ToolContext, action: str, **kw) -> ToolResult:
    from ..guia import Guia
    g = Guia(ctx)
    if action != "iniciar" and not g.objetivo:
        raise ToolError("No hay ningún documento en curso: usa action='iniciar' con el objetivo del usuario.")
    extra = ""
    files: list[Path] = []
    try:
        if action == "iniciar":
            g.iniciar(kw.get("objetivo") or "", kw.get("plantilla"), kw.get("periodo"), kw.get("ritmo"))
            extra = ("Empieza diciéndole al usuario en 3-6 líneas qué vas a necesitar (los pasos de abajo, en palabras "
                     "simples; lo que ya está, márcalo como listo) y pide la PRIMERA cosa.")
        elif action == "aportar":
            if not kw.get("paso"):
                raise ToolError("Falta 'paso'.")
            arch = [ctx.rel(ctx.resolve(a, must_exist=True)) for a in kw.get("archivos") or []]
            avisos = g.aportar(kw["paso"], kw.get("datos"), arch, kw.get("texto", ""))
            if avisos:
                extra = "AVISOS (coméntalos con el usuario antes de seguir):\n- " + "\n- ".join(avisos)
        elif action == "omitir":
            g.omitir(kw.get("paso", ""), kw.get("motivo", ""))
        elif action == "redactar":
            extra = g.redactar(_writer(ctx), kw.get("seccion"), bool(kw.get("todas")))
        elif action == "aprobar":
            g.aprobar(kw.get("seccion"))
            u = g.siguiente_seccion()
            extra = f"Aprobada. Siguiente sección: «{u.title}» [{u.id}] → redactar." if u else "Todas aprobadas → finalizar."
        elif action == "corregir":
            if not kw.get("seccion") or not kw.get("texto"):
                raise ToolError("Necesito 'seccion' y en 'texto' lo que el usuario quiere cambiar.")
            extra = g.corregir(kw["seccion"], kw["texto"], _writer(ctx))
        elif action == "editar":
            g.editar(kw.get("seccion", ""), kw.get("texto", ""))
            g.aprobar(kw.get("seccion"))
            extra = "Guardada la versión del usuario y aprobada."
        elif action == "finalizar":
            pdf, avisos = g.finalizar()
            files.append(pdf)
            extra = f"PDF: {ctx.rel(pdf)}" + ("\nComprobaciones:\n- " + "\n- ".join(avisos) if avisos else
                                              "\nComprobaciones: sin observaciones.")
        elif action != "estado":
            raise ToolError(f"Acción desconocida: {action}")
    except ValueError as e:
        raise ToolError(str(e))
    est = g.estado()
    todos = g.todos(est)
    ctx.state["todos"] = todos
    return ToolResult(g.texto(est) + ("\n\n" + extra if extra else ""), files=files, data={"todos": todos})
