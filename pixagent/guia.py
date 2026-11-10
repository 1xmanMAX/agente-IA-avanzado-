"""Modo guiado: el usuario dice QUÉ quiere, la app le dice QUÉ NECESITA y el documento se construye
paso a paso (como un asistente de varios pasos, pero conversando).

Cada objetivo es una lista de pasos. El estado de cada paso NO se guarda a mano: se CALCULA cada vez a
partir de lo que ya existe (perfil de obra, entregables del equipo, fotos aportadas, proyecto de informe,
secciones aprobadas, PDF). Así el progreso nunca miente y se puede retomar otro día.
La lista se muestra en el panel «Plan» de la interfaz (evento todos) con su barra de progreso.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ------------------------------------------------------------------ objetivos
OBJETIVOS = {
    "informe_mensual": {"nombre": "Informe mensual del residente (Anexo 2)", "plantilla": "informe-mensual-residente",
                        "obra": True},
    "preliquidacion": {"nombre": "Liquidación parcial / pre-liquidación (7.3.10)", "plantilla": "preliquidacion-obra",
                       "obra": True},
    "revision": {"nombre": "Revisión de un informe por inconsistencias", "plantilla": None, "obra": False},
    "informe": {"nombre": "Informe con una plantilla", "plantilla": None, "obra": False},
}
# Formatos de la directiva (Anexos 10–20 e informe final): pasos generados desde la plantilla
FORMATOS = {
    "modificacion": ("anexo10-modificacion", "Modificación del expediente técnico (Anexo 10)",
                     ["anexo 10", "modificacion del expediente", "modificación del expediente", "modificacion de obra",
                      "modificación de obra", "control de modificaciones", "deductivo", "partida nueva"]),
    "conformidad": ("anexo11-conformidad", "Informe de conformidad al inicio del plazo (Anexo 11)",
                    ["anexo 11", "conformidad al", "informe de conformidad", "cpm", "calendario de adquisicion"]),
    "revision_et": ("anexo12-revision-et", "Revisión del expediente técnico (Anexo 12)",
                    ["anexo 12", "revision del expediente", "revisión del expediente", "revision del et", "revisión del et",
                     "expediente de saldo", "compatibilidad"]),
    "supervision": ("anexo13-supervision", "Informe mensual de supervisión y valorización (Anexo 13)",
                    ["anexo 13", "supervision", "supervisión", "inspector"]),
    "ampliacion_plazo": ("anexo14-ampliacion-plazo", "Ampliación de plazo (Anexo 14)",
                         ["anexo 14", "ampliacion de plazo", "ampliación de plazo", "ampliacion", "ampliación", "paralizacion", "paralización"]),
    "reprogramacion": ("anexo15-reprogramacion", "Reprogramación por ampliación de plazo (Anexo 15)",
                       ["anexo 15", "reprogramacion", "reprogramación"]),
    "mayores_gastos_generales": ("anexo16-mayores-gastos-generales", "Mayores gastos generales (Anexo 16)",
                                 ["anexo 16", "mayores gastos", "gastos generales"]),
    "cronograma_actualizado": ("anexo17-cronograma-actualizado", "Cronograma actualizado (Anexo 17)",
                               ["anexo 17", "cronograma actualizado", "programa actualizado", "cronograma acelerado", "reinicio"]),
    "adicional": ("anexo18-adicional", "Prestación adicional de obra (Anexo 18)",
                  ["anexo 18", "adicional"]),
    "mayores_metrados": ("anexo19-mayores-metrados", "Mayores metrados (Anexo 19)",
                         ["anexo 19", "mayores metrados", "mayor metrado"]),
    "liquidacion_final": ("anexo20-liquidacion", "Informe de liquidación de obra (Anexo 20)",
                          ["anexo 20", "liquidacion final", "liquidación final", "liquidacion de obra", "liquidación de obra",
                           "liquidacion total", "liquidación total"]),
    "informe_final": ("informe-final-obra", "Informe final de obra (7.4.2)",
                      ["informe final", "culminacion", "culminación", "lecciones aprendidas"]),
}
for _k, (_tid, _nom, _al) in FORMATOS.items():
    OBJETIVOS[_k] = {"nombre": _nom, "plantilla": _tid, "obra": True}

# orden de detección: lo más específico primero
ALIAS = [(k, FORMATOS[k][2]) for k in ("revision_et", "liquidacion_final", "informe_final", "cronograma_actualizado",
                                       "reprogramacion", "mayores_gastos_generales", "mayores_metrados", "ampliacion_plazo",
                                       "adicional", "modificacion", "conformidad", "supervision")] + [
    ("preliquidacion", ["preliquid", "pre-liquid", "pre liquid", "liquidacion parcial", "liquidación parcial", "liquidacion",
                        "liquidación"]),
    ("informe_mensual", ["mensual", "anexo 2", "residente", "valorizacion mensual"]),
    ("revision", ["revis", "inconsisten", "observa", "verific", "auditar"]),
]


def detectar_objetivo(texto: str) -> str | None:
    t = (texto or "").lower()
    if t in OBJETIVOS:
        return t
    for k, al in ALIAS:
        if any(a in t for a in al):
            return k
    if "informe" in t or "reporte" in t:
        return "informe"
    return None


@dataclass
class Paso:
    id: str
    titulo: str
    necesito: str                  # qué tiene que aportar el usuario (en palabras simples)
    check: Callable[["Guia"], tuple[bool, str]]
    omitible: bool = False
    pregunta: str = ""             # pregunta sugerida para ask_user
    opciones: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ guía
class Guia:
    """Estado del asistente guiado de una sesión (vive en ctx.state['guia'])."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.st: dict = ctx.state.setdefault("guia", {})

    # ---------------------------------------------------------- utilidades
    @property
    def ws(self) -> Path:
        return self.ctx.ws

    @property
    def objetivo(self) -> str | None:
        return self.st.get("objetivo")

    def obra(self):
        from .obras.obra import Obra, get_activa
        oid = self.st.get("obra")
        o = Obra(self.ws, oid) if oid else get_activa(self.ws)
        return o if o is not None and o.data else None

    def proyecto(self):
        from .reports.engine import ReportProject
        rid = self.st.get("report_id")
        if not rid:
            return None
        p = ReportProject(self.ws, rid)
        return p if p.data else None

    def plantilla(self) -> dict | None:
        from .reports.engine import Templates
        tid = self.st.get("plantilla") or OBJETIVOS.get(self.objetivo or "", {}).get("plantilla")
        if not tid:
            return None
        try:
            return Templates(self.ws).get(tid)
        except KeyError:
            return None

    # ---------------------------------------------------------- inicio
    def iniciar(self, objetivo: str, plantilla: str | None = None, periodo: str | None = None,
                ritmo: str | None = None) -> None:
        obj = detectar_objetivo(objetivo) or objetivo
        if obj not in OBJETIVOS:
            raise ValueError(f"Objetivo desconocido: {objetivo}. Opciones: {', '.join(OBJETIVOS)}")
        self.st.clear()
        self.st.update(objetivo=obj, plantilla=plantilla or OBJETIVOS[obj]["plantilla"], periodo=periodo,
                       ritmo=ritmo, fotos=[], archivos=[], datos={}, notas="", omitidos={}, aprobadas=[],
                       revisado=False)
        o = self.obra()
        if o:
            self.st["obra"] = o.id

    # ---------------------------------------------------------- pasos
    def pasos(self) -> list[Paso]:
        obj = self.objetivo
        if obj in ("informe_mensual", "preliquidacion"):
            return self._pasos_obra(obj)
        if obj in FORMATOS:
            return self._pasos_formato()
        if obj == "revision":
            return [
                Paso("archivos", "Documento a revisar", "el PDF (escaneado o digital), fotos de las páginas o Excel",
                     lambda g: (bool(g.st["archivos"]), ", ".join(Path(a).name for a in g.st["archivos"]) or "falta adjuntarlo")),
                Paso("tipo", "Tipo de informe", "qué es: informe mensual, pre-liquidación, informe del supervisor o un cuadro",
                     lambda g: (bool(g.st["datos"].get("tipo")), g.st["datos"].get("tipo", "")),
                     pregunta="¿Qué tipo de documento es?",
                     opciones=["Informe mensual del residente", "Pre-liquidación", "Informe del supervisor", "Un cuadro suelto"]),
                Paso("obra", "Obra para comparar (opcional)", "si es de tu obra, compararé CUI, fechas y el mes anterior",
                     lambda g: (bool(g.obra()), g.obra().data.get("nombre") if g.obra() else "sin obra (solo reglas generales)"),
                     omitible=True),
                Paso("revisar", "Revisión y reporte PDF", "nada: lo hago yo",
                     lambda g: (bool(g.st.get("revisado")), g.st.get("reporte", ""))),
            ]
        return self._pasos_generico()

    def _pasos_formato(self) -> list[Paso]:
        """Pasos de un formato de la directiva, deducidos de su plantilla: datos de la obra, firmantes,
        datos propios del formato, cuadros, listas de verificación, documentos de sustento y hechos."""
        from .obras.obra import CAMPOS
        from .obras.plantillas import F_OBRA, F_RES, F_SUP, F_ET
        from .reports.engine import checklist_items
        t = self.plantilla() or {"fields": [], "sections": []}
        comunes = {k for k, _ in F_OBRA + F_RES + F_SUP + F_ET} | {"fecha"}
        propios = [f for f in t["fields"] if f["key"] not in comunes]
        req = [f for f in propios if f.get("required")]
        opc = [f for f in propios if not f.get("required")]
        tablas = [s_ for s_ in t["sections"] if s_["kind"] == "table"]
        listas = [s_ for s_ in t["sections"] if s_["kind"] == "checklist"]

        def vals(g):
            return {**(g.obra().campos_informe() if g.obra() else {}), **g.st["datos"]}

        def obra_ok(g):
            o = g.obra()
            if not o:
                return False, "no hay obra registrada"
            faltan = [k for k in ("cui", "entidad", "distrito", "provincia", "departamento", "fecha_inicio", "plazo_dias")
                      if o.data.get(k) in (None, "")]
            return not faltan, o.data.get("nombre") + (" — falta: " + ", ".join(CAMPOS[k] for k in faltan) if faltan else "")

        def firmantes_ok(g):
            v = vals(g)
            faltan = [lbl for k, lbl in (("res_nombre", "residente"), ("res_cip", "CIP del residente"),
                                         ("sup_nombre", "supervisor/inspector"), ("sup_cip", "CIP del supervisor"),
                                         ("res_designacion", "resolución del residente"),
                                         ("sup_designacion", "resolución del supervisor")) if not v.get(k)]
            return not faltan, "completos" if not faltan else "falta: " + ", ".join(faltan)

        def req_ok(g):
            v = vals(g)
            faltan = [f["label"] for f in req if v.get(f["key"]) in (None, "")]
            return not faltan, "falta: " + "; ".join(faltan) if faltan else "completos"

        def opc_ok(g):
            v = vals(g)
            faltan = [f["label"] for f in opc if v.get(f["key"]) in (None, "")]
            return not faltan, (f"{len(opc) - len(faltan)}/{len(opc)}; falta: " + "; ".join(faltan[:6])
                                + ("…" if len(faltan) > 6 else "")) if faltan else "completos"

        def tablas_ok(g):
            tiene = set(g.st.get("tablas", {})) | {a.get("key") for a in g.st.get("anexos", [])}
            falt = [s_.get("title") for s_ in tablas if s_.get("table") not in tiene and not g._tabla_obra(s_.get("table"))]
            return not falt, "completos" if not falt else "pendientes: " + "; ".join(falt)

        def listas_ok(g):
            resp = g.st.get("checklists", {})
            sin = sum(1 for s_ in listas for i in range(1, len(checklist_items(s_)) + 1)
                      if not (resp.get(s_["id"], {}).get(str(i)) or {}).get("r"))
            tot = sum(len(checklist_items(s_)) for s_ in listas)
            return sin == 0, f"{tot - sin}/{tot} respondidas"

        def sustento_ok(g):
            n = len(g.st.get("anexos", [])) + len(g.st["fotos"])
            return n > 0, f"{n} documentos/fotos" if n else "ninguno todavía"

        def notas_ok(g):
            return bool(g.st["notas"].strip()), (g.st["notas"][:60] + "…") if g.st["notas"] else "sin hechos todavía"

        pasos = [Paso("obra", "Datos de la obra", "nombre, CUI, INFOBRAS, entidad, ubicación, fecha de inicio y plazo", obra_ok),
                 Paso("firmantes", "Residente y supervisor", "nombres, DNI, CIP y resoluciones/contratos de designación (bloques II y III)",
                      firmantes_ok, omitible=True)]
        if req:
            pasos.append(Paso("datos", "Datos esenciales del formato", "; ".join(f["label"] for f in req), req_ok))
        if opc:
            pasos.append(Paso("datos_extra", "Demás datos del formato", "el resto de casillas del formato (te las pido por grupos)",
                              opc_ok, omitible=True))
        if tablas:
            pasos.append(Paso("tablas", "Cuadros", "; ".join(f"{s_['title']} ({', '.join(s_.get('columns', [])[:5])}…)" for s_ in tablas)
                              + " — en Excel/CSV, PDF escaneado o dictados", tablas_ok, omitible=True))
        if listas:
            pasos.append(Paso("checklist", "Preguntas del formato", "responder Sí/No/N.A. con comentario (te las hago de a pocas; "
                              "puedo proponerte respuestas si me das los documentos)", listas_ok, omitible=True))
        pasos += [Paso("sustento", "Documentos de sustento", "asientos del cuaderno, informes, planos, cotizaciones, fotos (PDF/imagen)",
                       sustento_ok, omitible=True),
                  Paso("notas", "Hechos y explicación", "qué pasó y por qué, con tus palabras (yo lo redacto según la norma)", notas_ok)]
        return pasos + self._pasos_redaccion()

    def _tabla_obra(self, key: str | None) -> bool:
        o = self.obra()
        if not o or not key:
            return False
        if key == "ampliaciones":
            return any(a.get("estado") == "aprobada" for a in o.data.get("ampliaciones", []))
        if key == "mm_aprobados":
            return any(m["tipo"] == "mayor_metrado" and m.get("estado") == "aprobada" for m in o.data.get("modificaciones", []))
        return False

    def _pasos_obra(self, obj: str) -> list[Paso]:
        from .obras.obra import periodo_actual

        def obra_ok(g):
            o = g.obra()
            if not o:
                return False, "no hay obra registrada"
            faltan = [k for k in ("cui", "entidad", "distrito", "provincia", "departamento", "costo_et",
                                  "fecha_inicio", "plazo_dias") if o.data.get(k) in (None, "")]
            from .obras.obra import CAMPOS
            return (not faltan, o.data.get("nombre") + (" — falta: " + ", ".join(CAMPOS[k] for k in faltan) if faltan else ""))

        def cat_ok(g):
            o = g.obra()
            c = o.data.get("categoria") if o else None
            return bool(c), f"Categoría {c}" if c else "sin determinar (te la pregunto)"

        def per_ok(g):
            return bool(g.st.get("periodo")), g.st.get("periodo") or f"¿{periodo_actual()}?"

        def equipo_ok(g):
            o = g.obra()
            if not o:
                return False, ""
            falt = o.faltantes_equipo()
            res = any(m["rol"] == "residente" for m in o.data["equipo"])
            return (res and not falt), ("completo" if res and not falt else
                                        "falta: " + ", ".join((["Residente"] if not res else []) + falt))

        def cuadros_ok(g):
            o = g.obra()
            if not o or not g.st.get("periodo"):
                return False, ""
            p = o.periodo(g.st["periodo"])
            pend = [k for k, e in p["entregables"].items() if e["estado"] in ("pendiente", "observado")]
            return not pend, f"{15 - len(pend)}/15 listos" + (f"; pendientes: {', '.join(pend)}" if pend else "")

        def fotos_ok(g):
            n = len(g.st["fotos"])
            return n > 0, f"{n} fotos" if n else "ninguna todavía"

        def cifras_ok(g):
            d = {**(g.obra().campos_informe() if g.obra() else {}), **g.st["datos"]}
            claves = (["valorizacion_mes", "total_ejecutado", "avance_programado", "avance_real"] if obj == "informe_mensual"
                      else ["numero", "periodo_liquidado"])
            faltan = [k for k in claves if d.get(k) in (None, "")]
            return not faltan, "falta: " + ", ".join(faltan) if faltan else "completas"

        def notas_ok(g):
            return bool(g.st["notas"].strip()), (g.st["notas"][:60] + "…") if g.st["notas"] else "sin ocurrencias todavía"

        pasos = [
            Paso("obra", "Datos de la obra", "nombre, CUI, entidad, ubicación, costo del expediente técnico, fecha de "
                 "inicio y plazo (o el PDF de la resolución/expediente y los leo)", obra_ok),
            Paso("categoria", "Categoría de la obra", "el costo total del ET y si está en zona de frontera o VRAEM",
                 cat_ok, pregunta="¿Qué categoría tiene la obra según la Directiva 017-2023?",
                 opciones=["Categoría A (hasta S/ 5 millones o frontera/VRAEM)", "Categoría B (S/ 5 a 10 millones)",
                           "Categoría C (más de S/ 10 millones)", "No lo sé"]),
            Paso("periodo", "Periodo del informe" if obj == "informe_mensual" else "Periodo a liquidar",
                 "el mes que informas (AAAA-MM)" if obj == "informe_mensual" else "desde–hasta y número de liquidación",
                 per_ok),
            Paso("equipo", "Equipo técnico", "quiénes son el residente y el personal clave (o que ellos se presenten en el chat)",
                 equipo_ok, omitible=True),
            Paso("cuadros", "Cuadros del equipo (D1–D15)", "los cuadros de cada responsable en Excel/CSV o PDF escaneado",
                 cuadros_ok, omitible=True),
            Paso("fotos", "Fotos del periodo", "fotos de antes, durante y final, con su ubicación si la sabes", fotos_ok,
                 omitible=obj == "preliquidacion"),
            Paso("cifras", "Cifras del periodo" if obj == "informe_mensual" else "Datos de la liquidación",
                 ("valorización del mes, total ejecutado, avance programado y ejecutado acumulado (%)"
                  if obj == "informe_mensual" else "número de liquidación y periodo; conformidad de gastos de Contabilidad"),
                 cifras_ok),
            Paso("notas", "Ocurrencias del periodo", "lo que pasó: trabajos, problemas (clima, personal, equipo), cuaderno de obra",
                 notas_ok, omitible=True),
        ]
        return pasos + self._pasos_redaccion()

    def _pasos_generico(self) -> list[Paso]:
        def plantilla_ok(g):
            t = g.plantilla()
            return bool(t), t["name"] if t else "elige una plantilla"

        def datos_ok(g):
            t = g.plantilla()
            if not t:
                return False, ""
            faltan = [f["label"] for f in t.get("fields", []) if f.get("required") and not g.st["datos"].get(f["key"])]
            return not faltan, "falta: " + ", ".join(faltan) if faltan else "completos"

        def fotos_ok(g):
            n = len(g.st["fotos"])
            return n > 0, f"{n} fotos" if n else "ninguna"

        def notas_ok(g):
            return bool(g.st["notas"].strip()), "con notas" if g.st["notas"] else "sin notas"

        return [Paso("plantilla", "Tipo de informe", "qué plantilla usar", plantilla_ok),
                Paso("datos", "Datos del informe", "los datos obligatorios de la plantilla", datos_ok),
                Paso("fotos", "Fotos", "las fotos que quieras incluir", fotos_ok, omitible=True),
                Paso("notas", "Notas y hallazgos", "lo que observaste, en tus palabras", notas_ok, omitible=True),
                ] + self._pasos_redaccion()

    def _pasos_redaccion(self) -> list[Paso]:
        def borrador_ok(g):
            p = g.proyecto()
            return bool(p), "creado" if p else "lo creo cuando estén los datos"

        def secciones_ok(g):
            p = g.proyecto()
            if not p:
                return False, ""
            ai = [u for u in p.ai_units() if u.kind != "outline"]
            aprob = [u for u in ai if u.id in g.st["aprobadas"]]
            nxt = g.siguiente_seccion()
            sig = nxt.title if nxt else ""
            return len(aprob) == len(ai), f"{len(aprob)}/{len(ai)} aprobadas" + (f"; siguiente: {sig}" if sig else "")

        def pdf_ok(g):
            p = g.proyecto()
            pdf = p.data.get("outputs", {}).get("pdf") if p else None
            return bool(pdf and (g.ws / pdf).exists()), pdf or ""

        return [Paso("borrador", "Borrador del informe", "nada: lo preparo con lo anterior", borrador_ok),
                Paso("secciones", "Redacción sección por sección", "leer cada sección y aprobarla o pedir cambios",
                     secciones_ok),
                Paso("pdf", "PDF final y comprobación", "nada: lo armo y reviso sumas, plazos y faltantes", pdf_ok)]

    # ---------------------------------------------------------- estado
    def estado(self) -> list[dict]:
        out, actual = [], None
        for p in self.pasos():
            ok, det = p.check(self)
            omit = p.id in self.st.get("omitidos", {})
            st = "hecho" if ok else "omitido" if omit else "pendiente"
            if st == "pendiente" and actual is None:
                actual = p.id
                st = "actual"
            out.append({"id": p.id, "titulo": p.titulo, "necesito": p.necesito, "estado": st, "detalle": det,
                        "omitible": p.omitible, "pregunta": p.pregunta, "opciones": p.opciones})
        return out

    def todos(self, est: list[dict] | None = None) -> list[dict]:
        est = est or self.estado()
        m = {"hecho": "completed", "omitido": "completed", "actual": "in_progress", "pendiente": "pending"}
        return [{"content": f"{e['titulo']}" + (f" — {e['detalle']}" if e["detalle"] else "")
                 + (" (omitido)" if e["estado"] == "omitido" else ""), "status": m[e["estado"]]} for e in est]

    def texto(self, est: list[dict] | None = None) -> str:
        est = est or self.estado()
        icon = {"hecho": "[x]", "omitido": "[-]", "actual": "[>]", "pendiente": "[ ]"}
        lines = [f"OBJETIVO: {OBJETIVOS[self.objetivo]['nombre']}"
                 + (f" · ritmo: {self.st['ritmo']}" if self.st.get("ritmo") else ""), ""]
        for i, e in enumerate(est, 1):
            lines.append(f"{icon[e['estado']]} {i}. {e['titulo']}: {e['detalle'] or '—'}")
        act = next((e for e in est if e["estado"] == "actual"), None)
        if act:
            lines += ["", f"PASO ACTUAL: {act['titulo']}. Necesito: {act['necesito']}."]
            if act["pregunta"]:
                lines.append(f"Pregunta sugerida (ask_user): {act['pregunta']} Opciones: {' | '.join(act['opciones'])}")
            ayuda = self._ayuda_paso(act["id"])
            if ayuda:
                lines.append(ayuda)
            if act["omitible"]:
                lines.append("Este paso se puede omitir si el usuario lo pide (guia action=omitir).")
        else:
            lines += ["", "TODOS LOS PASOS COMPLETOS: entrega el PDF y un resumen breve."]
        if not self.st.get("ritmo"):
            lines.append("RITMO SIN ELEGIR: pregunta si quiere aprobar cada sección (paso a paso) o que redactes "
                         "todo y revise al final (rápido).")
        return "\n".join(lines)

    # ---------------------------------------------------------- aportes
    def aportar(self, paso: str, datos: dict | None = None, archivos: list[str] | None = None,
                texto: str = "") -> list[str]:
        """Guarda lo que el usuario aporta en un paso. Devuelve avisos."""
        avisos: list[str] = []
        datos = {k: v for k, v in (datos or {}).items() if v not in (None, "")}
        o = self.obra()
        if paso == "obra":
            from .obras.obra import Obra
            if o is None:
                nombre = datos.pop("nombre", None) or texto
                if not nombre:
                    raise ValueError("Para crear la obra necesito al menos su nombre.")
                o = Obra.create(self.ws, nombre, **datos)
                self.st["obra"] = o.id
            else:
                avisos += o.update(**datos)
        elif paso == "categoria":
            if o is None:
                raise ValueError("Primero registra la obra.")
            cat = (datos.get("categoria") or texto or "").strip().upper()[:1]
            if cat in ("A", "B", "C"):
                o.fijar_categoria(cat, datos.get("motivo") or "Indicada por el usuario")
            else:
                avisos += o.update(**{k: datos[k] for k in ("costo_et", "zona_especial") if k in datos})
                if not o.data.get("categoria"):
                    avisos.append("Aún no se puede determinar: " + "; ".join(o.categoria_info().get("faltan", [])))
        elif paso == "periodo":
            self.st["periodo"] = (datos.get("periodo") or texto).strip()
            for k in ("numero", "periodo_liquidado"):
                if datos.get(k):
                    self.st["datos"][k] = datos[k]
        elif paso == "equipo":
            if o is None:
                raise ValueError("Primero registra la obra.")
            for m in datos.get("miembros", []):
                o.registrar_miembro(m["nombre"], m["rol"], **{k: m.get(k) for k in ("dni", "cip", "telefono", "email")})
        elif paso == "cuadros":
            if o is None or not self.st.get("periodo"):
                raise ValueError("Primero la obra y el periodo.")
            cuadro = datos.get("cuadro")
            if not cuadro or not archivos:
                raise ValueError("Indica el cuadro (D1..D15) y los archivos.")
            e = o.registrar_entrega(cuadro, archivos, self.st["periodo"], datos.get("autor", ""))
            if e["obs"]:
                avisos += [f"{cuadro}: {x}" for x in e["obs"]]
        elif paso == "fotos":
            for a in archivos or []:
                ph = {"path": a, "caption": datos.get("caption", ""), "group": datos.get("grupo", ""),
                      "status": datos.get("etapa", "")}
                if a not in [f["path"] for f in self.st["fotos"]]:
                    self.st["fotos"].append(ph)
            for f in datos.get("fotos", []):  # [{path, caption, grupo, etapa}]
                if f.get("path") and f["path"] not in [x["path"] for x in self.st["fotos"]]:
                    self.st["fotos"].append({"path": f["path"], "caption": f.get("caption", ""),
                                             "group": f.get("grupo", ""), "status": f.get("etapa", "")})
        elif paso in ("cifras", "datos", "datos_extra", "firmantes"):
            self.st["datos"].update(datos)
            if paso == "cifras":
                avisos += _chequeo_cifras(self.st["datos"])
            if paso == "firmantes" and o is not None:   # también quedan en el perfil de la obra
                for rol, pre in (("residente", "res"), ("supervisor", "sup")):
                    if datos.get(f"{pre}_nombre"):
                        o.registrar_miembro(datos[f"{pre}_nombre"], rol, dni=datos.get(f"{pre}_dni"), cip=datos.get(f"{pre}_cip"))
                o.update(**{k: v for k, v in datos.items() if k in ("res_designacion", "res_monto", "res_fecha", "res_inicio",
                                                                    "res_fin", "sup_designacion", "sup_monto", "sup_fecha",
                                                                    "sup_inicio", "sup_fin")})
            avisos += self._chequeo_formato()
        elif paso == "tablas":
            key = datos.get("tabla")
            if not key:
                raise ValueError("Indica 'tabla' (la clave del cuadro, p. ej. liquidacion, hitos, mm_cuantificacion).")
            if datos.get("filas"):
                self.st.setdefault("tablas", {})[key] = [[str(x) for x in r] for r in datos["filas"]]
            for a in archivos or []:
                if a.lower().endswith((".csv", ".xlsx", ".xlsm")):
                    from .obras.obra import leer_tabla
                    self.st.setdefault("tablas", {})[key] = leer_tabla(self.ws / a)
                else:
                    self.st.setdefault("anexos", []).append({"key": key, "path": a, "title": f"{key}: {Path(a).name}"})
            avisos += self._chequeo_formato()
        elif paso == "checklist":
            sec = datos.get("seccion")
            if not sec:
                raise ValueError("Indica 'seccion' (id de la lista) y 'respuestas': [{n, r, c}].")
            dst = self.st.setdefault("checklists", {}).setdefault(sec, {})
            for r in datos.get("respuestas", []):
                dst[str(r["n"])] = {"r": r.get("r", ""), "c": r.get("c", "")}
        elif paso == "sustento":
            for a in archivos or []:
                if a.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".heic")) and datos.get("como") != "anexo":
                    self.st["fotos"].append({"path": a, "caption": datos.get("caption", ""), "group": "", "status": ""})
                else:
                    self.st.setdefault("anexos", []).append({"key": "sustento", "path": a,
                                                             "title": datos.get("titulo") or Path(a).name})
        elif paso == "notas":
            self.st["notas"] = (self.st["notas"] + "\n" + texto).strip() if texto else self.st["notas"]
            self.st["archivos"] += [a for a in archivos or [] if a not in self.st["archivos"]]
        elif paso == "plantilla":
            self.st["plantilla"] = datos.get("plantilla") or texto
            if not self.plantilla():
                raise ValueError(f"No existe la plantilla «{self.st['plantilla']}» (report_builder action=templates).")
        elif paso == "archivos":
            self.st["archivos"] += [a for a in archivos or [] if a not in self.st["archivos"]]
        elif paso == "tipo":
            self.st["datos"]["tipo"] = datos.get("tipo") or texto
        elif paso == "ritmo":
            self.st["ritmo"] = "paso a paso" if "paso" in (texto or datos.get("ritmo", "")).lower() else "rápido"
        else:
            raise ValueError(f"Paso desconocido: {paso}")
        self.st["omitidos"].pop(paso, None)
        pr = self.proyecto()   # si el borrador ya existe, lo nuevo también entra en él
        if pr is not None and paso in ("fotos", "notas", "cifras", "datos", "datos_extra", "firmantes", "tablas",
                                       "checklist", "sustento"):
            pr.update(photos=self.st["fotos"], notes=self.st["notas"], fields={**pr.data["fields"], **self.st["datos"]},
                      tables={**(pr.data.get("tables") or {}), **self.st.get("tablas", {})},
                      checklists=self.st.get("checklists", {}),
                      anexos=_uniq((pr.data.get("anexos") or []) + self.st.get("anexos", [])))
        return avisos

    def _ayuda_paso(self, pid: str) -> str:
        """Detalle técnico del paso actual para el agente: claves exactas de los datos, cuadros y preguntas."""
        t = self.plantilla()
        if not t or self.objetivo not in FORMATOS:
            return ""
        from .obras.plantillas import F_OBRA, F_RES, F_SUP, F_ET
        from .reports.engine import checklist_items
        comunes = {k for k, _ in F_OBRA + F_RES + F_SUP + F_ET} | {"fecha"}
        o = self.obra()
        v = {**(o.campos_informe() if o else {}), **self.st["datos"]}
        if pid in ("datos", "datos_extra"):
            fs = [f for f in t["fields"] if f["key"] not in comunes and bool(f.get("required")) == (pid == "datos")
                  and v.get(f["key"]) in (None, "")]
            return ("Claves para aportar (pídelas de 2 a 4 por vez, agrupadas por tema): "
                    + "; ".join(f"{f['key']} = {f['label']}" + (f" [máx. {f['max_words']} palabras]" if f.get("max_words") else "")
                                for f in fs[:14]))
        if pid == "firmantes":
            return ("Claves: res_nombre, res_dni, res_cip, res_designacion, res_monto, res_fecha, res_inicio, res_fin; "
                    "sup_nombre, sup_dni, sup_cip, sup_designacion, sup_monto, sup_fecha, sup_inicio, sup_fin.")
        if pid == "tablas":
            tiene = set(self.st.get("tablas", {})) | {a.get("key") for a in self.st.get("anexos", [])}
            return "Cuadros (aportar con datos.tabla=clave y archivos o datos.filas=[[cabecera…],[fila…]]): " + "; ".join(
                f"{s_['table']} = {s_['title']} | columnas: {' | '.join(s_.get('columns', []))}"
                + (f" | filas fijas: {', '.join(s_['rubros'][:4])}…" if s_.get("rubros") else "")
                for s_ in t["sections"] if s_["kind"] == "table" and s_.get("table") not in tiene)
        if pid == "checklist":
            resp = self.st.get("checklists", {})
            pend = []
            for s_ in t["sections"]:
                if s_["kind"] != "checklist":
                    continue
                for i, it in enumerate(checklist_items(s_), 1):
                    if not (resp.get(s_["id"], {}).get(str(i)) or {}).get("r"):
                        pend.append(f"[{s_['id']} n={i}] {it['pregunta']} ({'/'.join(s_.get('opciones', ['Sí', 'No', 'N/A']))})")
            return ("Siguientes preguntas (hazlas de 3 a 5 por vez; aporta con datos.seccion y datos.respuestas=[{n, r, c}]):\n  "
                    + "\n  ".join(pend[:5])) if pend else ""
        return ""

    def _chequeo_formato(self) -> list[str]:
        t = self.plantilla()
        if not t or self.objetivo not in FORMATOS:
            return []
        from .obras.formatos import chequear
        o = self.obra()
        campos = {**(o.campos_informe() if o else {}), **self.st["datos"]}
        return [f"[{h['nivel'].upper()}] {h['regla']}: {h['detalle']}" + (f" → esperado {h['esperado']}" if h["esperado"] else "")
                + (f". {h['sugerencia']}" if h["sugerencia"] else "")
                for h in chequear(t["id"], campos, self.st.get("tablas", {}), o)]

    def omitir(self, paso: str, motivo: str = "") -> None:
        p = next((x for x in self.pasos() if x.id == paso), None)
        if p is None:
            raise ValueError(f"Paso desconocido: {paso}")
        if not p.omitible:
            raise ValueError(f"El paso «{p.titulo}» es necesario y no se puede omitir.")
        self.st["omitidos"][paso] = motivo or "a pedido del usuario"

    # ---------------------------------------------------------- redacción
    def crear_borrador(self) -> str:
        from .reports.engine import ReportProject
        t = self.plantilla()
        if not t:
            raise ValueError("Falta elegir la plantilla.")
        bloqueantes = [e for e in self.estado() if e["id"] not in ("borrador", "secciones", "pdf")
                       and e["estado"] in ("actual", "pendiente") and not e["omitible"]]
        if bloqueantes:
            raise ValueError("Antes necesito: " + "; ".join(f"{e['titulo']} ({e['necesito']})" for e in bloqueantes))
        fields, extra, note = dict(self.st["datos"]), {}, ""
        if OBJETIVOS[self.objetivo]["obra"]:
            from .tools.reports_tool import _from_obra
            fields, extra, note = _from_obra(self.ctx, self.st.get("obra"), self.st.get("periodo"), t, fields)
        title = (f"{t['name'].split(' (')[0]} — {self.st.get('periodo')}" if self.st.get("periodo") else t["name"])
        p = ReportProject.create(self.ws, t, title, fields, self.st["notas"], self.st["fotos"],
                                 model=self.ctx.settings.model)
        extra = {**extra, "tables": {**extra.get("tables", {}), **self.st.get("tablas", {})},
                 "anexos": _uniq(extra.get("anexos", []) + self.st.get("anexos", [])),
                 "checklists": self.st.get("checklists", {})}
        p.update(**extra)
        self.st["report_id"] = p.id
        est = p.estimate()
        return (f"Borrador creado: {p.id} ({len(p.ai_units())} secciones a redactar; ≈ {est['usd']} USD).{note}")

    def siguiente_seccion(self):
        p = self.proyecto()
        if not p:
            return None
        # orden de redacción: primero el cuerpo; lo que resume todo (depends_on '*', p. ej. el resumen
        # ejecutivo) al final, cuando ya existe lo que resume
        units = sorted((u for u in p.ai_units() if u.kind != "outline"), key=lambda u: "*" in u.depends_on)
        return next((u for u in units if u.id not in self.st["aprobadas"]), None)

    def redactar(self, writer=None, seccion: str | None = None, todas: bool = False) -> str:
        from .reports.engine import ReportGenerator
        p = self.proyecto()
        if not p:
            return self.crear_borrador() + "\n\n" + self.redactar(writer, seccion, todas)
        gen = ReportGenerator(self.ctx.settings, p, writer=writer, emit=self.ctx.emit)
        if todas:
            gen.run()
            return "Redacté todas las secciones pendientes. Revísalas en el PDF; dime qué cambiar."
        u = None
        if seccion:
            u = next((x for x in p.ai_units() if x.id == seccion or x.title.lower() == seccion.lower()), None)
        u = u or self.siguiente_seccion()
        if u is None:
            return "No quedan secciones por redactar."
        if p.data["units"].get(u.id, {}).get("status") != "done" or seccion or p.data["units"][u.id].get("feedback"):
            gen.run(only=[u.id], force=True)
        f = p.section_file(u.id)
        txt = f.read_text("utf-8") if f.exists() else "(no se pudo redactar: " + str(p.data["units"].get(u.id, {}).get("error")) + ")"
        return (f"SECCIÓN «{(u.chapter + ' › ') if u.chapter else ''}{u.title}» [{u.id}]\n\n{txt}\n\n"
                "Muéstrasela al usuario (o un resumen si es larga) y pregunta: aprobar, cambiar algo o editarla él.")

    def corregir(self, seccion: str, instrucciones: str, writer=None) -> str:
        p = self.proyecto()
        if not p:
            raise ValueError("Aún no hay borrador.")
        prev = p.data["units"].get(seccion, {}).get("feedback", "")
        p.set_unit(seccion, feedback=(prev + "\n" + instrucciones).strip(), edited=False)
        if seccion in self.st["aprobadas"]:
            self.st["aprobadas"].remove(seccion)
        return self.redactar(writer, seccion)

    def editar(self, seccion: str, markdown: str) -> None:
        p = self.proyecto()
        p.section_file(seccion).write_text(markdown, "utf-8")
        p.set_unit(seccion, status="done", edited=True, words=len(markdown.split()))

    def aprobar(self, seccion: str | None = None) -> None:
        p = self.proyecto()
        if not p:
            raise ValueError("Aún no hay borrador.")
        ids = [u.id for u in p.ai_units()] if seccion in (None, "", "*", "todas") else [seccion]
        for sid in ids:
            if p.data["units"].get(sid, {}).get("status") != "done":
                if seccion in (None, "", "*", "todas"):
                    continue
                raise ValueError(f"La sección {sid} aún no está redactada.")
            if sid not in self.st["aprobadas"]:
                self.st["aprobadas"].append(sid)

    def finalizar(self) -> tuple[Path, list[str]]:
        from .reports.engine import build_report_pdf
        p = self.proyecto()
        if not p:
            raise ValueError("Aún no hay borrador.")
        pdf = build_report_pdf(self.ctx.settings, p)
        avisos = list(p.data.get("outputs", {}).get("warnings", []))
        avisos += _chequeo_cifras({**p.data["fields"], **self.st["datos"]})
        avisos += self._chequeo_formato()
        pend = [u.title for u in p.ai_units() if u.id not in self.st["aprobadas"]]
        if pend and self.st.get("ritmo") == "paso a paso":
            avisos.append("Secciones sin aprobar: " + ", ".join(pend))
        self.st["revisado"] = True
        return pdf, avisos


def _uniq(anexos: list[dict]) -> list[dict]:
    seen, out = set(), []
    for a in anexos:
        if a["path"] not in seen:
            seen.add(a["path"])
            out.append(a)
    return out


def _chequeo_cifras(d: dict) -> list[str]:
    """Comprobaciones inmediatas (sin IA) de las cifras que da el usuario."""
    from .obras.obra import parse_num
    av = []
    v, mm, ad, de, tot = (parse_num(d.get(k)) for k in ("valorizacion_acumulada", "mayores_metrados", "adicionales",
                                                         "deductivos", "total_ejecutado"))
    if v is not None and tot is not None and abs(v + (mm or 0) + (ad or 0) - abs(de or 0) - tot) > max(1, tot * 0.001):
        av.append(f"Total ejecutado {tot:,.2f} ≠ valorización + mayores metrados + adicionales − deductivos "
                  f"({v + (mm or 0) + (ad or 0) - abs(de or 0):,.2f}).")
    pa, ea = parse_num(d.get("avance_programado")), parse_num(d.get("avance_real"))
    if pa and ea is not None and (pa - ea) / pa > 0.20:
        av.append(f"Atraso de {(pa - ea) / pa:.0%} (> 20 %): el informe debe proponer acciones y cronograma "
                  "acelerado; pregúntale al usuario cuáles son.")
    for k in ("avance_programado", "avance_real"):
        x = parse_num(d.get(k))
        if x is not None and not 0 <= x <= 100:
            av.append(f"{k} = {x}: debe estar entre 0 y 100 %.")
    return av
